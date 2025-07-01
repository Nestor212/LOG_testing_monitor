from PyQt5.QtWidgets import (
    QMainWindow, QLabel, QPushButton, QLineEdit,
    QVBoxLayout, QHBoxLayout, QWidget, QGridLayout, QFrame, QSizePolicy
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QColor, QPalette
from comms.teensy_socket import TeensySocketThread
from comms.parser_emitter import ParserEmitter
from PyQt5.QtCore import QTimer, QTime
from ui.plotter import PlotWindow
# from ui.moment_map import MomentMapWidget
from Database.export_data import DataExportDialog as Data
import csv
import os
import datetime

def format_force(value, axis):
    if axis == "X":
        arrow = "←" if value >= 0 else "→"
    elif axis == "Y":
        arrow = "↑" if value >= 0 else "↓"
    elif axis == "Z":
        arrow = "▼" if value >= 0 else "▲"
    return f"{value:+.1f} {arrow}"

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Force Display — Teensy Monitor")
        self.setGeometry(100, 100, 800, 550)

        self.plot_window = PlotWindow()
        # self.moment_map_window = MomentMapWidget()
        self.export_data_window = Data()

        self.socket_thread = None
        self.signal_emitter = ParserEmitter()
        self.signal_emitter.new_data.connect(self.update_display)
        self.signal_emitter.update_sps.connect(self.update_sps_display)

        # Fonts
        font = QFont("Arial", 18, QFont.Bold)
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
        grid.addWidget(self.labels["LC5"], 0, 0)
        grid.addWidget(self.labels["LC1"], 0, 2)
        grid.addWidget(self.labels["LC6"], 1, 1)
        grid.addWidget(self.labels["LC4"], 2, 0)
        grid.addWidget(self.labels["LC3"], 2, 1)
        grid.addWidget(self.labels["LC2"], 2, 2)

        frame = QFrame()
        frame.setFrameStyle(QFrame.Panel | QFrame.Raised)
        frame.setLineWidth(3)
        frame.setLayout(grid)
        frame.setFixedSize(560, 320)

        # Force Labels and SPS
        self.forces_title = QLabel("Forces (lbf)")
        self.forces_title.setFont(QFont("Arial", 16, QFont.Bold))
        self.lc_sps_label = QLabel("SPS: ---")
        self.lc_sps_label.setFont(QFont("Arial", 12))
        forces_header = QHBoxLayout()
        forces_header.addWidget(self.forces_title)
        forces_header.addSpacing(10)
        forces_header.addWidget(self.lc_sps_label)

        forces_header_container = QWidget()
        forces_header_container.setLayout(forces_header)

        forces_header_layout = QHBoxLayout()
        forces_header_layout.addStretch()
        forces_header_layout.addWidget(forces_header_container)
        forces_header_layout.addStretch()

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
        self.clock_label.setFont(QFont("Arial", 12))
        
        # Timer to update time every second
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_time)
        self.timer.start(1000)

        # Connection Controls
        self.ip_input = QLineEdit("192.168.1.100")
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.toggle_connection)
        self.status_led = QLabel()
        self.status_led.setFixedSize(20, 20)
        self.update_led("red")

        conn_layout = QHBoxLayout()
        conn_layout.addWidget(QLabel("IP:"))
        conn_layout.addWidget(self.ip_input)
        conn_layout.addWidget(self.connect_btn)
        conn_layout.addWidget(QLabel("Status:"))
        conn_layout.addWidget(self.status_led)
        conn_layout.addStretch(1)
        conn_layout.addWidget(self.clock_label)

        self.zero_lc_btn = QPushButton("Zero Loads")
        self.zero_lc_btn.clicked.connect(self.zero_loads)

        self.zero_accel_btn = QPushButton("Zero Accels")
        self.zero_accel_btn.clicked.connect(self.zero_accels)

        self.plot_btn = QPushButton("Open Plotter")
        self.plot_btn.clicked.connect(self.show_plot_window)

        # self.moment_map_btn = QPushButton("Open Moment Map")
        # self.moment_map_btn.clicked.connect(self.show_moment_map_window)

        self.export_data_btn = QPushButton("Export Data")
        self.export_data_btn.clicked.connect(self.show_export_data_window)

        zero_grid = QGridLayout()
        zero_grid.addWidget(self.zero_lc_btn, 0, 0)
        zero_grid.addWidget(self.zero_accel_btn, 0, 1)
        zero_grid.addWidget(self.plot_btn, 0, 2)
        # zero_grid.addWidget(self.moment_map_btn, 0, 3)
        zero_grid.addWidget(self.export_data_btn, 0, 3)


        legend = QLabel("Arrows indicate direction of applied force. X: ←→ , Y: ↑↓ , Z: ▼ (down) ▲ (up)")
        legend.setAlignment(Qt.AlignCenter)

        # Net force labels
        self.net_force_labels = {}
        for axis in ["Fx", "Fy", "Fz"]:
            lbl = QLabel(f"{axis}: ---")
            lbl.setFont(QFont("Arial", 14))
            lbl.setAlignment(Qt.AlignCenter)
            self.net_force_labels[axis] = lbl

        self.total_force_label = QLabel("Total: --- lbf")
        self.total_force_label.setFont(QFont("Arial", 14))
        self.total_force_label.setAlignment(Qt.AlignCenter)

        net_force_grid = QHBoxLayout()
        net_force_grid.addWidget(self.net_force_labels["Fx"])
        net_force_grid.addWidget(self.net_force_labels["Fy"])
        net_force_grid.addWidget(self.net_force_labels["Fz"])
        net_force_grid.addWidget(self.total_force_label)


        net_force_title = QLabel("Net Forces (lbf)")
        net_force_title.setFont(QFont("Arial", 16, QFont.Bold))
        net_force_title.setAlignment(Qt.AlignCenter)

        # Main Layout
        main_layout = QVBoxLayout()
        main_layout.addLayout(conn_layout)
        main_layout.addLayout(forces_header_layout)
        main_layout.addWidget(frame, alignment=Qt.AlignCenter)
        main_layout.addWidget(legend)
        main_layout.addWidget(net_force_title)
        main_layout.addLayout(net_force_grid)
        main_layout.addLayout(accel_header_layout)
        main_layout.addLayout(accel_grid)
        main_layout.addLayout(zero_grid)

        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

        log_file = f"lc_sps_log_{datetime.date.today().isoformat()}.csv"
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.sps_log_path = os.path.join(base_dir, "..", "Database", log_file)
        with open(self.sps_log_path, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["Timestamp", "LC_SPS", "Accel_SPS"])

    # def show_moment_map_window(self):
    #     self.moment_map_window.show()
    #     self.moment_map_window.raise_()
    #     self.moment_map_window.activateWindow()

    def show_export_data_window(self):
        self.export_data_window.show()
        self.export_data_window.raise_()
        self.export_data_window.activateWindow()

    def show_plot_window(self):
        self.plot_window.show()

    def zero_loads(self):
        print("Zeroing loads...")
        if self.socket_thread:
            self.socket_thread.zero_loads()

    def zero_accels(self):
        if self.socket_thread:
            self.socket_thread.zero_accels()

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
            self.socket_thread.stop()
            self.socket_thread = None
            self.connect_btn.setText("Connect")
            self.update_led("red")
        else:
            ip = self.ip_input.text().strip()
            if not ip:
                return
            self.update_led("yellow")
            self.socket_thread = TeensySocketThread(ip, 5000, self.signal_emitter)
            self.socket_thread.start()
            self.connect_btn.setText("Disconnect")
            self.update_led("green")

    def update_accel_led(self, color):
        palette = self.accel_led.palette()
        palette.setColor(QPalette.Window, QColor(color))
        self.accel_led.setAutoFillBackground(True)
        self.accel_led.setPalette(palette)

    def update_display(self, timestamp, loads, accels, accel_on, accel_status):
        axis_map = {
            "LC1": "Z", "LC2": "Y", "LC3": "Z",
            "LC4": "Y", "LC5": "Z", "LC6": "X",
        }

        for i, lc in enumerate(["LC1", "LC2", "LC3", "LC4", "LC5", "LC6"]):
            axis = axis_map[lc]
            force_val = loads[i]
            self.labels[lc].setText(f"{lc}:\n {format_force(force_val, axis)}")

        # Acceleration LED status
            accel_color = "green" if accel_on else "red"
            self.update_accel_led(accel_color)

            # Acceleration display
            if accel_on:
                self.accel_title.setText("Acceleration (g)")
                for i, axis in enumerate(["X", "Y", "Z"]):
                    self.accel_labels[axis].setText(f"{axis}: {accels[i]:+.2f} g")
            else:
                self.accel_title.setText("Acceleration (Unavailable)")
                for axis in ["X", "Y", "Z"]:
                    self.accel_labels[axis].setText(f"{axis}: ---")

        force_map = {
            "Fx": ([5], "X"),
            "Fy": ([1, 3], "Y"),
            "Fz": ([0, 2, 4], "Z")
        }

        moment_map_forces = {}
        total_force = 0

        for label_key, (indices, axis_for_arrow) in force_map.items():
            vals = [loads[i] for i in indices]
            net_force = sum(vals)
            total_force += abs(net_force)  # or net_force if you want algebraic sum
            self.net_force_labels[label_key].setText(f"{label_key}: {format_force(net_force, axis_for_arrow)} lbf")
            moment_map_forces[label_key] = vals

        self.total_force_label.setText(f"Total: {total_force:.1f} lbf")

        # # Update moment map
        # if self.moment_map_window and self.moment_map_window.isVisible():
        #     self.moment_map_window.update_forces(
        #         moment_map_forces["Fx"],
        #         moment_map_forces["Fy"],
        #         moment_map_forces["Fz"]
        #     )


    def update_sps_display(self, lc_sps, accel_sps):
        self.lc_sps_label.setText(f"LC SPS: {lc_sps}")
        self.accel_sps_label.setText(f"Accel SPS: {accel_sps}")

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.sps_log_path, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([now, lc_sps, accel_sps])

    def closeEvent(self, event):
        if self.socket_thread and self.socket_thread.isRunning():
            print("🛑 Window closed — stopping socket thread...")
            self.socket_thread.stop()
        event.accept()

