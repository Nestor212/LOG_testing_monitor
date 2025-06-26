from PyQt5.QtCore import pyqtSignal, pyqtSlot, QObject
import os
import csv
import datetime
from collections import deque

class CsvWorker(QObject):
    data_ready = pyqtSignal(list)
    single_point_ready = pyqtSignal(datetime.datetime, list)
    error = pyqtSignal(str)

    def __init__(self, data_dir):
        super().__init__()
        self.data_dir = data_dir

    @pyqtSlot(int)
    def read_last_n_samples(self, n):
        try:
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            path = os.path.join(self.data_dir, f"load_cell_log_{today}.csv")
            if not os.path.exists(path):
                self.error.emit(f"File not found: {path}")
                return

            recent = deque(maxlen=n)
            with open(path, "r") as f:
                reader = csv.reader(f)
                next(reader)  # skip header
                for row in reader:
                    if len(row) != 7:
                        continue
                    try:
                        dt = datetime.datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S.%f")
                        values = list(map(float, row[1:]))
                        recent.append((dt, values))
                    except Exception:
                        continue

            if len(recent) < n:
                return

            avg_ts = sum(t.timestamp() for t, _ in recent) / n
            avg_dt = datetime.datetime.fromtimestamp(avg_ts)
            avg_vals = [sum(v[i] for _, v in recent) / n for i in range(6)]

            self.single_point_ready.emit(avg_dt, avg_vals)

        except Exception as e:
            self.error.emit(str(e))
