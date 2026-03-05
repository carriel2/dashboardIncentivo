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
URL_ACCOUNTS = "https://jca.paas.saveincloud.net.br/JBilling/billing/account/rest/getaccounts"
URL_BILLING = "https://jca.paas.saveincloud.net.br/JBilling/billing/account/rest/getaccountbillinghistorybyperiodinner"
URL_FUNDING = "https://jca.paas.saveincloud.net.br/JBilling/billing/account/rest/getfundaccounthistory"

# Emails that should NEVER appear in the metrics
EXCLUDED_EMAILS = ["apresentacao@saveincloud.com"]

# =========================================================================
# 🛑 VARIÁVEIS DE DATA REMOVIDAS DAQUI DO ESCOPO GLOBAL! 🛑
# Agora elas são calculadas em tempo real dentro da função principal
# para evitar que o Docker congele a data de execução.
# =========================================================================

def get_db_connection():
    """Connects to PostgreSQL and ensures tables creation"""
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "db"),
        database=os.getenv("DB_NAME", "billing"),
        port=os.getenv("DB_PORT", "5432"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD")
    )
    
    cursor = conn.cursor()
    
    # Table 1: Standard daily consumption
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_billing (
            id SERIAL PRIMARY KEY,
            date TIMESTAMP,
            uid INTEGER,
            email VARCHAR(255),
            consumption NUMERIC(10, 4)
        )
    ''')
    
    # Table 2: Conversions Vault
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS client_conversions (
            uid INTEGER PRIMARY KEY,
            email VARCHAR(255),
            conversion_date TIMESTAMP
        )
    ''')
    
    conn.commit()
    cursor.close()
    return conn

def get_accounts():
    """Fetches accounts from the billing_incentivo group"""
    params = {
        'appid': APPID,
        'session': SESSION_TOKEN,
        'startRow': 0,
        'resultCount': 100,
        'orderField': 'email',
        'orderDirection': 'ASC',
        'filterField': 'group',
        'filterValue': 'billing_incentivo',
        'charset': 'UTF-8'
    }
    response = requests.get(URL_ACCOUNTS, params=params, timeout=30)
    data = response.json()
    
    if data.get('result') == 0:
        return data.get('array', [])
    else:
        print("Error fetching accounts:", data)
        return []

def get_conversion_time(uid, start_time, end_time):
    """Fetches the exact time a user made their first funding payment yesterday"""
    params = {
        'appid': APPID,
        'session': SESSION_TOKEN,
        'uid': uid,
        'starttime': start_time,
        'endtime': end_time,
        'startRow': 0,
        'resultCount': 100,
        'charset': 'UTF-8'
    }
    
    response = requests.get(URL_FUNDING, params=params, timeout=30)
    data = response.json()
    
    if data.get('result') == 0 and 'responses' in data:
        fundings = [r for r in data['responses'] if r.get('chargeType') == 'FUND']
        if fundings:
            fundings.sort(key=lambda x: x['operationDate'])
            first_funding_ms = fundings[0]['operationDate']
            conversion_date = datetime.datetime.fromtimestamp(first_funding_ms / 1000.0)
            return conversion_date.strftime("%Y-%m-%d %H:%M:%S")
            
    return None 

def get_billing_for_account(uid, email, start_time, end_time, custom_endtime=None):
    """Fetches the consumption of a specific account for yesterday's period"""
    if custom_endtime is None:
        custom_endtime = end_time

    params = {
        'appid': APPID,
        'session': SESSION_TOKEN,
        'period': 'day',
        'groupNodes': 'false',
        'uid': uid,
        'node': 'root',
        'charset': 'UTF-8',
        'starttime': start_time,
        'endtime': custom_endtime, 
        'email': email
    }
    
    response = requests.get(URL_BILLING, params=params, timeout=30)
    history_data = response.json()
    
    total_daily_cost = 0.0
    
    if history_data.get('result') == 0 and 'array' in history_data:
        items = history_data['array']
        for item in items:
            total_daily_cost += item.get('cost', 0.0)
    else:
        print(f"Warning: No consumption data found for {email}")
            
    return total_daily_cost

