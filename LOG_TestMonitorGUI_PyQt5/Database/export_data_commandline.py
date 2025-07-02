"""
extract_data.py

This script extracts logged sensor data from the SQLite database (data_log.db)
into CSV files. It supports exporting from four tables:
  - load_cells
  - accelerometer
  - load_cell_zero_offsets
  - accelerometer_zero_offsets

Each table is exported to a separate CSV file, including timestamped entries within
a specified time window.

USAGE:
  # Export all data from a single date (00:00:00 to 23:59:59 on 2025-06-26)
  python3 export_data.py 2025-06-26

  # Export data from a custom date/time range
  python3 export_data.py "2025-06-30 16:31:30" "2025-06-30 16:31:31"

Output CSV files will be saved in the current directory with filenames indicating
the selected date/time range.
"""


import sqlite3
import csv
import datetime
import os
import sys

output_folder = os.path.join(os.path.dirname(__file__), "ExportedData")

def get_connection():
    db_path = os.path.join(os.path.dirname(__file__), "Data", "data_log.db")
    return sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)

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

    full_path = os.path.join(output_folder, output_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        for row in rows:
            ts = parse_timestamp(row[0])
            if ts:
                writer.writerow([ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]] + list(row[1:]))
    print(f"✅ Exported {len(rows)} rows from {table} to {full_path}")

if __name__ == "__main__":
    if len(sys.argv) == 2:
        try:
            date = datetime.datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
            start = datetime.datetime.combine(date, datetime.time.min)
            end = datetime.datetime.combine(date, datetime.time.max)
        except ValueError:
            print("Usage: python extract_data.py YYYY-MM-DD")
            sys.exit(1)
    elif len(sys.argv) == 3:
        try:
            start = datetime.datetime.strptime(sys.argv[1], "%Y-%m-%d %H:%M:%S")
            end = datetime.datetime.strptime(sys.argv[2], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            print("Usage: python extract_data.py \"YYYY-MM-DD HH:MM:SS\" \"YYYY-MM-DD HH:MM:SS\"")
            sys.exit(1)
    else:
        print("Usage:\n  python extract_data.py YYYY-MM-DD\n  python extract_data.py \"YYYY-MM-DD HH:MM:SS\" \"YYYY-MM-DD HH:MM:SS\"")
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
