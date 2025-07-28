from PyQt5.QtWidgets import (
    QMainWindow, QLabel, QPushButton, QLineEdit,
    QVBoxLayout, QHBoxLayout, QWidget, QGridLayout, 
    QFrame, QSizePolicy, QMessageBox, QCheckBox,
    QComboBox, QTextEdit
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QColor, QPalette
from comms.teensy_socket import TeensySocketThread
from comms.parser_emitter import ParserEmitter
from PyQt5.QtCore import QTimer, QTime
from ui.plotter import PlotWindow
# from ui.moment_map import MomentMapWidget
from Database.export_data import DataExportDialog as Data
from ui.teensy_settings_dialog import TeensySettingsDialog
import os
import datetime
import sys

def format_force(value, axis):
    if axis == "X":
        arrow = "→" if value >= 0 else "←"
    elif axis == "Y":
        arrow = "↓" if value >= 0 else "↑"
    elif axis == "Z":
        arrow = "▼" if value >= 0 else "▲"
    return f"{value:+.3f} {arrow}"

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Force Display — Teensy Monitor")
        self.setGeometry(100, 100, 800, 550)

        self.port = 5000

        self.plot_windows = []
        self.export_data_window = Data()

        self.socket_thread = None
        self.signal_emitter = ParserEmitter()
        self.signal_emitter.new_data.connect(self.update_display)
        self.signal_emitter.update_sps.connect(self.update_sps_display)
        self.signal_emitter.disconnected.connect(self.handle_disconnection)
        self.signal_emitter.log_message.connect(self.log_message)

        # Fonts
        font = QFont("Arial", 16, QFont.Bold)
        # Load cell labels
        self.labels = {}
        for lc in ["LC1", "LC2", "LC3", "LC4", "LC5", "LC6"]:
            label = QLabel(f"{lc}:\n ---")
            label.setFont(font)
            label.setAlignment(Qt.AlignCenter)
            label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.labels[lc] = label

        grid = QGridLayout()
        grid.setSpacing(10)
        grid.addWidget(self.labels["LC5"], 2, 2)
        grid.addWidget(self.labels["LC1"], 2, 0)
        grid.addWidget(self.labels["LC6"], 1, 1)
        grid.addWidget(self.labels["LC4"], 0, 2)
        grid.addWidget(self.labels["LC3"], 0, 1)
        grid.addWidget(self.labels["LC2"], 0, 0)

        frame = QFrame()
        frame.setFrameStyle(QFrame.Panel | QFrame.Raised)
        frame.setLineWidth(3)
        frame.setLayout(grid)
        frame.setFixedSize(600, 180)

        # Create the forces container widget
        forces_container = QWidget()

        # Forces title
        self.forces_title = QLabel("Forces (lbf)")
        self.forces_title.setFont(QFont("Arial", 16, QFont.Bold))

        # SPS label
        self.lc_sps_label = QLabel("SPS: ---")
        self.lc_sps_label.setFont(QFont("Arial", 12))

        self.lc_sps_led = QLabel()
        self.lc_sps_led.setFixedSize(20, 20)
        self.update_lc_sps_led("red")

        # Horizontal layout for the top row (forces + SPS)
        forces_row_layout = QHBoxLayout()
        forces_row_layout.addStretch()
        forces_row_layout.addWidget(self.forces_title)
        forces_row_layout.addSpacing(10)
        forces_row_layout.addWidget(self.lc_sps_label)
        forces_row_layout.addSpacing(10)
        forces_row_layout.addWidget(self.lc_sps_led)
        forces_row_layout.addStretch()

        # Orientation label (second row)
        self.orientation_label = QLabel("(↑ Center of Turn Table ↑)")
        self.orientation_label.setFont(QFont("Arial", 10))  # Optional: Slightly smaller font
        self.orientation_label.setStyleSheet("color: gray;")  # Optional: Gray for subtlety
        self.orientation_label.setAlignment(Qt.AlignCenter)

        # Combine both into a vertical layout
        forces_container_layout = QVBoxLayout()
        forces_container_layout.addLayout(forces_row_layout)      # Top row: Forces + SPS
        forces_container_layout.addWidget(self.orientation_label) # Bottom: Orientation

        # Set layout to the container widget
        forces_container.setLayout(forces_container_layout)

        # Acceleration Labels and SPS
        self.accel_led = QLabel()
        self.accel_led.setFixedSize(20, 20)
        self.update_accel_led("red")
        self.accel_title = QLabel("Acceleration (g)")
        self.accel_title.setFont(QFont("Arial", 16, QFont.Bold))
        self.accel_sps_label = QLabel("SPS: ---")
        self.accel_sps_label.setFont(QFont("Arial", 12))
        accel_header = QHBoxLayout()
        accel_header.addWidget(self.accel_led)
        accel_header.addWidget(self.accel_title)
        accel_header.addSpacing(10)
        accel_header.addWidget(self.accel_sps_label)

        accel_header_container = QWidget()
        accel_header_container.setLayout(accel_header)

        accel_header_layout = QHBoxLayout()
        accel_header_layout.addStretch()
        accel_header_layout.addWidget(accel_header_container)
        accel_header_layout.addStretch()

        self.accel_labels = {}
        for axis in ["X", "Y", "Z"]:
            lbl = QLabel(f"{axis}: ---")
            lbl.setFont(QFont("Arial", 14))
            lbl.setAlignment(Qt.AlignCenter)
            self.accel_labels[axis] = lbl

        accel_grid = QHBoxLayout()
        accel_grid.addWidget(self.accel_labels["X"])
        accel_grid.addWidget(self.accel_labels["Y"])
        accel_grid.addWidget(self.accel_labels["Z"])

        # Clock Label
        self.clock_label = QLabel("Time: ---")
        self.clock_label.setFont(QFont("Arial", 8))
        
        # Timer to update time every second
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_time)
        self.timer.start(1000)

        # Connection Controls
        self.ip_input = QLineEdit("192.168.1.232")
        # self.ip_input = QLineEdit("10.130.91.42")
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.toggle_connection)
        self.status_led = QLabel()
        self.status_led.setFixedSize(20, 20)
        self.update_led("red")

        self.load_offsets_checkbox = QCheckBox("Load Stored Offsets")
        self.load_offsets_checkbox.setChecked(False)

        self.trigger_checkbox = QCheckBox("Trigger")
        self.trigger_checkbox.setChecked(False)

        self.trigger_selector = QComboBox()
        self.trigger_selector.addItems(["Threshold", "Delta"])
        self.trigger_selector.setCurrentIndex(0)

        self.trigger_input = QLineEdit("0.0")
        self.trigger_label = QLabel("Force")

        self.trigger_checkbox.stateChanged.connect(self.update_trigger_widget_states)
        self.trigger_checkbox.stateChanged.connect(self.update_trigger_settings)
        # self.trigger_selector.currentIndexChanged.connect(self.update_trigger_settings)
        # self.trigger_input.textChanged.connect(self.update_trigger_settings)

        self.update_trigger_widget_states()

        conn_layout = QHBoxLayout()
        conn_layout.addWidget(QLabel("IP:"))
        conn_layout.addWidget(self.ip_input)
        conn_layout.addWidget(self.connect_btn)
        conn_layout.addWidget(QLabel("Status:"))
        conn_layout.addWidget(self.status_led)
        # conn_layout.addWidget(self.load_offsets_checkbox)
        conn_layout.addWidget(self.trigger_checkbox)
        conn_layout.addWidget(self.trigger_selector)
        conn_layout.addWidget(self.trigger_label)
        conn_layout.addWidget(self.trigger_input)
        conn_layout.addStretch(1)
        conn_layout.addWidget(self.clock_label)

        self.zero_lc_btn = QPushButton("Zero Loads")
        self.zero_lc_btn.clicked.connect(self.zero_loads)
        self.clear_zero_lc_btn = QPushButton("Clear Load Offsets")
        self.clear_zero_lc_btn.clicked.connect(self.clear_load_offsets)

        self.zero_accel_btn = QPushButton("Zero Accels")
        self.zero_accel_btn.clicked.connect(self.zero_accels)
        self.clear_zero_accel_btn = QPushButton("Clear Accel Offsets")
        self.clear_zero_accel_btn.clicked.connect(self.clear_accel_offsets)

        self.plot_btn = QPushButton("Open Plotter")
        self.plot_btn.clicked.connect(self.show_plot_window)

        self.export_data_btn = QPushButton("Export Data")
        self.export_data_btn.clicked.connect(self.show_export_data_window)

        self.teensy_settings_btn = QPushButton("Teensy Settings")
        self.teensy_settings_btn.clicked.connect(self.show_teensy_settings)

        self.saved_teensy_settings = {
            "conv_mode": "Continuous",
            "sps": "800",
            "load_cells": [True]*6
        }

        zero_grid = QGridLayout()
        zero_grid.addWidget(self.zero_lc_btn, 0, 0)
        zero_grid.addWidget(self.clear_zero_lc_btn, 0, 1)
        zero_grid.addWidget(self.zero_accel_btn, 0, 2)
        zero_grid.addWidget(self.clear_zero_accel_btn, 0, 3)
        zero_grid.addWidget(self.plot_btn, 1, 1)
        zero_grid.addWidget(self.export_data_btn, 1, 2)
        zero_grid.addWidget(self.teensy_settings_btn, 1, 3)


        legend = QLabel("Arrows indicate direction of applied force. X: ←→ , Y: ↑↓ , Z: ▼ (down) ▲ (up)")
        legend.setAlignment(Qt.AlignCenter)

        # Initialize net_force_labels dict
        self.net_force_labels = {}

        # Helper to create consistent labels
        def make_label(text):
            lbl = QLabel(text)
            lbl.setFont(QFont("Arial", 14))
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setFrameStyle(QFrame.Panel | QFrame.Sunken)
            return lbl

        # Create force value labels
        self.net_force_labels['Fx'] = make_label("Fx: ---")
        self.net_force_labels['Fy'] = make_label("Fy: ---")
        self.net_force_labels['Fz'] = make_label("Fz: ---")
        self.net_force_labels['Moment_X'] = make_label("Moment X: --- lbf-in")
        self.net_force_labels['Moment_Y'] = make_label("Moment Y: --- lbf-in")
        self.net_force_labels['Moment_Z'] = make_label("Moment Z: --- lbf-in")
        self.total_force_label = make_label("Vector Magnitude: --- lbf")

        # Create grid layout
        net_force_grid = QGridLayout()

        # Title
        net_force_title = QLabel("Load Cell Forces and Moments")
        net_force_title.setFont(QFont("Arial", 16, QFont.Bold))
        net_force_title.setAlignment(Qt.AlignCenter)
        net_force_grid.addWidget(net_force_title, 0, 0, 1, 3)
        net_force_grid.setVerticalSpacing(2)
        net_force_grid.setContentsMargins(0, 0, 0, 0)

        # First row: Fx, Fy, Fz
        net_force_grid.addWidget(self.net_force_labels['Fx'], 1, 0)
        net_force_grid.addWidget(self.net_force_labels['Fy'], 1, 1)
        net_force_grid.addWidget(self.net_force_labels['Fz'], 1, 2)
        
        # Seconf row:
        net_force_grid.addWidget(self.total_force_label,      2, 0,1, 3)

        # Second row: Sum Fz, Net Fy, Total Y Reaction
        net_force_grid.addWidget(self.net_force_labels['Moment_X']  , 3, 0)
        net_force_grid.addWidget(self.net_force_labels['Moment_Y']  , 3, 1)
        net_force_grid.addWidget(self.net_force_labels['Moment_Z'], 3, 2)

        # Console output
        self.console_output = QTextEdit()
        self.console_output.setReadOnly(True)
        self.console_output.setStyleSheet("""
            background-color: #FFFFFF;
            color: #000000;
            font-family: monospace;
            font-size: 12px;
        """)
        self.console_output.setFixedHeight(80)  # Adjust as needed

        # Main Layout
        main_layout = QVBoxLayout()
        main_layout.addLayout(conn_layout)
        main_layout.addWidget(forces_container)
        main_layout.addWidget(frame, alignment=Qt.AlignCenter)
        main_layout.addWidget(legend)
        main_layout.addLayout(net_force_grid)
        main_layout.addLayout(accel_header_layout)
        main_layout.addLayout(accel_grid)
        main_layout.addLayout(zero_grid)
        main_layout.addWidget(self.console_output)

        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

        if getattr(sys, 'frozen', False):
            # Running as PyInstaller bundle
            base_dir = os.path.dirname(sys.executable)
        else:
            # Running as script
            base_dir = os.path.dirname(os.path.abspath(__file__))

        # log_file = f"lc_sps_log_{datetime.date.today().isoformat()}.csv"
        # self.sps_log_path = os.path.join(base_dir, "..", "Database", log_file)
        # with open(self.sps_log_path, 'a', newline='') as f:
        #     writer = csv.writer(f)
        #     writer.writerow(["Timestamp", "LC_SPS", "Accel_SPS"])
        
        self.sys_log_path = os.path.join(base_dir, "..", "Database", "sys_log.txt")

    def show_teensy_settings(self):
        dlg = TeensySettingsDialog(
            parent=self, 
            socket_thread=self.socket_thread, 
            log_callback=self.log_message,
            initial_settings=self.saved_teensy_settings
        )
        if dlg.exec_():
            self.saved_teensy_settings = dlg.get_teensy_settings()

    def log_message(self, message):
        # Update UI console output
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        self.console_output.append(log_entry)

        with open(self.sys_log_path, "a") as f:
            f.write(log_entry + "\n")

    def handle_disconnection(self, connected):
        if not connected:
            self.log_message("🔌 Disconnected signal received.")
            self.connect_btn.setText("Connect")
            self.update_led("red")
            self.update_accel_led("red")
            self.update_trigger_widget_states()
        else:
            self.log_message("🔗 Connected signal received.")
            self.connect_btn.setText("Disconnect")
            self.update_led("green")
            self.update_accel_led("green")
            self.update_trigger_widget_states()

    def update_trigger_widget_states(self):
        trigger_enabled = self.trigger_checkbox.isChecked()

        self.trigger_selector.setEnabled(not trigger_enabled)
        self.trigger_input.setEnabled(not trigger_enabled)
        self.trigger_label.setEnabled(not trigger_enabled)

    def update_trigger_settings(self):
        if not self.socket_thread:
            return
        self.socket_thread.trigger_enabled = self.trigger_checkbox.isChecked()

        try:
            value = float(self.trigger_input.text())
        except ValueError:
            self.log_message("⚠ Invalid trigger value, must be float")
            return

        if self.trigger_selector.currentText() == "Threshold":
            self.socket_thread.trigger_mode = "Threshold"
        elif self.trigger_selector.currentText() == "Delta":
            self.socket_thread.trigger_mode = "Delta"
        self.socket_thread.trigger_value = value

        self.update_trigger_widget_states()
        if self.socket_thread.trigger_enabled:
            self.log_message(f"Trigger enabled: {self.socket_thread.trigger_mode} at {value} lbf")
        else:
            self.log_message("Trigger disabled")

    def show_plot_window(self):
        plot_window = PlotWindow(self.signal_emitter)
        self.plot_windows.append(plot_window)
        plot_window.show()

    def show_export_data_window(self):
        self.export_data_window.show()
        self.export_data_window.raise_()
        self.export_data_window.activateWindow()

    def zero_loads(self):
        if self.socket_thread:
            reply = QMessageBox.question(self, "Confirm Zero Loads",
                                        "Are you sure you want to zero the load cells?\nThis will set the current values as offsets.",
                                        QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.socket_thread.zero_loads(True)

    def clear_load_offsets(self):
        if self.socket_thread:
            reply = QMessageBox.question(self, "Confirm Clear Load Offsets",
                                        "Are you sure you want to clear the load cell offsets?\nThis will remove all zeroing.",
                                        QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.socket_thread.zero_loads(False)

    def zero_accels(self):
        if self.socket_thread:
            reply = QMessageBox.question(self, "Confirm Zero Accels",
                                        "Are you sure you want to zero the accelerometers?\nThis will set the current values as offsets.",
                                        QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.socket_thread.zero_accels(True)

    def clear_accel_offsets(self):
        if self.socket_thread:
            reply = QMessageBox.question(self, "Confirm Clear Accel Offsets",
                                        "Are you sure you want to clear the accel offsets?\nThis will remove all zeroing.",
                                        QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.socket_thread.zero_accels(False)

    def update_time(self):
        current_time = QTime.currentTime().toString("HH:mm:ss")
        self.clock_label.setText(f"Time: {current_time}")

    def update_led(self, color):
        palette = self.status_led.palette()
        palette.setColor(QPalette.Window, QColor(color))
        self.status_led.setAutoFillBackground(True)
        self.status_led.setPalette(palette)

    def toggle_connection(self):
        if self.socket_thread and self.socket_thread.isRunning():
            self.log_message("🛑 Disconnecting...")
            self.socket_thread.stop()
            self.socket_thread = None
            self.connect_btn.setText("Connect")
            self.update_led("red")
            self.update_accel_led("red")
            self.update_lc_sps_led("red")
            self.update_trigger_widget_states()
            self.load_offsets_checkbox.setEnabled(True)
        else:
            ip = self.ip_input.text().strip()
            if not ip:
                self.log_message("⚠️ IP address is empty.")
                return

            # Prevent starting multiple threads
            if self.socket_thread:
                self.log_message("⚠️ Previous socket thread still exists. Cleaning up...")
                self.socket_thread.stop()
                self.socket_thread = None

            self.log_message("🔗 Connecting...")
            self.update_led("yellow")
            self.socket_thread = TeensySocketThread(ip, self.port, self.signal_emitter)
            self.socket_thread.start()
            self.connect_btn.setText("Disconnect")
            self.update_led("green")
            self.load_offsets_checkbox.setEnabled(False)

            # if self.load_offsets_checkbox.isChecked():
            self.socket_thread.load_last_offsets()

            self.update_trigger_settings()

    def update_lc_sps_led(self, color):
        palette = self.lc_sps_led.palette()
        palette.setColor(QPalette.Window, QColor(color))
        self.lc_sps_led.setAutoFillBackground(True)
        self.lc_sps_led.setPalette(palette)

    def update_accel_led(self, color):
        palette = self.accel_led.palette()
        palette.setColor(QPalette.Window, QColor(color))
        self.accel_led.setAutoFillBackground(True)
        self.accel_led.setPalette(palette)

    def compute_moments_from_loads(self, loads):
        """
        Compute Mx, My, and Mz from raw load cell force readings.
        Uses correct positions and force contributions based on physical layout.
        Positive directions:
            - Fx: right (LC6)
            - Fy: down (LC2, LC4)
            - Fz: down (LC1, LC3, LC5)
            - Mx: about X (rotation in Y-Z plane)
            - My: about Y (rotation in X-Z plane)
            - Mz: about Z (rotation in X-Y plane)
        """
        mm_to_in = 1 / 25.4
        positions = {
            0: (-330 * mm_to_in, 181 * mm_to_in),  # LC1 (Fz)
            2: (0,            -181 * mm_to_in),    # LC3 (Fz)
            4: (330 * mm_to_in, 181 * mm_to_in),   # LC5 (Fz)
            1: (-257 * mm_to_in, -187 * mm_to_in), # LC2 (Fy)
            3: (257 * mm_to_in, -187 * mm_to_in),  # LC4 (Fy)
        }

        # Mx: from Z-forces at y-offsets
        mx = (
            loads[0] * positions[0][1] +  # F1 * y1
            loads[2] * positions[2][1] +  # F3 * y3
            loads[4] * positions[4][1]    # F5 * y5
        )

        # My: from Z-forces at x-offsets (negated)
        my = -(
            loads[0] * positions[0][0] +  # -F1 * x1
            loads[2] * positions[2][0] +  # -F3 * x3 (0)
            loads[4] * positions[4][0]    # -F5 * x5
        )

        # Mz: from Y-forces at x-offsets
        mz = (
            loads[1] * positions[1][0] +  # F2 * x2
            loads[3] * positions[3][0]    # F4 * x4
        )

        return mx, my, mz

    def update_display(self, timestamp, loads, accels, accel_on, accel_status):
        if self.socket_thread is None:
            return
        
        axis_map = {
            "LC1": "Z", "LC2": "Y", "LC3": "Z",
            "LC4": "Y", "LC5": "Z", "LC6": "X",
        }

        for i, lc in enumerate(["LC1", "LC2", "LC3", "LC4", "LC5", "LC6"]):
            axis = axis_map[lc]
            force_val = loads[i]
            label_text = f"{lc}:\n {format_force(force_val, axis)}"

            # Contact loss detection for Z-axis cells with non-zero preload
            if lc in ["LC1", "LC3", "LC5"]:
                preload = self.socket_thread.load_offsets[i]
                if preload != 0.0 and force_val < -preload:
                    # Contact lost → highlight red
                    self.labels[lc].setStyleSheet("color: red; border: 2px solid red;")
                else:
                    # Normal style
                    self.labels[lc].setStyleSheet("color: black; border: none;")
            else:
                # Other load cells, no contact check
                self.labels[lc].setStyleSheet("color: black; border: none;")

            self.labels[lc].setText(label_text)

        # for i, lc in enumerate(["LC1", "LC2", "LC3", "LC4", "LC5", "LC6"]):
        #     axis = axis_map[lc]
        #     force_val = loads[i]
        #     self.labels[lc].setText(f"{lc}:\n {format_force(force_val, axis)}")

        # Acceleration LED and values
        accel_color = "green" if accel_on else "red"
        if self.socket_thread:
            self.update_accel_led(accel_color)

        if accel_on:
            self.accel_title.setText("Acceleration (g)")
            for i, axis in enumerate(["X", "Y", "Z"]):
                self.accel_labels[axis].setText(f"{axis}: {accels[i]:+.2f} g")
        else:
            self.accel_title.setText("Acceleration (Unavailable)")
            for axis in ["X", "Y", "Z"]:
                self.accel_labels[axis].setText(f"{axis}: ---")

        # Force breakdown
        force_map = {
            "Fx": ([5], "X"),
            "Fy": ([1, 3], "Y"),
            "Fz": ([0, 2, 4], "Z")
        }

        fx_value = sum(loads[i] for i in force_map["Fx"][0])
        fy_net = sum(loads[i] for i in force_map["Fy"][0])
        fz_sum = sum(loads[i] for i in force_map["Fz"][0])

        for label_key, (indices, axis_for_arrow) in force_map.items():
            vals = [loads[i] for i in indices]
            net_force = sum(vals)
            self.net_force_labels[label_key].setText(
                f"{label_key}: {format_force(net_force, axis_for_arrow)} lbf"
            )

        # Vector magnitude
        import math
        vector_magnitude = math.sqrt(fx_value**2 + fy_net**2 + fz_sum**2)
        self.total_force_label.setText(f"Vector Magnitude: {vector_magnitude:.2f} lbf")

        # Compute moments from loads
        moment_x, moment_y, moment_z = self.compute_moments_from_loads(loads)
        self.net_force_labels['Moment_X'].setText(f"Moment X: {moment_x:.2f} lbf-in")
        self.net_force_labels['Moment_Y'].setText(f"Moment Y: {moment_y:.2f} lbf-in")
        self.net_force_labels['Moment_Z'].setText(f"Moment Z: {moment_z:.2f} lbf-in")

    def update_sps_display(self, lc_sps, accel_sps, sys_stable):
        if sys_stable:
            self.update_lc_sps_led("green")
        else:
            self.update_lc_sps_led("red")

        self.lc_sps_label.setText(f"LC SPS: {lc_sps}")
        self.accel_sps_label.setText(f"Accel SPS: {accel_sps}")

        # now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # with open(self.sps_log_path, 'a', newline='') as f:
        #     writer = csv.writer(f)
        #     writer.writerow([now, lc_sps, accel_sps])

    def closeEvent(self, event):
        if self.socket_thread and self.socket_thread.isRunning():
            self.log_message("🛑 Window closed — stopping socket thread...")
            self.socket_thread.stop()
        event.accept()

