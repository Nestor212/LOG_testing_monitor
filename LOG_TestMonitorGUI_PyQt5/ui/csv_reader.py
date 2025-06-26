import os
import csv
import datetime


class CsvReader:
    def __init__(self, data_dir):
        self.data_dir = data_dir

    def get_averaged_data(self, start_dt, end_dt, avg_n=25):
        """
        Returns list of (datetime, [LC1, LC2, ..., LC6]) averaged over avg_n samples
        """
        date = start_dt.strftime("%Y-%m-%d")
        filename = f"load_cell_log_{date}.csv"
        path = os.path.join(self.data_dir, filename)
        if not os.path.exists(path):
            print(f"[CsvReader] File not found: {path}")
            return []

        results = []
        buffer = []

        with open(path, "r") as f:
            reader = csv.reader(f)
            next(reader)  # skip header

            for row in reader:
                if len(row) != 7:
                    continue
                try:
                    dt = datetime.datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S.%f")
                    if not (start_dt <= dt <= end_dt):
                        continue
                    values = list(map(float, row[1:]))
                    buffer.append((dt, values))

                    if len(buffer) >= avg_n:
                        avg_ts = sum(dt.timestamp() for dt, _ in buffer) / avg_n
                        avg_dt = datetime.datetime.fromtimestamp(avg_ts)
                        avg_vals = [sum(sample[i] for _, sample in buffer) / avg_n for i in range(6)]
                        results.append((avg_dt, avg_vals))
                        buffer.clear()

                except Exception as e:
                    print(f"[CsvReader] Parse error: {e}")
                    continue

        return results
