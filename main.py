import requests
import psycopg2
import os
import datetime
from datetime import timedelta
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv

# Loads environment variables from the .env file
load_dotenv()

# Email Configuration
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")

# Splits the comma-separated string into a list
receiver_emails_env = os.getenv("RECEIVER_EMAILS", "")
RECEIVER_EMAILS = [email.strip() for email in receiver_emails_env.split(",")]

# Global Configurations
SESSION_TOKEN = os.getenv("SESSION_TOKEN")
APPID = os.getenv("APPID", "cluster")
URL_ACCOUNTS = (
    "https://jca.paas.saveincloud.net.br/JBilling/billing/account/rest/getaccounts"
)
URL_BILLING = "https://jca.paas.saveincloud.net.br/JBilling/billing/account/rest/getaccountbillinghistorybyperiodinner"
URL_FUNDING = "https://jca.paas.saveincloud.net.br/JBilling/billing/account/rest/getfundaccounthistory"

# Emails that should NEVER appear in the metrics
EXCLUDED_EMAILS = ["apresentacao@saveincloud.com"]


# Database connection and setup
def get_db_connection():
    """Connects to PostgreSQL and ensures tables creation"""
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "db"),
        database=os.getenv("DB_NAME", "billing"),
        port=os.getenv("DB_PORT", "5432"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD"),
    )

    cursor = conn.cursor()

    # Table 1: Standard daily consumption
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_billing (
            id SERIAL PRIMARY KEY,
            date TIMESTAMP,
            uid INTEGER,
            email VARCHAR(255),
            consumption NUMERIC(10, 4)
        )
    """)

    # Table 2: Conversions Vault
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS client_conversions (
            uid INTEGER PRIMARY KEY,
            email VARCHAR(255),
            conversion_date TIMESTAMP
        )
    """)

    # Table 3: Daily Funding (Recargas)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_funding (
            id SERIAL PRIMARY KEY,
            date TIMESTAMP,
            uid INTEGER,
            email VARCHAR(255),
            amount NUMERIC(10, 4)
        )
    """)

    conn.commit()
    cursor.close()
    return conn


# API Interaction Functions
def get_accounts():
    """Fetches accounts from the billing_incentivo group"""
    params = {
        "appid": APPID,
        "session": SESSION_TOKEN,
        "startRow": 0,
        "resultCount": 100,
        "orderField": "email",
        "orderDirection": "ASC",
        "filterField": "group",
        "filterValue": "billing_incentivo",
        "charset": "UTF-8",
    }
    response = requests.get(URL_ACCOUNTS, params=params, timeout=30)
    data = response.json()

    if data.get("result") == 0:
        return data.get("array", [])
    else:
        print("Error fetching accounts:", data)
        return []


# This function is used to find out the exact time a user made their first funding payment yesterday.
def get_conversion_time(uid, start_time, end_time):
    """Fetches the exact time a user made their first funding payment yesterday"""
    params = {
        "appid": APPID,
        "session": SESSION_TOKEN,
        "uid": uid,
        "starttime": start_time,
        "endtime": end_time,
        "startRow": 0,
        "resultCount": 100,
        "charset": "UTF-8",
    }

    response = requests.get(URL_FUNDING, params=params, timeout=30)
    data = response.json()

    if data.get("result") == 0 and "responses" in data:
        fundings = [r for r in data["responses"] if r.get("chargeType") == "FUND"]
        if fundings:
            fundings.sort(key=lambda x: x["operationDate"])
            first_funding_ms = fundings[0]["operationDate"]
            conversion_date = datetime.datetime.fromtimestamp(first_funding_ms / 1000.0)
            return conversion_date.strftime("%Y-%m-%d %H:%M:%S")

    return None


# This function calculates the total amount funded by the user in the given period, which is important to understand how much of the consumption can be covered by the incentive.
def get_funding_amount_for_account(uid, start_time, end_time):
    """Busca o valor total recarregado pelo cliente no período"""
    params = {
        "appid": APPID,
        "session": SESSION_TOKEN,
        "uid": uid,
        "starttime": start_time,
        "endtime": end_time,
        "startRow": 0,
        "resultCount": 100,
        "charset": "UTF-8",
    }

    response = requests.get(URL_FUNDING, params=params, timeout=30)
    data = response.json()

    total_funding = 0.0

    if data.get("result") == 0 and "responses" in data:
        # Pega apenas os registros do tipo 'FUND' (Pagamentos/Recargas)
        fundings = [r for r in data["responses"] if r.get("chargeType") == "FUND"]
        for f in fundings:
            # A Jelastic geralmente retorna o valor recarregado no campo 'amount'
            total_funding += f.get("amount", 0.0)

    return total_funding


# This function is the core of the data collection process. It fetches the consumption for a specific account in the given period, and if we have an exact conversion time (first funding), it uses that as the end time to avoid counting costs that occurred after the conversion, which shouldn't be part of the incentive calculation.
def get_billing_for_account(uid, email, start_time, end_time, custom_endtime=None):
    """Fetches the consumption of a specific account for yesterday's period"""
    if custom_endtime is None:
        custom_endtime = end_time

    params = {
        "appid": APPID,
        "session": SESSION_TOKEN,
        "period": "day",
        "groupNodes": "false",
        "uid": uid,
        "node": "root",
        "charset": "UTF-8",
        "starttime": start_time,
        "endtime": custom_endtime,
        "email": email,
    }

    response = requests.get(URL_BILLING, params=params, timeout=30)
    history_data = response.json()

    total_daily_cost = 0.0

    if history_data.get("result") == 0 and "array" in history_data:
        items = history_data["array"]
        for item in items:
            total_daily_cost += item.get("cost", 0.0)
    else:
        print(f"Warning: No consumption data found for {email}")

    return total_daily_cost


