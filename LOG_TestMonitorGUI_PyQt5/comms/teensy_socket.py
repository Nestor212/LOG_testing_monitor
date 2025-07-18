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

        # self.lc_zero_load_offset = [1.638, 8.810, -6.306, 1.200, 1.281, -0.021] # PGA Bypassed
        self.lc_zero_load_offset = [0.238, 7.410, -7.706, -0.200, -0.119, -1.421] # PGA Enabled G = 1, less noisy 


        if not TeensySocketThread.first_connection_done or not TeensySocketThread.zeroed:
            self.load_offsets = [0.0] * 6
            self.zero_pending = {"loads": False, "accels": False}
            TeensySocketThread.first_connection_done = True
        else:
            self.load_offsets = self.fetch_latest_load_offsets_from_db()
            # self.emitter.log_message.emit(f"🔌 Loaded offsets: {self.load_offsets}")
            self.zero_pending = {"loads": False, "accels": False}

        self.accel_offset = [0.0, 0.0, 0.0]

        self.db_queue = Queue(maxsize=10000)  # Use a large queue to handle bursts
        self._db_writer_thread = threading.Thread(target=self._db_writer_loop, daemon=True)
        self._db_writer_thread.start()


    def load_last_offsets(self):
        """Load the last stored offsets from the database."""
        self.load_offsets = self.fetch_latest_load_offsets_from_db()
        rounded_offsets = [round(val, 2) for val in self.load_offsets]
        self.emitter.log_message.emit(f"🔌 Loaded offsets from DB: {rounded_offsets}")
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
                self.emitter.log_message.emit("⚠ No load cell zero offsets found in DB, using zeros.")
                return [0.0] * 6
        except Exception as e:
            self.emitter.log_message.emit(f"⚠ DB error fetching load offsets: {e}")
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
                self.emitter.log_message.emit(
                    f"🔧 Zeroed load cells: {[round(val, 2) for val in self.load_offsets]}"
                )
        else:
            # Clear load offsets without zeroing
            TeensySocketThread.zeroed = False
            self.load_offsets = [0.0] * 6
            self.zero_pending["loads"] = False
            self.emitter.log_message.emit("🔧 Cleared load cell offsets.")

    def zero_accels(self, zeroing=False):
        if zeroing:
            if self.latest_data:
                _, _, accels, accel_on, accel_stale = self.latest_data
                if accel_on and not accel_stale:
                    self.accel_offset = accels[:]
                    self.zero_pending["accels"] = True
                    self.emitter.log_message.emit(
                    f"🔧 Zeroed accelerometer: {[round(val, 2) for val in self.accel_offset]}"
                    )
        else:
            # Clear accelerometer offsets without zeroing
            self.accel_offset = [0.0, 0.0, 0.0]
            self.zero_pending["accels"] = False
            self.emitter.log_message.emit("🔧 Cleared accelerometer offsets.")

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
        self.emitter.log_message.emit("🔌 Starting socket thread.")
        self.running = True

        # Start emit loop if not already
        if not hasattr(self, 'emit_thread_started'):
            threading.Thread(target=self.emit_loop, daemon=True).start()
            self.emit_thread_started = True

        while self.running:
            try:
                self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.s.settimeout(3)  # Connect timeout
                self.s.connect((self.host, self.port))
                self.s.settimeout(0.8)  # Read timeout for recv

                self.emitter.log_message.emit("Connected to Teensy.")
                self.s.sendall(b"HELLO\n")
                time.sleep(0.1)
                self.sync_time()

                self._recv_loop()

            except (socket.timeout, ConnectionRefusedError, OSError) as e:
                self.emitter.log_message.emit(f"Socket error: {e}")

            finally:
                self._cleanup_socket()
                time.sleep(1)  # Delay before retry

    def _recv_loop(self):
        buffer = ""
        self.last_read_time = time.time()

        while self.running:
            try:
                chunk = self.s.recv(2048).decode(errors='ignore')

                if not chunk:
                    raise ConnectionResetError("Socket closed by peer.")

                self.last_read_time = time.time()
                buffer += chunk

                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    self.handle_line(line.strip())

                self.flush_logs()

            except socket.timeout:
                # Minor network hiccup — just continue
                self.emitter.log_message.emit("Minor Socket timeout, waiting for more data...")
                continue

            except (ConnectionResetError, OSError) as e:
                self.emitter.log_message.emit(f"Connection interrupted: {e}")
                break  # Exit to reconnect

            # Watchdog check happens **outside exceptions** for normal flow too
            if time.time() - self.last_read_time > 2:
                self.emitter.log_message.emit("Watchdog timeout: No data received in 2s. Forcing reconnect.")
                break

    def _cleanup_socket(self):
        try:
            if self.s:
                self.s.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            if self.s:
                self.s.close()
        except Exception:
            pass
        self.s = None

        self.emitter.log_message.emit("🔌 Socket closed. Cleaning up.")
        self.emitter.disconnected.emit()

        # Clear buffers
        self.avg_load_buffer.clear()
        self.avg_accel_buffer.clear()
        self.db_load_buffer.clear()
        self.pre_trigger_buffer.clear()

    # def run(self):
    #     self.emitter.log_message.emit("🔌 Starting socket thread.")
    #     buffer = ""
    #     self.inactivity_timeout = 2.0  # Seconds without data → auto disconnect

    #     if not hasattr(self, 'emit_thread_started'):
    #         threading.Thread(target=self.emit_loop, daemon=True).start()
    #         self.emit_thread_started = True

    #     while self.running:
    #         try:
    #             self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    #             self.s.settimeout(3)  # Timeout for connect
    #             self.s.connect((self.host, self.port))
    #             self.s.settimeout(1)  # Shorter timeout for recv

    #             self.s.sendall(b"HELLO\n")
    #             time.sleep(0.1)
    #             self.sync_time()

    #             while self.running:
    #                 if time.time() - self.last_read_time > self.inactivity_timeout:
    #                     self.emitter.log_message.emit("⚠️ Inactivity timeout — auto-disconnecting.")
    #                     self.emitter.disconnected.emit()
    #                     self.stop()
    #                     return

    #                 try:
    #                     chunk = self.s.recv(2048).decode(errors='ignore')
    #                 except (socket.timeout, ConnectionResetError, OSError) as e:
    #                     if self.running:
    #                         self.emitter.log_message.emit(f"⚠️ Socket receive error: {e}")
    #                         break
    #                     else:
    #                         break

    #                 if not chunk:
    #                     self.emitter.log_message.emit("⚠️ Socket closed by teensy.")
    #                     break

    #                 self.last_read_time = time.time()
    #                 buffer += chunk

    #                 while '\n' in buffer:
    #                     line, buffer = buffer.split('\n', 1)
    #                     line = line.strip()
    #                     if not line:
    #                         continue  # Skip empty lines
    #                     elif line.startswith("TS ") and line.count(' ') >= 12:
    #                         self.handle_line(line)
    #                     elif line.startswith("LC") or line.startswith("Time"):
    #                         self.emitter.log_message.emit(f"Teensy says: {line}")
    #                     elif line.startswith("\n"):
    #                         continue
    #                     else:
    #                         self.emitter.log_message.emit(f"⚠️ Unparsed line: {line}")

    #                 self.flush_logs()

    #         except (socket.timeout, ConnectionRefusedError, OSError) as e:
    #             self.emitter.log_message.emit(f"⚠️ Connection error: {e}")
    #             time.sleep(5)
    #         finally:
    #             if self.s:
    #                 try:
    #                     self.s.sendall(b"D\n")
    #                 except Exception:
    #                     pass
    #                 try:
    #                     self.s.close()
    #                 except Exception:
    #                     pass
    #                 self.s = None
    #                 self.emitter.disconnected.emit()

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
            pass
            # self.emitter.log_message.emit(f"⚠️ Parse error: {e} — line: {line}")

    def _parse_fields(self, line):
        fields = line[3:].strip().split()
        if len(fields) != 12:
            # self.emitter.log_message.emit(f"⚠️ Malformed line: {line}")
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
            self.trigger_active = False
            self.post_trigger_frames_remaining = 0
            self.last_fz = None
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
            self.trigger_active = True
            self.post_trigger_frames_remaining = 0
            self.db_load_buffer = list(self.pre_trigger_buffer)
            self.emitter.log_message.emit(f"Triggered at Fz = {round(fz, 1)} lbf. Trigger value = {self.trigger_value} lbf.")
            self.trigger_timestamp = datetime.datetime.now()
            self.emitter.trigger_started.emit(self.trigger_timestamp)           

        # 🔽 Start post-trigger countdown on falling edge
        elif untriggered and self.trigger_active and self.post_trigger_frames_remaining == 0:
            self.post_trigger_frames_remaining = self.trigger_delay_frames

        # ⏳ Finish countdown if started
        if untriggered and self.post_trigger_frames_remaining > 0:
            self.post_trigger_frames_remaining -= 1

            # When delay ends, finish session
            if self.post_trigger_frames_remaining == 0:
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
        lc_log_path = os.path.join(self.data_dir, "load_buffer_log.csv")
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
                    self.emitter.log_message.emit(f"⚠️ DB writer error: {e}")
                finally:
                    self.db_queue.task_done()

    def flush_logs(self):
        # If trigger is enabled but not yet fired, skip flushing
        if self.trigger_enabled and not self.trigger_active:
            self.db_load_buffer.clear()
            self.accel_buffer.clear()
            return
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
        self.emitter.log_message.emit("🛑 Stopping socket thread.")
        self.running = False
        try:
            if self.s:
                self.s.shutdown(socket.SHUT_RDWR)
                self.s.close()
                self.s = None
        except Exception as e:
            self.emitter.log_message.emit(f"⚠️ Socket close error during stop: {e}")
        self.quit()
        self.wait()
