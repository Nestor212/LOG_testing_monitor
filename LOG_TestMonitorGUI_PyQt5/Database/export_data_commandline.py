import sqlite3
import csv
import datetime
import os
import sys
import pandas as pd
import numpy as np

def get_db_path():
    base_dir = os.path.expanduser("~/Documents/LOG_testing_monitor/LOG_TestMonitorGUI_PyQt5/Database/Data")
    return os.path.join(base_dir, "data_log.db")

def get_connection():
    db_path = get_db_path()
    print(f"🔍 Using DB at: {db_path}")
    conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def print_usage():
    print("""
extract_data_commandline.py

Extract logged sensor data into CSV files.

USAGE:
  python3 extract_data_commandline.py YYYY-MM-DD [options]
      Export all data from that date (00:00:00 to 23:59:59)

  python3 extract_data_commandline.py "YYYY-MM-DD HH:MM:SS" "YYYY-MM-DD HH:MM:SS" [options]
      Export data from custom start and end time

OPTIONS:
  --outdir DIR    Output directory (default: ~/Desktop/exportedData)
  --load_cells    Export Load Cells
  --accelerometer Export Accelerometer
  --lc_offsets    Export Load Cell Zero Offsets
  --accel_offsets Export Accelerometer Zero Offsets
  --all           Export all data (default)
  -h, --help      Show this help message
""")

def export_table(table, columns, start_time, end_time, output_folder, filename, smoothing_factor=1):
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

    df = pd.DataFrame(rows, columns=columns)
    df['timestamp'] = pd.to_datetime(df['timestamp'], format='mixed')

    if smoothing_factor > 1:
        group_labels = np.arange(len(df)) // smoothing_factor
        df = df.groupby(group_labels).agg({
            'timestamp': 'mean',
            **{col: 'mean' for col in columns if col != 'timestamp'}
        }).reset_index(drop=True)

    os.makedirs(output_folder, exist_ok=True)
    full_path = os.path.join(output_folder, filename)
    df['timestamp'] = df['timestamp'].dt.strftime("%Y-%m-%d %H:%M:%S.%f").str[:-3]
    df.to_csv(full_path, index=False)

    print(f"✅ Exported {len(df)} rows from {table} to {full_path}")
    return len(df)

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or "-h" in args or "--help" in args:
        print_usage()
        sys.exit(0)

    output_folder = os.path.expanduser("~/Desktop/exportedData")
    export_load = export_accel = export_lc_offsets = export_accel_offsets = False
    smoothing_factor = 1

    date_args = []
    i = 0
    while i < len(args):
        if args[i].startswith("--"):
            break
        date_args.append(args[i])
        i += 1

    options = args[i:]
    while options:
        opt = options.pop(0)
        if opt == "--outdir":
            output_folder = os.path.expanduser(options.pop(0))
        elif opt == "--load_cells":
            export_load = True
        elif opt == "--accelerometer":
            export_accel = True
        elif opt == "--lc_offsets":
            export_lc_offsets = True
        elif opt == "--accel_offsets":
            export_accel_offsets = True
        elif opt == "--all":
            export_load = export_accel = export_lc_offsets = export_accel_offsets = True
        elif opt == "--smooth":
            smoothing_factor = int(options.pop(0))        
        else:
            print(f"❌ Unknown option: {opt}")
            print_usage()
            sys.exit(1)

    if not any([export_load, export_accel, export_lc_offsets, export_accel_offsets]):
        export_load = export_accel = export_lc_offsets = export_accel_offsets = True

    try:
        if len(date_args) == 1:
            date = datetime.datetime.strptime(date_args[0], "%Y-%m-%d").date()
            start = datetime.datetime.combine(date, datetime.time.min)
            end = datetime.datetime.combine(date, datetime.time.max)
        elif len(date_args) == 2:
            start = datetime.datetime.strptime(date_args[0], "%Y-%m-%d %H:%M:%S")
            end = datetime.datetime.strptime(date_args[1], "%Y-%m-%d %H:%M:%S")
        else:
            raise ValueError("Invalid date/time arguments")
    except Exception as e:
        print(f"❌ {e}")
        print_usage()
        sys.exit(1)

    base = f"{start.strftime('%Y-%m-%d_%H-%M-%S')}_to_{end.strftime('%Y-%m-%d_%H-%M-%S')}"

    try: 
        if export_load:
            export_table("load_cells",
                        ["timestamp", "lc1", "lc2", "lc3", "lc4", "lc5", "lc6"],
                        start, end, output_folder, f"load_cells_{base}.csv")

        if export_accel:
            export_table("accelerometer",
                        ["timestamp", "ax", "ay", "az"],
                        start, end, output_folder, f"accelerometer_{base}.csv")

        if export_lc_offsets:
            export_table("load_cell_zero_offsets",
                        ["timestamp", "lc1_offset", "lc2_offset", "lc3_offset", "lc4_offset", "lc5_offset", "lc6_offset"],
                        start, end, output_folder, f"load_cell_zero_offsets_{base}.csv")

        if export_accel_offsets:
            export_table("accelerometer_zero_offsets",
                        ["timestamp", "ax_offset", "ay_offset", "az_offset"],
                        start, end, output_folder, f"accelerometer_zero_offsets_{base}.csv")
    except Exception as e:
        print(f"❌ Error during export: {e}")
        sys.exit(1)