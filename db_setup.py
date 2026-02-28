import sqlite3

# Creates the SQLite file locally
conn = sqlite3.connect('billing_history.db')
cursor = conn.cursor()

# Creates the consumption table
cursor.execute('''
    CREATE TABLE IF NOT EXISTS daily_billing (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        uid INTEGER,
        email TEXT,
        consumption REAL
    )
''')

conn.commit()
conn.close()
print("Database 'billing_history.db' created/verified successfully!")
