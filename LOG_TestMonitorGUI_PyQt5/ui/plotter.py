# y = 8
# -----------------------------------
# | lc2          lc3            lc4 |
# |  y            z              y  |
# |                                 |
# |              lc6                |
# |               x                 |
# |                                 |
# |                                 |
# | lc1                         lc5 |
# |  z                           z  |
# -----------------------------------
# x = 0                         x = 16
# y = 0

import collections
import matplotlib.dates as mdates
import datetime

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QCheckBox, QComboBox, QDateTimeEdit, QLineEdit, QDialog,
    QGridLayout
)
from PyQt5.QtCore import QDateTime, QTimer, QThread
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas, NavigationToolbar2QT as NavigationToolbar
from ui.sql_worker import SqlWorker
from comms.parser_emitter import ParserEmitter
from ui.edit_params_dialog import EditParamsDialog
from Database.db import get_connection

import matplotlib.ticker as ticker
import time

def format_msec(x, pos=None):
    dt = mdates.num2date(x)
    return dt.strftime("%H:%M:%S.") + f"{int(dt.microsecond/10000):02d}"

class PlotWindow(QWidget):
    def __init__(self, emitter: ParserEmitter):
        super().__init__()
        self.setWindowTitle("Load Cell Plotter")
        self.resize(1000, 800)

        self.trigger_emitter = emitter
        self.trigger_emitter.trigger_started.connect(self.load_pretrigger_plot_data)
        self.appending_live_data = False

        self.x_data = collections.deque()
        self.y_data = [collections.deque() for _ in range(6)]

        self.canvas = FigureCanvas(Figure(figsize=(6, 10)))
        self.toolbar = NavigationToolbar(self.canvas, self)

        self.ax = self.canvas.figure.add_subplot(111)
        self.axis_labels = ["Z", "Y", "Z", "Y", "Z", "X"]
        self.individual_lines = [self.ax.plot([], [], label=f"LC{i+1} ({self.axis_labels[i]})")[0] for i in range(6)]
        self.net_lines = [self.ax.plot([], [], label=lbl)[0] for lbl in ["Net X", "Net Y", "Net Z"]]
        self.ax.set_xlabel("Time", fontsize=9)
        self.ax.set_ylabel("Load", fontsize=8)
        self.ax.legend(fontsize=7)
        self.ax.grid(True)
        self.ax.tick_params(labelsize=8)
        self.ax.xaxis.set_major_formatter(ticker.FuncFormatter(format_msec))
        self.canvas.figure.autofmt_xdate()

        self.live_timer = QTimer()
        self.live_timer.setInterval(500)
        self.live_timer.timeout.connect(self.request_latest_live_point)
        self.live_mode = True
        self.live_window_minutes = 1
        self.max_live_points = self.live_window_minutes * 60 * 2 

        self.worker_thread = QThread()
        self.worker = SqlWorker()
        self.worker.moveToThread(self.worker_thread)
        self.worker.data_ready.connect(self.on_data_ready)
        self.worker.single_point_ready.connect(self.on_live_point_ready)
        self.worker.error.connect(self.on_error)
        self.worker_thread.start()

        # --- New UI controls ---
        self.plot_data_selector = QComboBox()
        self.plot_data_selector.addItems([
            "Fx/Fy/Fz vs Time",
            "Mx/My/Mz vs Time",
            "All Load Cells (F1–F6) vs Time",
            "Axial Loads (Z: F1, F3, F5) vs Time",
            "Lateral Loads (Y: F2, F4) vs Time",
            "F6 (X) vs Time"
        ])
        self.plot_data_selector.currentIndexChanged.connect(lambda _: self.refresh_plot())

        self.plot_mode_selector = QComboBox()
        self.plot_mode_selector.addItems(["Single Plot", "Subplots"])
        self.plot_mode_selector.setCurrentIndex(0)
        self.plot_mode_selector.currentIndexChanged.connect(lambda _: self.refresh_plot())

        self.smoothing_selector = QComboBox()
        self.smoothing_selector.addItems(["1 (Raw)", "4", "16", "32", "64"])
        self.smoothing_selector.setCurrentIndex(0)
        self.smoothing_selector.currentTextChanged.connect(self.update_parameters)

        # Display-only labels for parameters
        self.wheel_label = QLabel("Wheel: 60/40")
        self.depth_label = QLabel("Depth (mm): 0.0")
        self.feed_label = QLabel("Feed (mm/s): 0.0")
        self.pitch_label = QLabel("Pitch (mm): 0.0")

        # Edit button
        self.edit_params_btn = QPushButton("Edit")
        self.edit_params_btn.clicked.connect(self.open_param_editor)

        self.wheel_type_selector = QComboBox()
        self.wheel_type_selector.addItems(["60/40", "120"])

        self.depth_input = QLineEdit("0.0")
        self.feed_rate_input = QLineEdit("0.0")
        self.pitch_input = QLineEdit("0.0")

        params_layout = QHBoxLayout()
        params_layout.addWidget(self.wheel_label)
        params_layout.addWidget(self.depth_label)
        params_layout.addWidget(self.feed_label)
        params_layout.addWidget(self.pitch_label)
        params_layout.addWidget(self.edit_params_btn)

        self.live_checkbox = QCheckBox("Live")
        self.live_checkbox.setChecked(True)
        self.live_checkbox.toggled.connect(self.toggle_live_mode)

        self.start_live_from_past_checkbox = QCheckBox("Start from history")
        self.start_live_from_past_checkbox.setChecked(False)
        self.start_live_from_past_checkbox.setEnabled(False)
        self.start_live_from_past_checkbox.toggled.connect(self.toggle_live_history)

        self.window_selector = QComboBox()
        self.window_selector.addItems(["1 min", "10 min", "1 hr", "5 hr", "12 hr"])
        self.window_selector.currentTextChanged.connect(self.update_live_window)

        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self.toggle_live_plotting)

        live_control_layout = QHBoxLayout()
        live_control_layout.addWidget(self.live_checkbox)
        live_control_layout.addWidget(self.start_live_from_past_checkbox)
        live_control_layout.addWidget(QLabel("Window:"))
        live_control_layout.addWidget(self.window_selector)
        live_control_layout.addWidget(QLabel("Plot:"))
        live_control_layout.addWidget(self.plot_data_selector)
        live_control_layout.addWidget(QLabel("Mode:"))
        live_control_layout.addWidget(self.plot_mode_selector)
        live_control_layout.addWidget(QLabel("Smooth:"))
        live_control_layout.addWidget(self.smoothing_selector)
        live_control_layout.addWidget(self.start_btn)
        live_control_layout.addStretch()

        self.start_time_edit = QDateTimeEdit(QDateTime.currentDateTime().addSecs(-600))
        self.start_time_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.start_time_edit.setCalendarPopup(True)

        self.end_time_edit = QDateTimeEdit(QDateTime.currentDateTime())
        self.end_time_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.end_time_edit.setCalendarPopup(True)

        self.averaging_selector = QComboBox()
        self.averaging_selector.addItems(["1 (64 Hz)", "4 (16 Hz)", "16 (4 Hz)", "32 (2 Hz)", "64 (1 Hz)"])

        self.plot_button = QPushButton("Plot")
        self.plot_button.clicked.connect(self.plot_historical)

        hist_control_layout = QHBoxLayout()
        hist_control_layout.addWidget(QLabel("Start:"))
        hist_control_layout.addWidget(self.start_time_edit)
        hist_control_layout.addWidget(QLabel("End:"))
        hist_control_layout.addWidget(self.end_time_edit)
        hist_control_layout.addWidget(QLabel("Average:"))
        hist_control_layout.addWidget(self.averaging_selector)
        hist_control_layout.addWidget(self.plot_button)
        hist_control_layout.addStretch()

        layout = QVBoxLayout()
        layout.addLayout(live_control_layout)
        layout.addLayout(hist_control_layout)
        layout.addLayout(params_layout)
        layout.addWidget(self.canvas)
        layout.insertWidget(0, self.toolbar)
        self.setLayout(layout)

        self.toggle_live_mode(self.live_mode)
        self.catch_up_mode = False

    def update_parameters(self):
        self.update_plot_timer_interval()
        self.update_live_window()

    def open_param_editor(self):
        current = {
            "wheel": self.wheel_label.text().split(": ")[1],
            "depth": float(self.depth_label.text().split(": ")[1]),
            "feed": float(self.feed_label.text().split(": ")[1]),
            "pitch": float(self.pitch_label.text().split(": ")[1]),
        }

        dlg = EditParamsDialog(current, self)
        if dlg.exec_() == QDialog.Accepted:
            params = dlg.get_params()
            self.wheel_label.setText(f"Wheel: {params['wheel']}")
            self.depth_label.setText(f"Depth (mm): {params['depth']}")
            self.feed_label.setText(f"Feed (mm/s): {params['feed']}")
            self.pitch_label.setText(f"Pitch (mm): {params['pitch']}")

            # Prepare DB insert
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

            conn = get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO log_config (
                    timestamp, wheel_type, depth, feed_rate, pitch
                ) VALUES (?, ?, ?, ?, ?)
                """, 
                (
                now,
                params['wheel'],
                params['depth'],
                params['feed'],
                params['pitch']
                )
            )
            conn.commit()
            conn.close()

    def load_pretrigger_plot_data(self, trigger_time):
        print(f"🔄 Trigger received at {trigger_time} — loading pre-trigger data...")
        pre_time = trigger_time - datetime.timedelta(seconds=10)
        avg_n = int(self.smoothing_selector.currentText().split()[0])

        self.appending_live_data = False  # 🚫 Block appending until preload finishes
        self.waiting_for_pretrigger_plot = True
        time.sleep(0.2)  # Give UI a moment to update
        self.worker.query_range(pre_time, trigger_time, avg_n)

    def update_plot_timer_interval(self):
        smoothing_n = int(self.smoothing_selector.currentText().split()[0])

        if smoothing_n <= 32:
            interval = 500
        else:
            interval = 1000

        self.live_timer.setInterval(interval)

    def rebuild_plot_layout(self, plot_data, mode_number):
        self.canvas.figure.clf()
        y_label = "Force (lbf)"

        if plot_data == "Fx/Fy/Fz vs Time":
            labels = ["Fx", "Fy", "Fz"]
        elif plot_data == "Mx/My/Mz vs Time":
            labels = ["Mx", "My", "Mz"]
            y_label = "Moment (lbf-in)"
        elif plot_data == "All Load Cells (F1–F6) vs Time":
            labels = [f"F{i+1}" for i in range(6)]
        elif plot_data == "Axial Loads (Z: F1, F3, F5) vs Time":
            labels = ["F1", "F3", "F5"]
        elif plot_data == "Lateral Loads (Y: F2, F4) vs Time":
            labels = ["F2", "F4"]
        elif plot_data == "F6 (X) vs Time":
            labels = ["F6"]
        else:
            labels = []

        if mode_number == 1:
            self.ax = self.canvas.figure.add_subplot(111)
            self.axes = [self.ax]
            self.individual_lines = [
                self.ax.plot([], [], label=label)[0] for label in labels
            ]
            self.ax.set_xlabel("Time")
            self.ax.set_ylabel(y_label)
            self.ax.legend(fontsize=7)
            self.ax.grid(True)
        else:
            self.axes = self.canvas.figure.subplots(nrows=len(labels), sharex=True)
            if len(labels) == 1:
                self.axes = [self.axes]
            self.ax = None
            self.individual_lines = []

        self.canvas.draw()
        
    def check_lag_and_throttle(self):
        latest_time = self.x_data[-1]
        now = datetime.datetime.now()
        lag_sec = (now - latest_time).total_seconds()

        if lag_sec > 1.5:
            if not self.catch_up_mode:
                print(f"⚠️ Lag: {lag_sec:.2f}s behind. Slowing refresh.")
                self.catch_up_mode = True
                self.live_timer.setInterval(1000)
        else:
            if self.catch_up_mode:
                print("✅ Caught up. Restoring normal refresh.")
                self.catch_up_mode = False
                self.update_plot_timer_interval()

    def compute_moments(self):
        """
        Compute Mx, My, and Mz using corrected load cell positions and forces.
        Positive directions:
            - Fx: right (LC6)
            - Fy: down (LC2, LC4)
            - Fz: down (LC1, LC3, LC5)
            - Mx: rotation about X (Y-Z plane)
            - My: rotation about Y (X-Z plane)
            - Mz: rotation about Z (X-Y plane)
        """

        # Positions in mm from origin at LC6 (converted to inches for moment units in lbf-in)
        mm_to_in = 1 / 25.4
        positions = {
            0: (-330 * mm_to_in, 181 * mm_to_in),  # LC1 (Fz) 
            2: (0,            -181 * mm_to_in),    # LC3 (Fz)
            4: (330 * mm_to_in, 181 * mm_to_in),   # LC5 (Fz)
            1: (-257 * mm_to_in, -187 * mm_to_in), # LC2 (Fy)
            3: (257 * mm_to_in, -187 * mm_to_in),  # LC4 (Fy)
        }

        n = len(self.x_data)

        # Forces for LC1, LC3, LC5 (Z-direction): compute Mx and My
        moment_x = [
            self.y_data[0][j] * positions[0][1] +  # F1 * y1
            self.y_data[2][j] * positions[2][1] +  # F3 * y3
            self.y_data[4][j] * positions[4][1]    # F5 * y5
            for j in range(n)
        ]

        moment_y = [
            -self.y_data[0][j] * positions[0][0] -  # -F1 * x1
            self.y_data[2][j] * positions[2][0] -  # -F3 * x3 (which is 0)
            self.y_data[4][j] * positions[4][0]     # -F5 * x5
            for j in range(n)
        ]

        # Forces for LC2 and LC4 (Y-direction): compute Mz
        moment_z = [
            self.y_data[1][j] * positions[1][0] +  # F2 * x2
            self.y_data[3][j] * positions[3][0]    # F4 * x4
            for j in range(n)
        ]

        return moment_x, moment_y, moment_z

    def prepare_force_data(self):
        plot_data = self.plot_data_selector.currentText()

        if plot_data == "Fx/Fy/Fz vs Time":
            data_indices = {"Fx": [5], "Fy": [1, 3], "Fz": [0, 2, 4]}
        elif plot_data == "All Load Cells (F1–F6) vs Time":
            data_indices = {f"F{i+1}": [i] for i in range(6)}
        elif plot_data == "Axial Loads (Z: F1, F3, F5) vs Time":
            data_indices = {"F1": [0], "F3": [2], "F5": [4]}
        elif plot_data == "Lateral Loads (Y: F2, F4) vs Time":
            data_indices = {"F2": [1], "F4": [3]}
        elif plot_data == "F6 (X) vs Time":
            data_indices = {"F6": [5]}
        else:
            print("⚠️ Unknown plot type")
            return [], []

        labels = list(data_indices.keys())
        data_series = [
            [sum(self.y_data[k][j] for k in data_indices[label]) for j in range(len(self.x_data))]
            for label in labels
        ]

        return data_series, labels
    
    def update_lines(self, time_data, data_series, labels):
        if len(self.individual_lines) != len(labels):
            print("⚠️ Mismatch detected. Removing old lines and rebuilding.")
            for line in self.individual_lines:
                line.remove()
            self.individual_lines.clear()
            self.ax.set_prop_cycle(None) # Reset color cycle

            self.individual_lines = [
                self.ax.plot([], [], label=label)[0] for label in labels
            ]

        for i, data in enumerate(data_series):
            self.individual_lines[i].set_data(time_data, data)
            self.individual_lines[i].set_label(labels[i])

    def update_subplots(self, time_data, data_series, labels):
        for i, data in enumerate(data_series):
            ax = self.axes[i]
            ax.clear()
            ax.plot(time_data, data, label=labels[i])
            ax.set_ylabel(labels[i])
            ax.legend(fontsize=7)
            ax.grid(True)

    def handle_axes_formatting(self, labels, mode, y_label):
        if mode == "Single Plot":
            self.ax.relim()
            self.ax.autoscale_view()
            self.ax.legend([line.get_label() for line in self.individual_lines[:len(labels)]])
            self.ax.set_xlabel("Time")
            self.ax.set_ylabel(y_label)
            self.ax.grid(True)
            self.ax.xaxis.set_major_formatter(ticker.FuncFormatter(format_msec))
        else:
            self.axes[-1].set_xlabel("Time")
            self.axes[-1].xaxis.set_major_formatter(ticker.FuncFormatter(format_msec))

        self.canvas.figure.autofmt_xdate()

    def refresh_plot(self):
        if not self.x_data:
            return

        y_label = "Force (lbf)"
        time_data = list(self.x_data)

        self.check_lag_and_throttle()

        plot_data = self.plot_data_selector.currentText()
        plot_mode = self.plot_mode_selector.currentText()

        if plot_data == "Mx/My/Mz vs Time":
            moment_x, moment_y, moment_z = self.compute_moments()
            data_series = [moment_x, moment_y, moment_z]
            labels = ["Mx", "My", "Mz"]
            y_label = "Moment (lbf-in)"
        else:
            data_series, labels = self.prepare_force_data()

        if plot_mode == "Single Plot":
            self.update_lines(time_data, data_series, labels)
        else:
            self.update_subplots(time_data, data_series, labels)

        self.handle_axes_formatting(labels, plot_mode, y_label)
        self.canvas.draw()

    # def refresh_plot(self):
    #     plot_data = self.plot_data_selector.currentText()
    #     plot_mode = self.plot_mode_selector.currentText()

    #     # Determine which data to plot
    #     if plot_data == "Fx/Fy/Fz vs Time":
    #         data_indices = {
    #             "Fx": [5],        # LC6 (X)
    #             "Fy": [1, 3],     # LC2, LC4 (Y)
    #             "Fz": [0, 2, 4]   # LC1, LC3, LC5 (Z)
    #         }
    #         labels = ["Fx", "Fy", "Fz"]
    #     elif plot_data == "Mx/My/Mz vs Time":
    #         labels = ["Mx", "My", "Mz"]
    #     elif plot_data == "All Load Cells (F1–F6) vs Time":
    #         data_indices = {f"F{i+1}": [i] for i in range(6)}
    #         labels = list(data_indices.keys())
    #     elif plot_data == "Axial Loads (Z: F1, F3, F5) vs Time":
    #         data_indices = {"F1": [0], "F3": [2], "F5": [4]}
    #         labels = list(data_indices.keys())
    #     elif plot_data == "Lateral Loads (Y: F2, F4) vs Time":
    #         data_indices = {"F2": [1], "F4": [3]}
    #         labels = list(data_indices.keys())
    #     elif plot_data == "F6 (X) vs Time":
    #         data_indices = {"F6": [5]}
    #         labels = ["F6"]
    #     else:
    #         print("⚠ Unknown plot type")
    #         return

    #     mode_number = 1 if plot_mode == "Single Plot" else 2

    #     if getattr(self, 'current_mode', None) != (plot_data, mode_number):
    #         self.rebuild_plot_layout(plot_data, mode_number)
    #         self.current_mode = (plot_data, mode_number)

    #     time_data = list(self.x_data)

    #     if plot_data == "Mx/My/Mz vs Time":
    #         labels = ["Mx", "My", "Mz"]
    #         moment_x, moment_y, moment_z = self.compute_moments()

    #         if mode_number == 1:
    #             self.individual_lines[0].set_data(time_data, moment_x)
    #             self.individual_lines[1].set_data(time_data, moment_y)
    #             self.individual_lines[2].set_data(time_data, moment_z)

    #             self.ax.relim()
    #             self.ax.autoscale_view()
    #             self.ax.set_xlabel("Time")
    #             self.ax.set_ylabel("Moment (lbf-in)")
    #             self.ax.legend(["Mx", "My", "Mz"])
    #             self.ax.grid(True)
    #             self.ax.xaxis.set_major_formatter(ticker.FuncFormatter(format_msec))
    #         else:
    #             self.axes[0].clear()
    #             self.axes[0].plot(time_data, moment_x, label="Mx")
    #             self.axes[0].set_ylabel("Mx")
    #             self.axes[0].legend(fontsize=7)
    #             self.axes[0].grid(True)

    #             self.axes[1].clear()
    #             self.axes[1].plot(time_data, moment_y, label="My")
    #             self.axes[1].set_ylabel("My")
    #             self.axes[1].legend(fontsize=7)
    #             self.axes[1].grid(True)

    #             self.axes[2].clear()
    #             self.axes[2].plot(time_data, moment_z, label="Mz")
    #             self.axes[2].set_ylabel("Mz")
    #             self.axes[2].legend(fontsize=7)
    #             self.axes[2].grid(True)

    #             self.axes[-1].set_xlabel("Time")
    #             self.axes[-1].xaxis.set_major_formatter(ticker.FuncFormatter(format_msec))

    #     else:
    #         for i, label in enumerate(labels):
    #             indices = data_indices[label]
    #             vals = [sum(self.y_data[k][j] for k in indices) for j in range(len(self.x_data))]
    #             # vals = smooth(vals, smoothing_n)

    #             if mode_number == 1:
    #                 self.individual_lines[i].set_data(time_data, vals)
    #             else:
    #                 ax = self.axes[i]
    #                 ax.clear()
    #                 ax.plot(time_data, vals, label=label)
    #                 ax.set_ylabel(label)
    #                 ax.legend(fontsize=7)
    #                 ax.grid(True)

    #         if mode_number == 1:
    #             self.ax.relim()
    #             self.ax.autoscale_view()
    #             self.ax.set_xlabel("Time")
    #             self.ax.set_ylabel("Force")
    #             self.ax.legend([line.get_label() for line in self.individual_lines[:len(labels)]])
    #             self.ax.grid(True)
    #             self.ax.xaxis.set_major_formatter(ticker.FuncFormatter(format_msec))
    #         else:
    #             self.axes[-1].set_xlabel("Time")
    #             self.axes[-1].xaxis.set_major_formatter(ticker.FuncFormatter(format_msec))

    #     self.canvas.figure.autofmt_xdate()
    #     self.canvas.draw()

    def plot_historical(self):
        # Clear plot buffers
        self.x_data.clear()
        self.y_data = [collections.deque() for _ in range(6)]

        # Reset current mode to force layout rebuild
        self.current_mode = None
        plot_data = self.plot_data_selector.currentText()
        mode_number = 1 if self.plot_mode_selector.currentText() == "Single Plot" else 2
        self.rebuild_plot_layout(plot_data, mode_number)

        start_dt = self.start_time_edit.dateTime().toPyDateTime().replace(microsecond=0)
        end_dt = self.end_time_edit.dateTime().toPyDateTime().replace(microsecond=0)
        avg_n = int(self.averaging_selector.currentText().split()[0])
        self.appending_live_data = False  # Disable appending for historical plots
        self.worker.query_range(start_dt, end_dt, avg_n)

    def toggle_live_mode(self, checked):
        self.live_mode = checked

        # Controls related to live plotting
        self.window_selector.setEnabled(checked)
        self.start_btn.setEnabled(checked)
        self.live_checkbox.setChecked(checked)
        self.start_live_from_past_checkbox.setEnabled(False) #Disabled until debugged

        # Controls related to historical plotting
        self.plot_button.setEnabled(not checked)
        self.start_time_edit.setEnabled(not checked or self.start_live_from_past_checkbox.isChecked())
        self.end_time_edit.setEnabled(not checked)
        self.averaging_selector.setEnabled(not checked)

        self.update_plot_timer_interval()

        if not checked:
            self.live_timer.stop()
            self.start_btn.setText("Start")

    def toggle_live_history(self, checked):
        # Only matters if we're in live mode
        if self.live_mode:
            self.start_time_edit.setEnabled(checked)
            self.window_selector.setEnabled(not checked)

    def update_live_window(self):
        selected = self.window_selector.currentText()
        if "min" in selected:
            self.live_window_minutes = int(selected.split()[0])
        elif "hr" in selected:
            self.live_window_minutes = int(selected.split()[0]) * 60
        else:
            self.live_window_minutes = 1  # Default fallback

        avg_n = int(self.smoothing_selector.currentText().split()[0])
        if avg_n <= 16:
            self.max_live_points = self.live_window_minutes * 60 * 4  # 4 Hz
        elif avg_n <= 32:
            self.max_live_points = self.live_window_minutes * 60 * 2
        else:
            self.max_live_points = self.live_window_minutes * 60 * 1

    def toggle_live_plotting(self):
        self.update_parameters()

        if self.live_timer.isActive():
            self.live_timer.stop()
            self.start_btn.setText("Start")
            self.window_selector.setEnabled(True)
            self.plot_mode_selector.setEnabled(True)
            self.smoothing_selector.setEnabled(True)
            self.wheel_type_selector.setEnabled(True)
            self.depth_input.setEnabled(True)
            self.feed_rate_input.setEnabled(True)
            self.pitch_input.setEnabled(True)
            self.start_live_from_past_checkbox.setEnabled(False) #Disabled until debugged
            return
        
        # Clear plot buffers
        self.x_data.clear()
        self.y_data = [collections.deque() for _ in range(6)]

        # Reset current mode to force layout rebuild
        self.current_mode = None
        plot_data = self.plot_data_selector.currentText()
        mode_number = 1 if self.plot_mode_selector.currentText() == "Single Plot" else 2
        self.rebuild_plot_layout(plot_data, mode_number)

        self.appending_live_data = False  # Default to reset mode

        if self.start_live_from_past_checkbox.isChecked():
            # Start from past — fetch history first
            start_dt = self.start_time_edit.dateTime().toPyDateTime()
            end_dt = datetime.datetime.now()
            avg_n = int(self.smoothing_selector.currentText().split()[0])
            self.appending_live_data = True  # Enable appending mode
            self.worker.query_range(start_dt, end_dt, avg_n)
        else:
            # Start fresh live mode
            # self.x_data.clear()
            self.y_data = [collections.deque() for _ in range(6)]
            self.appending_live_data = True  # Enable appending mode for live updates

            # ⚠️ Do not preload any data — pretrigger data will be fetched when trigger fires
            print("🔄 Live mode started — waiting for trigger to fetch pre-trigger data.")

        self.live_timer.start()
        self.start_btn.setText("Stop")
        self.window_selector.setEnabled(False)
        self.wheel_type_selector.setEnabled(False)
        self.depth_input.setEnabled(False)
        self.feed_rate_input.setEnabled(False)
        self.pitch_input.setEnabled(False)
        self.start_live_from_past_checkbox.setEnabled(False)

    def request_latest_live_point(self):
        if getattr(self, 'waiting_for_pretrigger_plot', False):
            print("⏳ Waiting for pre-trigger data, skipping live point request")
            return

        avg_n = int(self.smoothing_selector.currentText().split()[0])
        self.worker.query_last_n_samples(avg_n)

    def on_live_point_ready(self, dt, values):
        # Skip if this is a repeat of the most recent timestamp
        if self.x_data and dt <= self.x_data[-1]:
            return

        self.x_data.append(dt)
        for i in range(6):
            self.y_data[i].append(values[i])

        # Only trim if we're not starting from past data
        if not self.start_live_from_past_checkbox.isChecked():
            while len(self.x_data) > self.max_live_points:
                self.x_data.popleft()
                for i in range(6):
                    self.y_data[i].popleft()

        self.refresh_plot()

    def on_data_ready(self, data):
        """
        Called when historical data (e.g., pre-trigger) is loaded.
        If self.waiting_for_pretrigger_plot is True, this data is pre-trigger and
        appending of live data will start only after this is loaded.

        Three Use cases:
        1. Pre-trigger data loaded: self.waiting_for_pretrigger_plot is True
        2. Historical plot request: self.waiting_for_pretrigger_plot is False
        3. Starting live mode from past: self.waiting_for_pretrigger_plot is False

        In the first case, we wait for the pre-trigger data to load before enabling live appending.
        In the second case, we just load the historical data into the plot buffers.
        In the third case, we also load historical data but then enable live appending.

        In all cases, we clear the plot buffers and load the data for a fresh plot.
        """
        self.x_data.clear()
        self.y_data = [collections.deque() for _ in range(6)]
    
        for dt, loads in data:
            self.x_data.append(dt)
            for i in range(6):
                self.y_data[i].append(loads[i])

        print(f"[PlotWindow] Loaded {len(data)} historical points")

        # ✅ If waiting for pre-trigger plot, now enable live appending
        if getattr(self, 'waiting_for_pretrigger_plot', False):
            self.waiting_for_pretrigger_plot = False
            self.appending_live_data = True
            # print("[PlotWindow] ✅ Pre-trigger data loaded — now accepting live updates")

        if self.start_live_from_past_checkbox.isChecked():
            self.appending_live_data = True

        self.refresh_plot()

    def on_error(self, msg):
        print(f"[SqlWorker] Error: {msg}")

    def connect_plot_events(self):
        self.canvas.mpl_connect("button_press_event", self.on_plot_click)

    def on_plot_click(self, event):
        if event.inaxes and self.x_data:
            click_time = mdates.num2date(event.xdata)
            nearest_index = min(range(len(self.x_data)), key=lambda i: abs(self.x_data[i] - click_time))
            y_vals = [self.y_data[i][nearest_index] for i in range(6)]
            # print(f"Clicked near: {self.x_data[nearest_index]} -> {y_vals}")

    # def hideEvent(self, event):
    #     if self.live_timer.isActive():
    #         print("[PlotWindow] Window hidden — live timer paused.")
    #         self.live_timer.stop()
    #         self.start_btn.setText("Start")
    #         self.live_checkbox.setEnabled(True)
    #         self.window_selector.setEnabled(True)
    #     event.accept()

    def closeEvent(self, event):
        print("[PlotWindow] Window closed.")
        if self.live_timer.isActive():
            self.live_timer.stop()
            print("Live timer stopped.")
        print("Stopping worker thread.")
        self.worker_thread.quit()
        self.worker_thread.wait()
        event.accept()