# This function generates a well-formatted HTML email report with the consumption data, including a ranking of clients by consumption and the percentage variation compared to the previous day. It also calculates and displays the total consumption at the end of the table. Finally, it sends the email to the configured recipients.
def send_email_report(report_data, report_date_str, report_obj_date):
    """Gera um relatório HTML executivo e envia por email"""
    msg = MIMEMultipart()
    msg["From"] = SENDER_EMAIL
    msg["To"] = ", ".join(RECEIVER_EMAILS)

    # Formatação de data por extenso em PT-BR
    meses = [
        "janeiro",
        "fevereiro",
        "março",
        "abril",
        "maio",
        "junho",
        "julho",
        "agosto",
        "setembro",
        "outubro",
        "novembro",
        "dezembro",
    ]
    data_extenso = f"{report_obj_date.day:02d} de {meses[report_obj_date.month-1]} de {report_obj_date.year}"

    msg["Subject"] = (
        f"[Billing Incentivo] Resumo Diário — {report_obj_date.strftime('%d/%m/%Y')}"
    )

    # Ordena e calcula KPIs
    report_data_sorted = sorted(
        report_data, key=lambda r: r["consumption"], reverse=True
    )
    total_consumption = sum(row["consumption"] for row in report_data_sorted)
    total_clients = len(report_data_sorted)
    active_clients = len([r for r in report_data_sorted if r["consumption"] > 0])
    avg_ticket = (total_consumption / active_clients) if active_clients > 0 else 0.0

    # Helper para badge de variação (sem emoji, mais limpo)
    def render_variation(variation_str):
        # variation_str vem como "⬆️ 6.72%" / "⬇️ -10.18%" / "➖ 0.0%"
        if "⬆️" in variation_str:
            color_bg = "#e8f5e9"
            color_txt = "#1b5e20"
            arrow = "▲"
        elif "⬇️" in variation_str:
            color_bg = "#ffebee"
            color_txt = "#b71c1c"
            arrow = "▼"
        else:
            color_bg = "#eceff1"
            color_txt = "#546e7a"
            arrow = "—"
        pct = variation_str.split(" ", 1)[1] if " " in variation_str else variation_str
        return f'<span style="background:{color_bg};color:{color_txt};padding:4px 10px;border-radius:12px;font-size:12px;font-weight:600;display:inline-block;">{arrow} {pct}</span>'

    # Medalhas para o top 3
    def rank_display(idx):
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        return medals.get(idx, str(idx))

    html_content = f"""
    <html>
    <head><meta charset="UTF-8"></head>
    <body style="margin:0;padding:0;background-color:#f4f6f8;font-family:'Segoe UI',Helvetica,Arial,sans-serif;color:#2c3e50;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f6f8;padding:30px 0;">
            <tr><td align="center">
                <table width="720" cellpadding="0" cellspacing="0" style="background-color:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.06);">

                    <!-- HEADER -->
                    <tr><td style="background:linear-gradient(135deg,#1a73e8 0%,#0d47a1 100%);padding:32px 40px;">
                        <h1 style="margin:0;color:#ffffff;font-size:24px;font-weight:600;letter-spacing:-0.3px;">Billing Incentivo · Resumo Diário</h1>
                        <p style="margin:6px 0 0;color:#bbdefb;font-size:14px;">Referência: {data_extenso}</p>
                    </td></tr>

                    <!-- KPIs -->
                    <tr><td style="padding:28px 40px 8px;">
                        <table width="100%" cellpadding="0" cellspacing="0">
                            <tr>
                                <td width="33%" style="padding:16px;background:#f8fafc;border-radius:8px;border-left:4px solid #1a73e8;">
                                    <div style="font-size:11px;color:#78909c;text-transform:uppercase;letter-spacing:0.5px;font-weight:600;">Consumo Total</div>
                                    <div style="font-size:22px;color:#0d47a1;font-weight:700;margin-top:6px;">R$ {total_consumption:,.2f}</div>
                                </td>
                                <td width="4"></td>
                                <td width="33%" style="padding:16px;background:#f8fafc;border-radius:8px;border-left:4px solid #43a047;">
                                    <div style="font-size:11px;color:#78909c;text-transform:uppercase;letter-spacing:0.5px;font-weight:600;">Clientes Ativos</div>
                                    <div style="font-size:22px;color:#1b5e20;font-weight:700;margin-top:6px;">{active_clients} <span style="font-size:13px;color:#90a4ae;font-weight:400;">/ {total_clients}</span></div>
                                </td>
                                <td width="4"></td>
                                <td width="33%" style="padding:16px;background:#f8fafc;border-radius:8px;border-left:4px solid #fb8c00;">
                                    <div style="font-size:11px;color:#78909c;text-transform:uppercase;letter-spacing:0.5px;font-weight:600;">Ticket Médio</div>
                                    <div style="font-size:22px;color:#e65100;font-weight:700;margin-top:6px;">R$ {avg_ticket:,.2f}</div>
                                </td>
                            </tr>
                        </table>
                    </td></tr>

                    <!-- INTRO -->
                    <tr><td style="padding:24px 40px 8px;">
                        <p style="margin:0;font-size:14px;color:#546e7a;line-height:1.6;">
                            Segue abaixo o ranking de consumo do dia anterior, ordenado do maior para o menor, com a variação percentual em relação ao dia retrasado.
                        </p>
                    </td></tr>

                    <!-- TABELA -->
                    <tr><td style="padding:16px 40px 32px;">
                        <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:14px;">
                            <thead>
                                <tr style="background-color:#f1f4f8;">
                                    <th style="padding:12px 10px;text-align:center;color:#37474f;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:0.5px;border-bottom:2px solid #cfd8dc;width:50px;">#</th>
                                    <th style="padding:12px 10px;text-align:left;color:#37474f;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:0.5px;border-bottom:2px solid #cfd8dc;">Cliente</th>
                                    <th style="padding:12px 10px;text-align:right;color:#37474f;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:0.5px;border-bottom:2px solid #cfd8dc;">Consumo</th>
                                    <th style="padding:12px 10px;text-align:center;color:#37474f;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:0.5px;border-bottom:2px solid #cfd8dc;">Variação</th>
                                </tr>
                            </thead>
                            <tbody>
    """

    for idx, row in enumerate(report_data_sorted, start=1):
        bg = "#ffffff" if idx % 2 == 1 else "#fafbfc"
        html_content += f"""
                                <tr style="background-color:{bg};">
                                    <td style="padding:12px 10px;text-align:center;font-weight:600;color:#455a64;border-bottom:1px solid #eceff1;">{rank_display(idx)}</td>
                                    <td style="padding:12px 10px;color:#263238;border-bottom:1px solid #eceff1;">{row['email']}</td>
                                    <td style="padding:12px 10px;text-align:right;color:#263238;font-variant-numeric:tabular-nums;border-bottom:1px solid #eceff1;font-weight:500;">R$ {row['consumption']:,.4f}</td>
                                    <td style="padding:12px 10px;text-align:center;border-bottom:1px solid #eceff1;">{render_variation(row['variation'])}</td>
                                </tr>
        """

    html_content += f"""
                                <tr style="background-color:#0d47a1;">
                                    <td style="padding:14px 10px;text-align:center;color:#ffffff;font-weight:700;">Σ</td>
                                    <td style="padding:14px 10px;color:#ffffff;font-weight:700;letter-spacing:0.3px;">TOTAL GERAL</td>
                                    <td style="padding:14px 10px;text-align:right;color:#ffffff;font-weight:700;font-size:15px;font-variant-numeric:tabular-nums;">R$ {total_consumption:,.4f}</td>
                                    <td style="padding:14px 10px;text-align:center;color:#bbdefb;">—</td>
                                </tr>
                            </tbody>
                        </table>
                    </td></tr>

                    <!-- FOOTER -->
                    <tr><td style="background-color:#f8fafc;padding:24px 40px;border-top:1px solid #eceff1;">
                        <table width="100%" cellpadding="0" cellspacing="0">
                            <tr>
                                <td style="font-size:12px;color:#78909c;line-height:1.6;">
                                    <strong style="color:#37474f;">Pedro Carriel</strong><br>
                                    Consultor Técnico<br>
                                    <span style="color:#90a4ae;">SaveinCloud</span>
                                </td>
                                <td style="text-align:right;font-size:11px;color:#b0bec5;">
                                    Relatório gerado automaticamente<br>
                                    {report_obj_date.strftime('%d/%m/%Y')}
                                </td>
                            </tr>
                        </table>
                    </td></tr>

                </table>
                <p style="font-size:11px;color:#b0bec5;margin:16px 0 0;">Este é um email automatizado. Em caso de divergência, contate o time de Consultoria.</p>
            </td></tr>
        </table>
    </body>
    </html>
    """

    msg.attach(MIMEText(html_content, "html"))

    try:
        print("\nConnecting to SMTP Server...")
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)
        server.quit()
        print("✅ Email sent successfully!")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")


