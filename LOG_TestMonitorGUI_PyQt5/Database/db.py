import sqlite3
import os

import sqlite3
import os
import sys

def get_db_path():
    if getattr(sys, 'frozen', False):
        # PyInstaller executable
        base_dir = os.path.expanduser("~/.LOG_testing_monitor")
    else:
        # Running from source
        base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Data")

    os.makedirs(base_dir, exist_ok=True)
    return os.path.join(base_dir, "data_log.db")

def get_connection():
    db_path = get_db_path()
    print(f"Connecting to database at: {db_path}")  # Debugging lin
    conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def initialize_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS load_cells (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME,
            lc1 REAL, lc2 REAL, lc3 REAL,
            lc4 REAL, lc5 REAL, lc6 REAL
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS accelerometer (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME,
            ax REAL, ay REAL, az REAL
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS load_cell_zero_offsets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME,
            lc1_offset REAL, lc2_offset REAL, lc3_offset REAL,
            lc4_offset REAL, lc5_offset REAL, lc6_offset REAL
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS accelerometer_zero_offsets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME,
            ax_offset REAL, ay_offset REAL, az_offset REAL
        );
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON load_cells(timestamp);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_accel_timestamp ON accelerometer(timestamp);")

    conn.commit()
    conn.close()
