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
URL_ACCOUNTS = "https://jca.jelastic.saveincloud.net/JBilling/billing/account/rest/getaccounts"
URL_BILLING = "https://jca.jelastic.saveincloud.net/JBilling/billing/account/rest/getaccountbillinghistorybyperiodinner"
URL_FUNDING = "https://jca.jelastic.saveincloud.net/JBilling/billing/account/rest/getfundaccounthistory"

# Emails that should NEVER appear in the metrics
EXCLUDED_EMAILS = ["apresentacao@saveincloud.com"]

# Defining dates (Calculating "Yesterday's" consumption with JCA Precision)
yesterday_obj = datetime.date.today() - timedelta(days=1)
yesterday_date = yesterday_obj.strftime("%Y-%m-%d 00:00:00") 

day_before_yesterday_obj = yesterday_obj - timedelta(days=1)
day_before_yesterday_date = day_before_yesterday_obj.strftime("%Y-%m-%d 00:00:00")

yesterday_start_jelastic = yesterday_obj.strftime("%Y-%m-%d 00:00:00")
yesterday_end_jelastic = yesterday_obj.strftime("%Y-%m-%d 23:59:59") 

def get_db_connection():
    """Conecta ao PostgreSQL e garante a criação das tabelas"""
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "db"),
        database=os.getenv("DB_NAME", "billing"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD")
    )
    
    cursor = conn.cursor()
    
    # Tabela 1: O consumo diário normal
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_billing (
            id SERIAL PRIMARY KEY,
            date TIMESTAMP,
            uid INTEGER,
            email VARCHAR(255),
            consumption NUMERIC(10, 4)
        )
    ''')
    
    # Tabela 2: O Cofre de Conversões
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
        print("Erro ao buscar contas:", data)
        return []

def get_conversion_time(uid):
    """Fetches the exact time a user made their first funding payment yesterday"""
    params = {
        'appid': APPID,
        'session': SESSION_TOKEN,
        'uid': uid,
        'starttime': yesterday_start_jelastic,
        'endtime': yesterday_end_jelastic,
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

def get_billing_for_account(uid, email, custom_endtime=None):
    """Fetches the consumption of a specific account for yesterday's period"""
    if custom_endtime is None:
        custom_endtime = yesterday_end_jelastic

    params = {
        'appid': APPID,
        'session': SESSION_TOKEN,
        'period': 'day',
        'groupNodes': 'false',
        'uid': uid,
        'node': 'root',
        'charset': 'UTF-8',
        'starttime': yesterday_start_jelastic,
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
        print(f"Aviso: Nenhum dado de consumo encontrado para {email}")
            
    return total_daily_cost

def send_email_report(report_data):
    """Generates an HTML email report and sends it to the recipients"""
    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = ", ".join(RECEIVER_EMAILS)
    msg['Subject'] = f"Resumo diário Billing Incentivo - {yesterday_date}"
    
    html_content = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; color: #333; }}
            table {{ border-collapse: collapse; width: 100%; }}
            th, td {{ border: 1px solid #dddddd; text-align: left; padding: 10px; }}
            th {{ background-color: #0056b3; color: white; }}
            tr:nth-child(even) {{ background-color: #f9f9f9; }}
        </style>
    </head>
    <body>
        <h2>Resumo Billing Incentivo - {yesterday_obj.strftime("%d/%m/%Y")}</h2>
        <p>Aqui está o resumo do consumo referente ao dia anterior.</p>
        <table>
            <tr>
                <th>Email</th>
                <th>Consumo (R$)</th>
                <th>Variação (%)</th>
            </tr>
    """
    for row in report_data:
        html_content += f"""
            <tr>
                <td>{row['email']}</td>
                <td>R$ {row['consumption']:.4f}</td>
                <td>{row['variation']}</td>
            </tr>
        """
    html_content += """
        </table>
        <p style="margin-top: 20px; font-size: 12px; color: #777;">
            <i>Relatório gerado automaticamente via Python.</i>
        </p>
    </body>
    </html>
    """
        
    msg.attach(MIMEText(html_content, 'html'))
    
    try:
        print("\nConectando ao Servidor SMTP...")
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)
        server.quit()
        print("✅ Email enviado com sucesso!")
    except Exception as e:
        print(f"❌ Falha ao enviar email: {e}")

def process_daily_billing():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM daily_billing WHERE date = %s", (yesterday_date,))
    conn.commit()
    
    # 1. Fetch current clients from the API
    api_accounts = get_accounts()
    
    api_uids = {acc['uid'] for acc in api_accounts}
    accounts_dict = {acc['uid']: acc['email'] for acc in api_accounts}
    
    # 2. Fetch clients that were active yesterday from the DB
    cursor.execute('''
        SELECT DISTINCT uid, email FROM daily_billing 
        WHERE date = %s
    ''', (day_before_yesterday_date,))
    db_accounts = cursor.fetchall()
    
    # 3. Merge lists
    for uid, email in db_accounts:
        if uid not in accounts_dict:
            accounts_dict[uid] = email
            
    accounts = [{'uid': uid, 'email': email} for uid, email in accounts_dict.items()]
    
    print(f"Encontradas {len(accounts)} contas (API + DB). Processando custos para {yesterday_date}...")
    
    report = []

    for account in accounts:
        uid = account['uid']
        email = account['email']
        
        if email in EXCLUDED_EMAILS:
            continue
            
        is_in_api = uid in api_uids
        
        if not is_in_api:
            # O cliente sumiu da API (saiu do billing_incentivo). Vamos ver se ele pagou!
            exact_leave_time = get_conversion_time(uid)
            
            if exact_leave_time:
                # Registra o cliente na tabela de estatísticas como CONVERTIDO!
                # O "ON CONFLICT" impede que ele seja duplicado
                cursor.execute('''
                    INSERT INTO client_conversions (uid, email, conversion_date)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (uid) DO NOTHING
                ''', (uid, email, exact_leave_time))
                conn.commit()
                
                yesterday_consumption = get_billing_for_account(uid, email, custom_endtime=exact_leave_time)
            else:
                yesterday_consumption = get_billing_for_account(uid, email)
                
            if yesterday_consumption == 0.0:
                continue
        else:
            yesterday_consumption = get_billing_for_account(uid, email)
            
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
            
        # O insert na daily_billing continua puro
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
    
    print("\n--- Relatório Preliminar ---")
    for r in report:
        print(f"{r['email']} | R$ {r['consumption']:.4f} | {r['variation']}")

    if report:
        send_email_report(report)

if __name__ == '__main__':
    process_daily_billing()