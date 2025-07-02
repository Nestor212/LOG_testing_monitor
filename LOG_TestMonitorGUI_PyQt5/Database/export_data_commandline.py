import sqlite3
import csv
import datetime
import os
import sys


def get_connection():
    # Locate the database relative to where this script lives
    base_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(base_dir, "Data", "data_log.db")

    # Or if your DB lives somewhere fixed (recommended if multiple scripts access it):
    # db_path = os.path.expanduser("~/Documents/LOG_testing_monitor/Database/Data/data_log.db")

    conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.execute("PRAGMA journal_mode=WAL;")  # Enable concurrent reads/writes
    return conn


def print_usage():
    print("""
extract_data.py

Extract logged sensor data into CSV files.

USAGE:
  python3 extract_data.py YYYY-MM-DD
      Export all data from that date (00:00:00 to 23:59:59)

  python3 extract_data.py "YYYY-MM-DD HH:MM:SS" "YYYY-MM-DD HH:MM:SS"
      Export data from custom start and end time

OPTIONS:
  -h, --help    Show this help message
""")

output_folder = os.path.join(os.path.expanduser("~"), "LOG_Exports")

def parse_timestamp(ts):
    if isinstance(ts, datetime.datetime):
        return ts
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.datetime.strptime(ts, fmt)
        except ValueError:
            continue
    print(f"⚠️ Skipping unparseable timestamp: {ts}")
    return None

def export_table(table, columns, start_time, end_time, output_path):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(f"""
        SELECT {', '.join(columns)}
        FROM {table}
        WHERE timestamp BETWEEN ? AND ?
        ORDER BY timestamp
    """, (start_time, end_time))
    rows = cursor.fetchall()
    conn.close()

    os.makedirs(output_folder, exist_ok=True)
    full_path = os.path.join(output_folder, output_path)

    with open(full_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        for row in rows:
            ts = parse_timestamp(row[0])
            if ts:
                writer.writerow([ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]] + list(row[1:]))
    print(f"✅ Exported {len(rows)} rows from {table} to {full_path}")

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print_usage()
        sys.exit(0)

    if len(args) == 1:
        try:
            date = datetime.datetime.strptime(args[0], "%Y-%m-%d").date()
            start = datetime.datetime.combine(date, datetime.time.min)
            end = datetime.datetime.combine(date, datetime.time.max)
        except ValueError:
            print("❌ Invalid date format. Use YYYY-MM-DD.")
            sys.exit(1)
    elif len(args) == 2:
        try:
            start = datetime.datetime.strptime(args[0], "%Y-%m-%d %H:%M:%S")
            end = datetime.datetime.strptime(args[1], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            print("❌ Invalid datetime format. Use \"YYYY-MM-DD HH:MM:SS\"")
            sys.exit(1)
    else:
        print_usage()
        sys.exit(1)

    base = f"{start.strftime('%Y-%m-%d_%H-%M-%S')}_to_{end.strftime('%Y-%m-%d_%H-%M-%S')}"

    export_table("load_cells",
                 ["timestamp", "lc1", "lc2", "lc3", "lc4", "lc5", "lc6"],
                 start, end, f"load_cells_{base}.csv")

    export_table("accelerometer",
                 ["timestamp", "ax", "ay", "az"],
                 start, end, f"accelerometer_{base}.csv")

    export_table("load_cell_zero_offsets",
                 ["timestamp", "lc1_offset", "lc2_offset", "lc3_offset", "lc4_offset", "lc5_offset", "lc6_offset"],
                 start, end, f"load_cell_zero_offsets_{base}.csv")

    export_table("accelerometer_zero_offsets",
                 ["timestamp", "ax_offset", "ay_offset", "az_offset"],
                 start, end, f"accelerometer_zero_offsets_{base}.csv")
