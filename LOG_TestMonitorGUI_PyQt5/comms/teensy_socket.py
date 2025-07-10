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
from collections import deque
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
        self.emit_interval = 0.50  # 20 Hz
        self.avg_load_buffer = []
        self.avg_accel_buffer = []
        self.avg_accel_on = False
        self.avg_accel_stale = False
        self.last_read_time = time.time()

        self.trigger_enabled = False
        self.trigger_active = False
        self.trigger_mode = "Threshold"
        self.trigger_value = 0.0  # Force threshold in lbf, or force delta depending on trigger mode
        self.last_force_vector = None
        self.pre_trigger_buffer = deque(maxlen=int(64*10))  # ~10 sec of pre-data
        self.active_buffer = []
        self.post_trigger_frames_remaining = 0
        self.trigger_delay_frames = int(64*10)  # ~10 sec of post-data
        self.last_fz = None

        if getattr(sys, 'frozen', False):
            # Running as PyInstaller bundle
            base_dir = os.path.dirname(sys.executable)
        else:
            # Running as script
            base_dir = os.path.dirname(os.path.abspath(__file__))

        self.data_dir = os.path.join(base_dir, "..", "Database", "Data")
        os.makedirs(self.data_dir, exist_ok=True)

        self.db_load_buffer = []
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
            # print("🔌 Subsequent connection detected, fetching latest zero offsets from DB.", flush=True)
            self.load_offsets = self.fetch_latest_load_offsets_from_db()
            # print(f"🔌 Loaded offsets: {self.load_offsets}", flush=True)
            self.zero_pending = {"loads": False, "accels": False}

        self.accel_offset = [0.0, 0.0, 0.0]

        self.db_queue = Queue()
        self._db_writer_thread = threading.Thread(target=self._db_writer_loop, daemon=True)
        self._db_writer_thread.start()


    def load_last_offsets(self):
        """Load the last stored offsets from the database."""
        self.load_offsets = self.fetch_latest_load_offsets_from_db()
        # print(f"🔌 Loaded offsets from DB: {self.load_offsets}", flush=True)
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

            # 🔁 Always reset buffers regardless
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
                    # if time.time() - self.last_read_time > 0.1:
                        # print(F"Elapsed time since last read: {time.time() - self.last_read_time:.2f} seconds", flush=True)
                    
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
                                # if dt > 2:  # flag slow lines
                                #     print(f"🐢 handle_line took {dt:.2f} ms", flush=True)
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
            fields = self._parse_fields(line)
            if fields is None:
                return

            timestamp, loads, accels, accel_on, accel_stale = fields
            adjusted_loads = self._process_loads(loads, timestamp)
            adjusted_accels = self._process_accels(accels, accel_on, accel_stale, timestamp)

            # Save values to emitter buffers
            self.avg_load_buffer.append(adjusted_loads)
            if adjusted_accels is not None:
                self.avg_accel_buffer.append(adjusted_accels)

            self._update_trigger_logic(adjusted_loads)
            self._update_sps_counter(timestamp.timestamp(), bool(adjusted_accels))

        except Exception as e:
            print(f"⚠️ Parse error: {e} — line: {line}", flush=True)

    def _parse_fields(self, line):
        fields = line[3:].strip().split()
        if len(fields) != 12:
            print(f"⚠️ Malformed line: {line}", flush=True)
            return None

        raw_ts = float(fields[0])
        timestamp = datetime.datetime.fromtimestamp(raw_ts)
        loads = list(map(float, fields[1:7]))
        accel_on = int(fields[7])
        accel_stale = fields[11] == '1'
        accels = list(map(float, fields[8:11])) if accel_on and not accel_stale else []
        return timestamp, loads, accels, accel_on, accel_stale

    def _update_trigger_logic(self, loads):
        if not self.trigger_enabled:
            return

        fz = loads[0] + loads[2] + loads[4]
        triggered = False
        untriggered = False

        if self.trigger_mode == "Threshold":
            if not self.trigger_active and fz >= self.trigger_value:
                triggered = True
            elif self.trigger_active and fz < self.trigger_value:
                untriggered = True

        elif self.trigger_mode == "Delta":
            if self.last_fz is not None:
                delta = fz - self.last_fz
                if not self.trigger_active and delta >= self.trigger_value:
                    triggered = True
                elif self.trigger_active and delta <= -self.trigger_value:
                    untriggered = True

        self.last_fz = fz

        # 🔼 Trigger just activated
        if triggered:
            # print("⚡ Trigger ON")
            self.trigger_active = True
            self.post_trigger_frames_remaining = 0
            self.db_load_buffer = list(self.pre_trigger_buffer)
            print(f"Triggered. Db load buffer size: {len(self.db_load_buffer)}")
            self.trigger_timestamp = datetime.datetime.now()
            self.emitter.trigger_started.emit(self.trigger_timestamp)           

        # 🔽 Start post-trigger countdown on falling edge
        elif untriggered and self.trigger_active and self.post_trigger_frames_remaining == 0:
            # print("⏹ Trigger OFF (start delay)")
            self.post_trigger_frames_remaining = self.trigger_delay_frames

        # ⏳ Finish countdown if started
        if untriggered and self.post_trigger_frames_remaining > 0:
            self.post_trigger_frames_remaining -= 1

            # When delay ends, finish session
            if self.post_trigger_frames_remaining == 0:
                # print("🛑 Trigger DONE — flushing to log")
                self.trigger_active = False

    def _process_loads(self, loads, timestamp):
        adjusted = [l - offset - zero for l, offset, zero in zip(loads, self.load_offsets, self.lc_zero_load_offset)]
        rounded = [round(x, 4) for x in adjusted]

        self.pre_trigger_buffer.append((timestamp, *rounded))

        # Store if trigger is active or finishing
        if self.trigger_enabled:
            if self.trigger_active or self.post_trigger_frames_remaining > 0:
                self.db_load_buffer.append((timestamp, *rounded))
        else:
            # Trigger disabled — regular logging
            self.db_load_buffer.append((timestamp, *rounded))

        return adjusted

    def _process_accels(self, accels, accel_on, accel_stale, timestamp):
        if not accels:
            return None

        adjusted = [a - offset for a, offset in zip(accels, self.accel_offset)]
        rounded = [round(a, 4) for a in adjusted]
        self.last_valid_accels = adjusted

        self.accel_buffer.append([timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]] + rounded)
        self.avg_accel_on = True
        self.avg_accel_stale = accel_stale

        return adjusted

    def _update_sps_counter(self, raw_ts, has_accel):
        current_sec = int(raw_ts)
        if not hasattr(self, 'last_sps_sec'):
            self.last_sps_sec = current_sec
            self.lc_sps_counter = 0
            self.accel_sps_counter = 0

        if current_sec == self.last_sps_sec:
            self.lc_sps_counter += 1
            if has_accel:
                self.accel_sps_counter += 1
        else:
            self.emitter.update_sps.emit(self.lc_sps_counter, self.accel_sps_counter)
            self.last_sps_sec = current_sec
            self.lc_sps_counter = 1
            self.accel_sps_counter = 1 if has_accel else 0

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

                    if payload["db_load_buffer"]:
                        cursor.executemany("""
                            INSERT INTO load_cells (timestamp, lc1, lc2, lc3, lc4, lc5, lc6)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, payload["db_load_buffer"])

                        # Write to CSV
                        for row in payload["db_load_buffer"]:
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
        # If trigger is enabled but not yet fired, skip flushing
        if self.trigger_enabled and not self.trigger_active:
            self.db_load_buffer.clear()
            self.accel_buffer.clear()
            return
        # print("flushing logs.")
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        payload = {
            "zero_pending": self.zero_pending.copy(),
            "load_offsets": self.load_offsets.copy(),
            "accel_offset": self.accel_offset.copy(),
            "db_load_buffer": self.db_load_buffer.copy(),
            "accel_buffer": self.accel_buffer.copy(),
            "timestamp": now_str
        }

        self.zero_pending = {"loads": False, "accels": False}
        self.db_load_buffer.clear()
        self.accel_buffer.clear()

        self.db_queue.put(payload)

    def sync_time(self):
        if self.s:
            unix_time = int(time.time())
            cmd = f"SETTIME {unix_time}\n"
            self.s.sendall(cmd.encode('utf-8'))

    def stop(self):
        self.running = False
        self.quit()
        self.wait()