def send_email_report(report_data, report_date_str, report_obj_date):
    """Generates an HTML email report and sends it to the recipients"""
    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = ", ".join(RECEIVER_EMAILS)
    msg['Subject'] = f"Resumo diário Billing Incentivo - {report_date_str}"
    
    # 1. Calcula o total somando o consumo de todo mundo da lista
    total_consumption = sum(row['consumption'] for row in report_data)
    
    # Keeping the Email UI in Portuguese
    html_content = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; color: #333; }}
            table {{ border-collapse: collapse; width: 100%; }}
            th, td {{ border: 1px solid #dddddd; text-align: left; padding: 10px; }}
            th {{ background-color: #0056b3; color: white; }}
            tr:nth-child(even) {{ background-color: #f9f9f9; }}
            .total-row {{ background-color: #d1ecf1; font-weight: bold; color: #0c5460; }}
        </style>
    </head>
    <body>
        <h2>Resumo Billing Incentivo - {report_obj_date.strftime("%d/%m/%Y")}</h2>
        <p>Aqui está o resumo do consumo referente ao dia anterior.</p>
        <table>
            <tr>
                <th>Email</th>
                <th>Consumo (R$)</th>
                <th>Variação (%)</th>
            </tr>
    """
    
    # 2. Preenche as linhas dos clientes
    for row in report_data:
        html_content += f"""
            <tr>
                <td>{row['email']}</td>
                <td>R$ {row['consumption']:.4f}</td>
                <td>{row['variation']}</td>
            </tr>
        """
        
    # 3. Adiciona a linha do TOTAL destacada no final
    html_content += f"""
            <tr class="total-row">
                <td>TOTAL GERAL</td>
                <td>R$ {total_consumption:.4f}</td>
                <td>➖</td>
            </tr>
        </table>
        <p style="margin-top: 20px; font-size: 12px; color: #777;">
            <i>Relatório gerado automaticamente via Python.</i>
        </p>
    </body>
    </html>
    """
        
    msg.attach(MIMEText(html_content, 'html'))
    
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
    conn.commit()
    
    api_accounts = get_accounts()
    
    api_uids = {acc['uid'] for acc in api_accounts}
    accounts_dict = {acc['uid']: acc['email'] for acc in api_accounts}
    
    cursor.execute('''
        SELECT DISTINCT uid, email FROM daily_billing 
        WHERE date = %s
    ''', (day_before_yesterday_date,))
    db_accounts = cursor.fetchall()
    
    for uid, email in db_accounts:
        if uid not in accounts_dict:
            accounts_dict[uid] = email
            
    accounts = [{'uid': uid, 'email': email} for uid, email in accounts_dict.items()]
    
    print(f"\n[!] Data de Referência do processamento: {yesterday_date[:10]}")
    print(f"Found {len(accounts)} accounts (API + DB). Processing costs...")
    
    report = []

    for account in accounts:
        uid = account['uid']
        email = account['email']
        
        if email in EXCLUDED_EMAILS:
            continue
            
        is_in_api = uid in api_uids
        
        if not is_in_api:
            exact_leave_time = get_conversion_time(uid, yesterday_start_jelastic, yesterday_end_jelastic)
            
            if exact_leave_time:
                cursor.execute('''
                    INSERT INTO client_conversions (uid, email, conversion_date)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (uid) DO NOTHING
                ''', (uid, email, exact_leave_time))
                conn.commit()
                
                yesterday_consumption = get_billing_for_account(uid, email, yesterday_start_jelastic, yesterday_end_jelastic, custom_endtime=exact_leave_time)
            else:
                yesterday_consumption = get_billing_for_account(uid, email, yesterday_start_jelastic, yesterday_end_jelastic)
                
            if yesterday_consumption == 0.0:
                continue
        else:
            yesterday_consumption = get_billing_for_account(uid, email, yesterday_start_jelastic, yesterday_end_jelastic)
            
        cursor.execute('''
            SELECT consumption FROM daily_billing 
            WHERE uid = %s AND date = %s
        ''', (uid, day_before_yesterday_date))
        day_before_yesterday_result = cursor.fetchone()
        
        day_before_yesterday_consumption = float(day_before_yesterday_result[0]) if day_before_yesterday_result else 0.0
        
        if day_before_yesterday_consumption > 0:
            variation_pct = ((yesterday_consumption - day_before_yesterday_consumption) / day_before_yesterday_consumption) * 100
        else:
            variation_pct = 0.0 
            
        cursor.execute('''
            INSERT INTO daily_billing (date, uid, email, consumption)
            VALUES (%s, %s, %s, %s)
        ''', (yesterday_date, uid, email, yesterday_consumption))
        
        trend = "⬆️" if variation_pct > 0 else "⬇️" if variation_pct < 0 else "➖"
        report.append({
            'email': email,
            'consumption': yesterday_consumption,
            'variation': f"{trend} {round(variation_pct, 2)}%"
        })

    conn.commit()
    cursor.close()
    conn.close()
    
    print("--- Preliminary Report ---")
    for r in report:
        print(f"{r['email']} | R$ {r['consumption']:.4f} | {r['variation']}")


    if report:
        send_email_report(report, yesterday_date[:10], yesterday_obj)


if __name__ == '__main__':
    # ====================================================================
    # 🟢 MODO BACKFILL (MÁQUINA DO TEMPO)
    # Descomente este bloco, rode o script, e ele vai reprocessar o passado.
    # Após rodar com sucesso, comente isso aqui de volta!
    # ====================================================================
    
     #dates_to_fix = [
         #datetime.date(2026, 3, 2), # Vai apagar e refazer o dia 01/03
         #datetime.date(2026, 3, 3), # Vai apagar e refazer o dia 02/03
         #datetime.date(2026, 3, 4), # Vai apagar e refazer o dia 03/03
         #datetime.date(2026, 3, 5), # Vai apagar e refazer o dia 04/03
     #]
     #for d in dates_to_fix:
         #process_daily_billing(d)
        
    
    # ====================================================================
    # 🔵 MODO PRODUÇÃO NORMAL
    # É isso que deve ficar ativado lá no Docker da SaveinCloud.
    # A data do momento em que a função dispara!
    # ====================================================================
    
    process_daily_billing(datetime.date.today())