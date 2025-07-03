import socket
import time
import datetime
import threading
import os
import csv
import sys
from PyQt5.QtCore import QThread
from comms.parser_emitter import ParserEmitter
from Database.db import get_connection  # Ensure this is at the top of your file
from queue import Queue
import threading
import numpy as np

class TeensySocketThread(QThread):
    first_connection_done = False
    zeroed = False
    
    def __init__(self, host, port, emitter: ParserEmitter):
        super().__init__()
        self.host = host
        self.port = port
        self.s = None
        self.running = True
        self.emitter = emitter
        self.last_emit_time = time.time()
        self.latest_data = None
        self.emit_interval = 0.25  # 20 Hz
        self.avg_load_buffer = []
        self.avg_accel_buffer = []
        self.avg_accel_on = False
        self.avg_accel_stale = False
        self.last_read_time = time.time()

        if getattr(sys, 'frozen', False):
            # Running as PyInstaller bundle
            base_dir = os.path.dirname(sys.executable)
        else:
            # Running as script
            base_dir = os.path.dirname(os.path.abspath(__file__))

        self.data_dir = os.path.join(base_dir, "..", "Database", "Data")
        os.makedirs(self.data_dir, exist_ok=True)

        self.load_buffer = []
        self.accel_buffer = []
        self.last_valid_accels = [0.0, 0.0, 0.0]  # Default accelerometer values
        self.last_flush = time.time()

        # self.lc_zero_load_offset = [1.6378,	8.8097,	-6.3057, 1.1999, 1.2814, -0.0209] # PGA Bypassed
        self.lc_zero_load_offset = [0.2378,	7.4097,	-7.7057, -0.2001, -0.1186, -1.4209] # PGA Enabled G = 1, less noisy 


        if not TeensySocketThread.first_connection_done or not TeensySocketThread.zeroed:
            # print("🔌 First connection detected, initializing zero offsets.", flush=True)
            self.load_offsets = [0.0] * 6
            self.zero_pending = {"loads": False, "accels": False}
            TeensySocketThread.first_connection_done = True
        else:
            print("🔌 Subsequent connection detected, fetching latest zero offsets from DB.", flush=True)
            self.load_offsets = self.fetch_latest_load_offsets_from_db()
            print(f"🔌 Loaded offsets: {self.load_offsets}", flush=True)
            self.zero_pending = {"loads": False, "accels": False}

        self.accel_offset = [0.0, 0.0, 0.0]

        self.db_queue = Queue()
        self._db_writer_thread = threading.Thread(target=self._db_writer_loop, daemon=True)
        self._db_writer_thread.start()

    def load_last_offsets(self):
        """Load the last stored offsets from the database."""
        self.load_offsets = self.fetch_latest_load_offsets_from_db()
        print(f"🔌 Loaded offsets from DB: {self.load_offsets}", flush=True)
        self.zero_pending["loads"] = False
        TeensySocketThread.zeroed = True  # Mark as zeroed to avoid re-zeroing on next connection

    def fetch_latest_load_offsets_from_db(self):
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT lc1_offset, lc2_offset, lc3_offset, lc4_offset, lc5_offset, lc6_offset
                FROM load_cell_zero_offsets
                ORDER BY timestamp DESC
                LIMIT 1
            """)
            row = cursor.fetchone()
            conn.close()

            if row:
                return list(row)
            else:
                print("⚠ No load cell zero offsets found in DB, using zeros.")
                return [0.0] * 6
        except Exception as e:
            print(f"⚠ DB error fetching load offsets: {e}")
            return [0.0] * 6

    def zero_loads(self, zeroing=False):
        if zeroing:
            TeensySocketThread.zeroed = True
            if self.latest_data:
                _, loads, *_ = self.latest_data
                self.load_offsets = [
                    load + offset for load, offset in zip(loads, self.load_offsets)
                ]
                self.zero_pending["loads"] = True
                print(f"🔧 Zeroed load cells: {self.load_offsets}")
        else:
            # Clear load offsets without zeroing
            TeensySocketThread.zeroed = False
            self.load_offsets = [0.0] * 6
            self.zero_pending["loads"] = False
            print("🔧 Cleared load cell offsets.")

    def zero_accels(self, zeroing=False):
        if zeroing:
            if self.latest_data:
                _, _, accels, accel_on, accel_stale = self.latest_data
                if accel_on and not accel_stale:
                    self.accel_offset = accels[:]
                    self.zero_pending["accels"] = True
                    print(f"🔧 Zeroed accelerometer: {self.accel_offset}")
        else:
            # Clear accelerometer offsets without zeroing
            self.accel_offset = [0.0, 0.0, 0.0]
            self.zero_pending["accels"] = False
            print("🔧 Cleared accelerometer offsets.")

    def emit_loop(self):
        while self.running:
            time.sleep(self.emit_interval)
            timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

            if self.avg_load_buffer:
                avg_loads = np.mean(self.avg_load_buffer, axis=0).tolist()
            else:
                avg_loads = [0.0] * 6

            if self.avg_accel_buffer:
                avg_accels = np.mean(self.avg_accel_buffer, axis=0).tolist()
            else:
                avg_accels = [0.0, 0.0, 0.0]

            # Update latest_data for consistency
            self.latest_data = (
                timestamp_str,
                avg_loads,
                avg_accels,
                self.avg_accel_on,
                self.avg_accel_stale
            )

            self.emitter.new_data.emit(
                timestamp_str,
                avg_loads,
                avg_accels,
                self.avg_accel_on,
                self.avg_accel_stale
            )

            # Reset buffers for next interval
            self.avg_load_buffer.clear()
            self.avg_accel_buffer.clear()
            self.avg_accel_on = False
            self.avg_accel_stale = False

    def run(self):
        print("🔌 Starting socket thread.", flush=True)
        buffer = ""
        line_counter = 0
        #last_debug_time = time.time()
        if not hasattr(self, 'emit_thread_started'):
            threading.Thread(target=self.emit_loop, daemon=True).start()
            self.emit_thread_started = True

        while self.running:
            try:
                self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
                self.s.settimeout(5)
                self.s.connect((self.host, self.port))
                self.s.sendall(b"HELLO\n")
                time.sleep(0.1)
                self.sync_time()

                while self.running:
                    if time.time() - self.last_read_time > 0.1:
                        print(F"Elapsed time since last read: {time.time() - self.last_read_time:.2f} seconds", flush=True)
                    
                    self.last_read_time = time.time()
                    try:
                        chunk = self.s.recv(2048).decode(errors='ignore')
                        # print(f"chunk: {chunk}", flush=True)
                        if not chunk:
                            break

                        buffer += chunk
                        while '\n' in buffer:
                            line, buffer = buffer.split('\n', 1)
                            line = line.strip()

                            if line.startswith("TS ") and line.count(' ') >= 12:
                                t0 = time.time()
                                self.handle_line(line)
                                t1 = time.time()
                                dt = (t1 - t0) * 1000  # ms
                                if dt > 2:  # flag slow lines
                                    print(f"🐢 handle_line took {dt:.2f} ms", flush=True)
                                line_counter += 1
                            else:
                                print(f"⚠️ Malformed or partial line: {line}", flush=True)

                        # now = time.time()
                        # if now - last_debug_time >= 1.0:
                        #     print(f"📨 {line_counter} lines/sec", flush=True)
                        #     line_counter = 0
                        #     last_debug_time = now

                        self.flush_logs()

                    except socket.timeout:
                        continue

            except Exception as e:
                print(f"⚠️ Socket error: {e}", flush=True)
                time.sleep(2)

            finally:
                if self.s:
                    self.s.sendall(b"D\n")
                    time.sleep(0.1)
                    self.s.close()
                    self.s = None

    def handle_line(self, line):
        try:
            # print(f"📥 Received line: {line}", flush=True)
            fields = line[3:].strip().split()
            if len(fields) != 12:
                return

            raw_ts = float(fields[0])
            timestamp = datetime.datetime.fromtimestamp(raw_ts)
            # print(timestamp, flush=True)
            timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            loads = list(map(float, fields[1:7]))
            accel_on = int(fields[7])
            accel_stale = fields[11] == '1'
            accels = list(map(float, fields[8:11])) if accel_on and not accel_stale else []

            # Update buffer for logging data to db
            if accels:
                adjusted_accels = [a - offset for a, offset in zip(accels, self.accel_offset)]
                self.last_valid_accels = adjusted_accels
                rounded_accels = [round(l, 4) for l in adjusted_accels]
                self.accel_buffer.append([timestamp_str] + rounded_accels)

            adjusted_loads = [l - offset - zero_load for l, offset, zero_load in zip(loads, self.load_offsets, self.lc_zero_load_offset)]
            rounded_loads = [round(l, 4) for l in adjusted_loads]
            self.load_buffer.append((timestamp, *rounded_loads))

            # Update average buffers for UI displau
            self.avg_load_buffer.append(adjusted_loads)
            if accels:
                self.avg_accel_buffer.append(self.last_valid_accels)
                self.avg_accel_on = True
                self.avg_accel_stale = accel_stale

            # self.latest_data = (timestamp_str, adjusted_loads, self.last_valid_accels, accel_on, accel_stale)
            # --- SPS counter ---
            current_sec = int(raw_ts)
            if not hasattr(self, 'last_sps_sec'):
                self.last_sps_sec = current_sec
                self.lc_sps_counter = 0
                self.accel_sps_counter = 0

            if current_sec == self.last_sps_sec:
                self.lc_sps_counter += 1
                if accels:
                    self.accel_sps_counter += 1
            else:
                self.emitter.update_sps.emit(self.lc_sps_counter, self.accel_sps_counter)
                self.last_sps_sec = current_sec
                self.lc_sps_counter = 1
                self.accel_sps_counter = 1 if accels else 0

        except Exception as e:
            print(f"⚠️ Parse error: {e} — line: {line}", flush=True)
    
    def _db_writer_loop(self):
        # Open CSV files once for appending
        lc_log_path = os.path.join(self.data_dir, "load_buffer_log.csv.csv")
        accel_log_path = os.path.join(self.data_dir, "accel_buffer_log.csv")

        with open(lc_log_path, "a", newline="") as load_csv_file, \
            open(accel_log_path, "a", newline="") as accel_csv_file:
            load_writer = csv.writer(load_csv_file)
            accel_writer = csv.writer(accel_csv_file)

            while True:
                payload = self.db_queue.get()
                if payload is None:
                    break  # For clean shutdown

                try:
                    conn = get_connection()
                    cursor = conn.cursor()

                    now_str = payload["timestamp"]

                    if payload["zero_pending"]["loads"]:
                        cursor.execute("""
                            INSERT INTO load_cell_zero_offsets (
                                timestamp, lc1_offset, lc2_offset, lc3_offset, lc4_offset, lc5_offset, lc6_offset
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, [now_str] + payload["load_offsets"])

                    if payload["zero_pending"]["accels"]:
                        cursor.execute("""
                            INSERT INTO accelerometer_zero_offsets (
                                timestamp, ax_offset, ay_offset, az_offset
                            ) VALUES (?, ?, ?, ?)
                        """, [now_str] + payload["accel_offset"])

                    if payload["load_buffer"]:
                        cursor.executemany("""
                            INSERT INTO load_cells (timestamp, lc1, lc2, lc3, lc4, lc5, lc6)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, payload["load_buffer"])

                        # Write to CSV
                        for row in payload["load_buffer"]:
                            load_writer.writerow(row)

                    if payload["accel_buffer"]:
                        cursor.executemany("""
                            INSERT INTO accelerometer (timestamp, ax, ay, az)
                            VALUES (?, ?, ?, ?)
                        """, payload["accel_buffer"])

                        # Write to CSV
                        for row in payload["accel_buffer"]:
                            accel_writer.writerow(row)

                    conn.commit()
                    conn.close()
                except Exception as e:
                    print(f"⚠️ DB writer error: {e}")
                finally:
                    self.db_queue.task_done()


    def flush_logs(self):
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        payload = {
            "zero_pending": self.zero_pending.copy(),
            "load_offsets": self.load_offsets.copy(),
            "accel_offset": self.accel_offset.copy(),
            "load_buffer": self.load_buffer.copy(),
            "accel_buffer": self.accel_buffer.copy(),
            "timestamp": now_str
        }

        self.zero_pending = {"loads": False, "accels": False}
        self.load_buffer.clear()
        self.accel_buffer.clear()

        self.db_queue.put(payload)

    # def flush_csv_logs(self):
    #     now = time.time()

    #     if self.zero_pending["loads"]:
    #         log_path = os.path.join(self.data_dir, "load_cell_zero_offsets.csv")
    #         with open(log_path, 'a', newline='') as f:
    #             writer = csv.writer(f)
    #             writer.writerow(["Timestamp"] + [f"LC{i+1} Offset" for i in range(6)])
    #             writer.writerow([datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]] + self.load_offsets)
    #         self.zero_pending["loads"] = False

    #     if self.zero_pending["accels"]:
    #         log_path = os.path.join(self.data_dir, "accelerometer_zero_offsets.csv")
    #         with open(log_path, 'a', newline='') as f:
    #             writer = csv.writer(f)
    #             writer.writerow(["Timestamp", "AX Offset", "AY Offset", "AZ Offset"])
    #             writer.writerow([datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]] + self.accel_offset)
    #         self.zero_pending["accels"] = False

    #     if now - self.last_flush < 2.0:
    #         return
    #     self.last_flush = now

    #     if self.load_buffer:
    #         log_date = datetime.datetime.now().strftime("%Y-%m-%d")
    #         log_path = os.path.join(self.data_dir, f"load_cell_log_{log_date}.csv")
    #         file_exists = os.path.isfile(log_path)

    #         with open(log_path, 'a', newline='') as f:
    #             writer = csv.writer(f)
    #             if not file_exists:
    #                 writer.writerow(["Timestamp"] + [f"LC{i+1}" for i in range(6)])
    #             writer.writerows(self.load_buffer)
    #         self.load_buffer.clear()

    #     if self.accel_buffer:
    #         log_date = datetime.datetime.now().strftime("%Y-%m-%d")
    #         log_path = os.path.join(self.data_dir, f"accelerometer_log_{log_date}.csv")
    #         file_exists = os.path.isfile(log_path)

    #         with open(log_path, 'a', newline='') as f:
    #             writer = csv.writer(f)
    #             if not file_exists:
    #                 writer.writerow(["Timestamp", "AX", "AY", "AZ"])
    #             writer.writerows(self.accel_buffer)
    #         self.accel_buffer.clear()

    def sync_time(self):
        if self.s:
            unix_time = int(time.time())
            cmd = f"SETTIME {unix_time}\n"
            self.s.sendall(cmd.encode('utf-8'))

    def stop(self):
        self.running = False
        self.quit()
        self.wait()
