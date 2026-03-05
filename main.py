import requests
import mysql.connector
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
URL_FUNDING = "https://jca.jelastic.saveincloud.net/JBilling/billing/account/rest/getfundaccounthistory"

# Emails that should NEVER appear in the metrics
EXCLUDED_EMAILS = ["apresentacao@saveincloud.com"]

# ==========================================
# 🛑 BLOCO DE DATAS PARA TESTE DEV LOCAL (MySQL Dev DB) 🛑
yesterday_date = "2026-03-02 00:00:00" 
day_before_yesterday_date = "2026-03-01 00:00:00"
yesterday_start_jelastic = "2026-03-02 00:00:00"
yesterday_end_jelastic = "2026-03-02 23:59:59" 
yesterday_display = "02/03/2026"

# 🟢 BLOCO DE DATAS PARA PRODUÇÃO 🟢
# (Descomente estas linhas e apague as de cima quando for para produção)
# yesterday_obj = datetime.date.today() - timedelta(days=1)
# yesterday_date = yesterday_obj.strftime("%Y-%m-%d 00:00:00") 
# day_before_yesterday_obj = yesterday_obj - timedelta(days=1)
# day_before_yesterday_date = day_before_yesterday_obj.strftime("%Y-%m-%d 00:00:00")
# yesterday_start_jelastic = yesterday_obj.strftime("%Y-%m-%d 00:00:00")
# yesterday_end_jelastic = yesterday_obj.strftime("%Y-%m-%d 23:59:59") 
# yesterday_display = yesterday_obj.strftime("%d/%m/%Y")
# ==========================================

def get_db_connection():
    """Connects to MySQL Central and ensures auxiliary tables creation"""
    conn = mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT", 3306)),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )
    
    cursor = conn.cursor()
    
    # Table 1: Conversions Vault (MySQL Syntax)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS client_conversions (
            uid INT PRIMARY KEY,
            email VARCHAR(255),
            conversion_date DATETIME
        )
    ''')

    # Table 2: Active clients tracking (Resolves the JCA Amnesia problem)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tracked_clients (
            uid INT PRIMARY KEY,
            email VARCHAR(255)
        )
    ''')
    
    conn.commit()
    cursor.close()
    
    return conn

def get_accounts():
    """Fetches ONLY active accounts from the billing_incentivo group today"""
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

def get_conversion_time(uid):
    """Fetches the exact time a user made their first funding payment"""
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

def get_cost_from_db(cursor, uid, date_str):
    """Fetches the daily consumption directly from Central MySQL DB"""
    cursor.execute('''
        SELECT cost FROM billing_history 
        WHERE user_id = %s AND date = %s
    ''', (uid, date_str))
    result = cursor.fetchone()
    # Converte o retorno decimal do MySQL para float
    return float(result[0]) if result else 0.0

def send_email_report(report_data):
    """Generates an HTML email report and sends it to the recipients"""
    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = ", ".join(RECEIVER_EMAILS)
    msg['Subject'] = f"Resumo diário Billing Incentivo - {yesterday_display}"
    
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
        <h2>Resumo Billing Incentivo - {yesterday_display}</h2>
        <p>Resumo do consumo diário (Extraído do Banco Central MySQL).</p>
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
        print("\nConnecting to SMTP Server...")
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)
        server.quit()
        print("✅ Email sent successfully!")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")

def process_daily_billing():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Fetch current clients from the API (WHO IS ACTIVE TODAY)
    api_accounts = get_accounts()
    api_dict = {acc['uid']: acc['email'] for acc in api_accounts}
    
    # 2. Fetch clients that were active yesterday from the Tracking Table
    cursor.execute('SELECT uid, email FROM tracked_clients')
    db_accounts = cursor.fetchall()
    db_dict = {row[0]: row[1] for row in db_accounts}
    
    report_accounts = []

    # 3. Crossing Logic: Who was here yesterday but left today? (Conversions)
    for uid, email in db_dict.items():
        if uid not in api_dict:
            exact_leave_time = get_conversion_time(uid)
            if exact_leave_time:
                # MySQL uses INSERT IGNORE to prevent duplicates
                cursor.execute('''
                    INSERT IGNORE INTO client_conversions (uid, email, conversion_date)
                    VALUES (%s, %s, %s)
                ''', (uid, email, exact_leave_time))
            
            # Remove from active tracking
            cursor.execute('DELETE FROM tracked_clients WHERE uid = %s', (uid,))
            # Adds to report calculation (because they still consumed yesterday)
            report_accounts.append({'uid': uid, 'email': email})

    # 4. Crossing Logic: Who is new today? (New Entries)
    for uid, email in api_dict.items():
        if uid not in db_dict:
            # MySQL uses INSERT IGNORE
            cursor.execute('''
                INSERT IGNORE INTO tracked_clients (uid, email)
                VALUES (%s, %s)
            ''', (uid, email))
        
        # Adds to report calculation
        report_accounts.append({'uid': uid, 'email': email})

    conn.commit()
    print(f"Processando os custos de {len(report_accounts)} clientes direto do banco...")
    
    report = []

    # 5. Fast Cost Calculation via MySQL Central DB
    for acc in report_accounts:
        uid = acc['uid']
        email = acc['email']
        
        if email in EXCLUDED_EMAILS:
            continue
            
        yesterday_cost = get_cost_from_db(cursor, uid, yesterday_date)
        day_before_cost = get_cost_from_db(cursor, uid, day_before_yesterday_date)
        
        if yesterday_cost == 0.0:
            continue
            
        if day_before_cost > 0:
            variation_pct = ((yesterday_cost - day_before_cost) / day_before_cost) * 100
        else:
            variation_pct = 0.0 
            
        trend = "⬆️" if variation_pct > 0 else "⬇️" if variation_pct < 0 else "➖"
        report.append({
            'email': email,
            'consumption': yesterday_cost,
            'variation': f"{trend} {round(variation_pct, 2)}%"
        })

    cursor.close()
    conn.close()
    
    print("\n--- Preliminary Report ---")
    for r in report:
        print(f"{r['email']} | R$ {r['consumption']:.4f} | {r['variation']}")

    if report:
        send_email_report(report)

if __name__ == '__main__':
    process_daily_billing()