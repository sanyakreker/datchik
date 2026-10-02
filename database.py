import sqlite3
import datetime


DB_NAME = "monitor.db"


def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS temperature (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            temperature REAL NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def log_temperature(temp):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "INSERT INTO temperature (timestamp, temperature) VALUES (?, ?)",
        (timestamp, temp)
    )
    conn.commit()
    conn.close()