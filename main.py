import requests
import sqlite3
import datetime
from datetime import timedelta
import smtplib
from email.mime.multipar import MIMEMultipart
from email.mime.text import MIMEText

# Email Configuration (Ideally, place these in environment variables later)
SMTP_SERVER = "mail.saveincloud.com" # Change to the actual SMTP server of the sender email provider
SMTP_PORT = 587 # Use 465 for SSL, 587 for TLS
SENDER_MAIL = "pedro.carriel@saveincloud.com" # Change to the actual sender email
SENDER_PASSWORD = "PC15042025" # Change to the actual sender email password or use an app-specific password for better security
RECEIVER_EMAILS = ["pedro.carriel@saveincloud.com",
                   "michelle.ferreira@saveincloud.com"
                   ] # Change to the actual recipient email


# Global Configurations (Ideally, place the session_token in environment variables later)
SESSION_TOKEN = "6d405345eedb48a1b72546e4f4ba583a1e61f08a"
APPID = "cluster"
URL_ACCOUNTS = "https://jca.jelastic.saveincloud.net/JBilling/billing/account/rest/getaccounts"
URL_BILLING = "https://jca.jelastic.saveincloud.net/JBilling/billing/account/rest/getaccountbillinghistorybyperiodinner"

# Defining dates (Calculating "Yesterday's" consumption)
yesterday_obj = datetime.date.today() - timedelta(days=1)
yesterday_date = yesterday_obj.strftime("%Y-%m-%d")
yesterday_date_jelastic = yesterday_obj.strftime("%Y-%m-%d 00:00:00") # Adjust format if API requires time
today_date_jelastic = datetime.date.today().strftime("%Y-%m-%d 00:00:00")

def get_db_connection():
    return sqlite3.connect('billing_history.db')

def get_accounts():
    """Fetches accounts from the billing_incentivo_v2 group"""
    params = {
        'appid': APPID,
        'session': SESSION_TOKEN,
        'startRow': 0,
        'resultCount': 100,
        'orderField': 'email',
        'orderDirection': 'ASC',
        'filterField': 'group',
        'filterValue': 'billing_incentivo_v2',
        'charset': 'UTF-8'
    }
    response = requests.get(URL_ACCOUNTS, params=params)
    data = response.json()
    
    if data.get('result') == 0:
        return data.get('array', [])
    else:
        print("Error fetching accounts:", data)
        return []

def get_billing_for_account(uid, email):
    """Fetches the consumption of a specific account for yesterday's period"""
    params = {
        'appid': APPID,
        'session': SESSION_TOKEN,
        'period': 'day',
        'groupNodes': 'false',
        'uid': uid,
        'node': 'root',
        'charset': 'UTF-8',
        'starttime': yesterday_date_jelastic,
        'endtime': today_date_jelastic,
        'email': email
    }
    
    response = requests.get(URL_BILLING, params=params)
    history_data = response.json()
    
    total_daily_cost = 0.0
    
    # Checks if the API returned a success result (0) and contains the 'array' key
    if history_data.get('result') == 0 and 'array' in history_data:
        items = history_data['array']
        for item in items:
            # Gets the total cost. If 'cost' is 0 or missing, it tries to sum resourceCost + bonusCost
            generic_cost = item.get('cost', 0.0)
            real_cost = item.get('resourceCost', 0.0)
            bonus_cost = item.get('bonusCost', 0.0)
            
            # Use 'cost' if available, otherwise fallback to the sum of real + bonus
            item_total = generic_cost if generic_cost > 0 else (real_cost + bonus_cost)
            
            total_daily_cost += item_total
    else:
        print(f"Warning: No billing data found or error for {email}")
            
    return total_daily_cost

def send_email_report(report_data):
    """Generates an HTML email report and sends it to the recipient"""
    msg = MIMEMultipart()
    msg['From'] = SENDER_MAIL
    msg['To'] = ", ".join(RECEIVER_EMAILS)
    msg['Subject'] = f"Resumo diário Billing Incentivo - {yesterday_date}"
    
    # Constructing the HTML body of the email
    html_content = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; color #333;}}
            table {{ border-collapse: collapse; width: 100%; }}
            th, td {{border: 1px solid #dddddd; text-align: left; padding: 10px;}}
            th {{ background-color: #0056b3; color: white; }}
            tr:nth-cild(even) {{ background-color: #f9f9f9; }}
        </style>
    </head>
    <body>
        <h2>Resumo Billing Incentivo - {yesterday_date}</h2>
        <p> Aqui está o resumo do consumo referente a <b>{yesterday_date}</b> comparado ao dia anterior. </p>
        <table>
            <tr>
                <th>Email</th>
                <th>Consumo (R$)</th>
                <th>Variação (%)</th>
            </tr>
    """
    # Injetando os dados do relatório na tabela HTML
    for row in report_data:
        html_content += f"""
            <tr>
                <td>{row['email']}</td>
                <td>R$ {row['consumption']}</td>
                <td>{row['variation']}</td>
            </tr>
        """
    html_content += """
            </table>
            <p style="margin-top: 20px; font-size: 12px; color: #777;">
                <i>Automated report generated by Python.</i>
            </p>
        </body>
        </html>
        """
        
    msg.attach(MIMEText(html_content, 'html'))
    
    # Enviando Email
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
    
    accounts = get_accounts()
    print(f"Found {len(accounts)} accounts. Processing costs for {yesterday_date}...")
    
    report = []

    for account in accounts:
        uid = account['uid']
        email = account['email']
        
        # 1. Fetch consumption from API
        yesterday_consumption = get_billing_for_account(uid, email)
        
        # 2. Fetch the day before yesterday's consumption from the SQLite DB to compare
        cursor.execute('''
            SELECT consumption FROM daily_billing 
            WHERE uid = ? AND date = date(?, '-1 day')
        ''', (uid, yesterday_date))
        day_before_yesterday_result = cursor.fetchone()
        
        day_before_yesterday_consumption = day_before_yesterday_result[0] if day_before_yesterday_result else 0.0
        
        # 3. Calculate the Variation (Delta %)
        if day_before_yesterday_consumption > 0:
            variation_pct = ((yesterday_consumption - day_before_yesterday_consumption) / day_before_yesterday_consumption) * 100
        else:
            variation_pct = 0.0 # Prevents division by zero if it's the client's first day
            
        # 4. Save yesterday's consumption to the DB to serve as a baseline for tomorrow
        cursor.execute('''
            INSERT INTO daily_billing (date, uid, email, consumption)
            VALUES (?, ?, ?, ?)
        ''', (yesterday_date, uid, email, yesterday_consumption))
        
        # 5. Add to the report list in memory
        trend = "⬆️" if variation_pct > 0 else "⬇️" if variation_pct < 0 else "➖"
        report.append({
            'email': email,
            'consumption': round(yesterday_consumption, 2),
            'variation': f"{trend} {round(variation_pct, 2)}%"
        })

    conn.commit()
    conn.close()
    
    # Display a preview in the console
    print("\n--- Preliminary Report ---")
    for r in report:
        print(f"{r['email']} | R$ {r['consumption']} | {r['variation']}")

if __name__ == '__main__':
    process_daily_billing()