# This is the main function that orchestrates the entire data collection, processing, and reporting workflow. It calculates the relevant dates, fetches accounts from both the API and the database, processes each account's consumption and funding data, calculates variations, stores everything in the database, and finally generates and sends the email report.
def process_daily_billing(target_today_date):

    yesterday_obj = target_today_date - timedelta(days=1)
    yesterday_date = yesterday_obj.strftime("%Y-%m-%d 00:00:00")

    day_before_yesterday_obj = yesterday_obj - timedelta(days=1)
    day_before_yesterday_date = day_before_yesterday_obj.strftime("%Y-%m-%d 00:00:00")

    yesterday_start_jelastic = yesterday_obj.strftime("%Y-%m-%d 00:00:00")
    yesterday_end_jelastic = yesterday_obj.strftime("%Y-%m-%d 23:59:59")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM daily_billing WHERE date = %s", (yesterday_date,))
    cursor.execute("DELETE FROM daily_funding WHERE date = %s", (yesterday_date,))
    conn.commit()

    api_accounts = get_accounts()

    api_uids = {acc["uid"] for acc in api_accounts}
    accounts_dict = {acc["uid"]: acc["email"] for acc in api_accounts}

    cursor.execute(
        """
        SELECT DISTINCT uid, email FROM daily_billing 
        WHERE date = %s
    """,
        (day_before_yesterday_date,),
    )
    db_accounts = cursor.fetchall()

    for uid, email in db_accounts:
        if uid not in accounts_dict:
            accounts_dict[uid] = email

    accounts = [{"uid": uid, "email": email} for uid, email in accounts_dict.items()]

    print(f"\n[!] Data de Referência do processamento: {yesterday_date[:10]}")
    print(f"Found {len(accounts)} accounts (API + DB). Processing costs...")

    report = []

    for account in accounts:
        uid = account["uid"]
        email = account["email"]

        if email in EXCLUDED_EMAILS:
            continue

        is_in_api = uid in api_uids

        if not is_in_api:
            cursor.execute("SELECT 1 FROM client_conversions WHERE uid = %s", (uid,))
            if cursor.fetchone():
                continue

            exact_leave_time = get_conversion_time(
                uid, yesterday_start_jelastic, yesterday_end_jelastic
            )

            leave_time_to_save = (
                exact_leave_time if exact_leave_time else yesterday_end_jelastic
            )

            cursor.execute(
                """
                INSERT INTO client_conversions (uid, email, conversion_date)
                VALUES (%s, %s, %s)
                ON CONFLICT (uid) DO NOTHING
            """,
                (uid, email, leave_time_to_save),
            )
            conn.commit()

            yesterday_consumption = get_billing_for_account(
                uid,
                email,
                yesterday_start_jelastic,
                yesterday_end_jelastic,
                custom_endtime=exact_leave_time,
            )
        else:
            yesterday_consumption = get_billing_for_account(
                uid, email, yesterday_start_jelastic, yesterday_end_jelastic
            )

        cursor.execute(
            """
            SELECT consumption FROM daily_billing 
            WHERE uid = %s AND date = %s
        """,
            (uid, day_before_yesterday_date),
        )
        day_before_yesterday_result = cursor.fetchone()

        day_before_yesterday_consumption = (
            float(day_before_yesterday_result[0])
            if day_before_yesterday_result
            else 0.0
        )

        if day_before_yesterday_consumption > 0:
            variation_pct = (
                (yesterday_consumption - day_before_yesterday_consumption)
                / day_before_yesterday_consumption
            ) * 100
        else:
            variation_pct = 0.0

        cursor.execute(
            """
            INSERT INTO daily_billing (date, uid, email, consumption)
            VALUES (%s, %s, %s, %s)
        """,
            (yesterday_date, uid, email, yesterday_consumption),
        )

        yesterday_funding = get_funding_amount_for_account(
            uid, yesterday_start_jelastic, yesterday_end_jelastic
        )

        if yesterday_funding > 0.0:
            cursor.execute(
                """
                INSERT INTO daily_funding (date, uid, email, amount)
                VALUES (%s, %s, %s, %s)
            """,
                (yesterday_date, uid, email, yesterday_funding),
            )

        trend = "⬆️" if variation_pct > 0 else "⬇️" if variation_pct < 0 else "➖"
        report.append(
            {
                "email": email,
                "consumption": yesterday_consumption,
                "variation": f"{trend} {round(variation_pct, 2)}%",
            }
        )

    conn.commit()
    cursor.close()
    conn.close()

    print("--- Preliminary Report ---")
    for r in report:
        print(f"{r['email']} | R$ {r['consumption']:.4f} | {r['variation']}")

    if report:
        send_email_report(report, yesterday_date[:10], yesterday_obj)


if __name__ == "__main__":
    # ====================================================================
    # 🟢 MODO BACKFILL (MÁQUINA DO TEMPO)
    # Descomente este bloco, rode o script, e ele vai reprocessar o passado.
    # Após rodar com sucesso, comente isso aqui de volta!
    # ====================================================================

    #  dates_to_fix = [
    #      datetime.date(2026, 3, 2), # Vai apagar e refazer o dia 01/03
    #      datetime.date(2026, 3, 3), # Vai apagar e refazer o dia 02/03
    #      datetime.date(2026, 3, 4), # Vai apagar e refazer o dia 03/03
    #      datetime.date(2026, 3, 5), # Vai apagar e refazer o dia 04/03
    #  ]
    #  for d in dates_to_fix:
    #      process_daily_billing(d)

    # ====================================================================
    # 🔵 MODO PRODUÇÃO NORMAL
    # É isso que deve ficar ativado lá no Docker da SaveinCloud.
    # A data do momento em que a função dispara!
    # ====================================================================

    process_daily_billing(datetime.date.today())
