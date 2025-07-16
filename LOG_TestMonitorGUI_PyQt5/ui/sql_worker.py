from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot
import datetime
from Database.db import get_connection


class SqlWorker(QObject):
    data_ready = pyqtSignal(list)
    single_point_ready = pyqtSignal(datetime.datetime, list)
    error = pyqtSignal(str)

    @pyqtSlot(datetime.datetime, datetime.datetime, int)
    def query_range(self, start_dt, end_dt, avg_n):
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT timestamp, lc1, lc2, lc3, lc4, lc5, lc6
                FROM load_cells
                WHERE timestamp >= ? AND timestamp < ?
                ORDER BY timestamp
            """, (start_dt, end_dt))
            rows = cursor.fetchall()
            conn.close()

            buffer = []
            result = []

            for row in rows:
                ts = row[0]
                if isinstance(ts, str):
                    try:
                        ts = datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S.%f")
                    except ValueError:
                        try:
                            ts = datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            print(f"⚠️ Skipping unparseable timestamp: {ts}")
                            continue

                values = row[1:]
                buffer.append((ts, values))
                if len(buffer) >= avg_n:
                    avg_ts = sum(t.timestamp() for t, _ in buffer) / avg_n
                    avg_dt = datetime.datetime.fromtimestamp(avg_ts)
                    avg_vals = [sum(v[i] for _, v in buffer) / avg_n for i in range(6)]
                    result.append((avg_dt, avg_vals))
                    buffer.clear()

            self.data_ready.emit(result)

        except Exception as e:
            self.error.emit(str(e))

    @pyqtSlot(int)
    def query_last_n_samples(self, n):
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT timestamp, lc1, lc2, lc3, lc4, lc5, lc6
                FROM load_cells
                ORDER BY timestamp DESC
                LIMIT ?
            """, (n,))
            rows = cursor.fetchall()
            conn.close()

            if not rows or len(rows) < n:
                return  # Not enough data

            # Reverse to chronological order
            rows.reverse()

            # Convert timestamps to epoch seconds with fallback
            times = []
            for r in rows:
                ts_str = r[0]
                try:
                    ts = datetime.datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S.%f")
                except ValueError:
                    ts = datetime.datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                times.append(ts.timestamp())

            avg_time = datetime.datetime.fromtimestamp(sum(times) / n)

            # Average loads
            transposed = list(zip(*[r[1:] for r in rows]))  # Skip timestamp
            avg_loads = [sum(col) / n for col in transposed]

            self.single_point_ready.emit(avg_time, avg_loads)

        except Exception as e:
            self.error.emit(f"[query_last_n_samples] {e}")
