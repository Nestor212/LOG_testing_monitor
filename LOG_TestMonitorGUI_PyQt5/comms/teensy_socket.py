import socket
import time
import datetime
import threading
import os
import csv
from PyQt5.QtCore import QThread
from comms.parser_emitter import ParserEmitter
from Database.db import get_connection  # Ensure this is at the top of your file



class TeensySocketThread(QThread):
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

        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.data_dir = os.path.join(base_dir, "..", "Database", "Data")
        os.makedirs(self.data_dir, exist_ok=True)

        self.load_buffer = []
        self.accel_buffer = []
        self.last_valid_accels = [0.0, 0.0, 0.0]  # Default accelerometer values
        self.last_flush = time.time()

        self.lc_zero_load_offset = [1.6378,	8.8097,	-6.3057, 1.1999, 1.2814, -0.0209]
        self.load_offsets = [0.0] * 6
        self.accel_offset = [0.0, 0.0, 0.0]
        self.zero_pending = {"loads": True, "accels": True}

    def zero_loads(self):
        if self.latest_data:
            _, loads, *_ = self.latest_data
            self.load_offsets = loads[:]
            self.zero_pending["loads"] = True
            print(f"🔧 Zeroed load cells: {self.load_offsets}")

    def zero_accels(self):
        if self.latest_data:
            _, _, accels, accel_on, accel_stale = self.latest_data
            if accel_on and not accel_stale:
                self.accel_offset = accels[:]
                self.zero_pending["accels"] = True
                print(f"🔧 Zeroed accelerometer: {self.accel_offset}")


    def emit_loop(self):
        while self.running:
            time.sleep(self.emit_interval)
            if self.latest_data:
                # print(f"Emitting {time.time()}")
                timestamp, loads, accels, accel_on, accel_stale = self.latest_data
                self.emitter.new_data.emit(timestamp, loads, accels, accel_on, accel_stale)

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
                    try:
                        chunk = self.s.recv(4096).decode(errors='ignore')
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


            if accels:
                adjusted_accels = [a - offset for a, offset in zip(accels, self.accel_offset)]
                self.last_valid_accels = adjusted_accels
                self.accel_buffer.append([timestamp_str] + adjusted_accels)

            adjusted_loads = [l - offset - zero_load for l, offset, zero_load in zip(loads, self.load_offsets, self.lc_zero_load_offset)]

            self.load_buffer.append((timestamp, *adjusted_loads))

            self.latest_data = (timestamp_str, adjusted_loads, self.last_valid_accels, accel_on, accel_stale)

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

    def flush_logs(self):
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        conn = get_connection()
        cursor = conn.cursor()

        if self.zero_pending["loads"]:
            cursor.execute("""
                INSERT INTO load_cell_zero_offsets (
                    timestamp, lc1_offset, lc2_offset, lc3_offset, lc4_offset, lc5_offset, lc6_offset
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, [now_str] + self.load_offsets)
            self.zero_pending["loads"] = False

        if self.zero_pending["accels"]:
            cursor.execute("""
                INSERT INTO accelerometer_zero_offsets (
                    timestamp, ax_offset, ay_offset, az_offset
                ) VALUES (?, ?, ?, ?)
            """, [now_str] + self.accel_offset)
            self.zero_pending["accels"] = False

        conn.commit()
        conn.close()

        now = time.time()
        if now - self.last_flush < 0.1:
            return
        self.last_flush = now

        if self.load_buffer or self.accel_buffer:
            conn = get_connection()
            cursor = conn.cursor()

            if self.load_buffer:
                cursor.executemany("""
                    INSERT INTO load_cells (timestamp, lc1, lc2, lc3, lc4, lc5, lc6)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, self.load_buffer)
                self.load_buffer.clear()

            if self.accel_buffer:
                cursor.executemany("""
                    INSERT INTO accelerometer (timestamp, ax, ay, az)
                    VALUES (?, ?, ?, ?)
                """, self.accel_buffer)
                self.accel_buffer.clear()

            conn.commit()
            conn.close()


    # def flush_logs(self):
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
