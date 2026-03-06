import schedule
import time
import datetime
from main import process_daily_billing

def job():
    print("Iniciando a rotina de faturamento diário...")
    process_daily_billing(datetime.date.today())
    print("Rotina concluída! Aguardando o próximo ciclo...")

# Schedules the job to run every day at 07:00 AM
schedule.every().day.at("07:00").do(job)

print("Agendador (Worker) iniciado com sucesso. Aguardando as 07:00...")

# Infinite loop to keep the container running and checking the time
while True:
    schedule.run_pending()
    time.sleep(60)