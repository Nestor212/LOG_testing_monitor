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
    QCheckBox, QComboBox, QDateTimeEdit, QLineEdit, QGridLayout
)
from PyQt5.QtCore import QDateTime, QTimer, QThread
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas, NavigationToolbar2QT as NavigationToolbar
from ui.sql_worker import SqlWorker

import matplotlib.ticker as ticker

def format_msec(x, pos=None):
    dt = mdates.num2date(x)
    return dt.strftime("%H:%M:%S.") + f"{int(dt.microsecond/10000):02d}"

class PlotWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Load Cell Plotter")
        self.resize(1000, 800)

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

        self.wheel_type_selector = QComboBox()
        self.wheel_type_selector.addItems(["60/40", "120"])

        self.depth_input = QLineEdit("0.0")
        self.feed_rate_input = QLineEdit("0.0")
        self.pitch_input = QLineEdit("0.0")

        params_layout = QHBoxLayout()
        params_layout.addWidget(QLabel("Plot:"))
        params_layout.addWidget(self.plot_data_selector)
        params_layout.addWidget(QLabel("Mode:"))
        params_layout.addWidget(self.plot_mode_selector)
        params_layout.addWidget(QLabel("Smooth:"))
        params_layout.addWidget(self.smoothing_selector)
        params_layout.addWidget(QLabel("Wheel:"))
        params_layout.addWidget(self.wheel_type_selector)
        params_layout.addWidget(QLabel("Depth (mm):"))
        params_layout.addWidget(self.depth_input)
        params_layout.addWidget(QLabel("Feed (mm/s):"))
        params_layout.addWidget(self.feed_rate_input)
        params_layout.addWidget(QLabel("Pitch (mm):"))
        params_layout.addWidget(self.pitch_input)

        self.live_checkbox = QCheckBox("Live")
        self.live_checkbox.setChecked(True)
        self.live_checkbox.toggled.connect(self.toggle_live_mode)

        self.start_live_from_past_checkbox = QCheckBox("Start from history")
        self.start_live_from_past_checkbox.setChecked(False)
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
        layout.addLayout(params_layout)
        layout.addLayout(live_control_layout)
        layout.addLayout(hist_control_layout)
        layout.addWidget(self.canvas)
        layout.insertWidget(0, self.toolbar)
        self.setLayout(layout)

        self.toggle_live_mode(self.live_mode)

    def rebuild_plot_layout(self, plot_data, mode_number):
        self.canvas.figure.clf()

        if plot_data == "Fx/Fy/Fz vs Time":
            labels = ["Fx", "Fy", "Fz"]
        elif plot_data == "Mx/My/Mz vs Time":
            labels = ["Mx", "My"]
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
            self.ax.set_ylabel("Force/Moment")
            self.ax.legend(fontsize=7)
            self.ax.grid(True)
        else:
            self.axes = self.canvas.figure.subplots(nrows=len(labels), sharex=True)
            if len(labels) == 1:
                self.axes = [self.axes]
            self.ax = None
            self.individual_lines = []

        self.canvas.draw()

    def compute_moments(self):
        """
        Compute Mx, My, and Mz using force data and load cell positions.
        Positive directions:
            - Fx: right (LC6)
            - Fy: down (LC2, LC4)
            - Fz: down (LC1, LC3, LC5)
            - Mx: about X axis (rotation in Y-Z plane)
            - My: about Y axis (rotation in X-Z plane)
            - Mz: about Z axis (rotation in X-Y plane)
        """
        positions = {
            0: (-13, -7),  # LC1 (Fz)
            1: (-10,  4),  # LC2 (Fy)
            2: (0,    7),  # LC3 (Fz)
            3: (10,   4),  # LC4 (Fy)
            4: (13,  -7),  # LC5 (Fz)
            5: (0,    0),  # LC6 (Fx)
        }

        n = len(self.x_data)

        # Mx: from Fy at x-offsets (LC2, LC4)
        moment_x = [
            self.y_data[1][j] * positions[1][0] +  # LC2
            self.y_data[3][j] * positions[3][0]    # LC4
            for j in range(n)
        ]

        # My: from Fz at y-offsets (LC1, LC5)
        moment_y = [
            self.y_data[0][j] * positions[0][1] +  # LC1
            self.y_data[4][j] * positions[4][1]    # LC5
            for j in range(n)
        ]

        # Mz: cross product from Fy × x (LC2, LC4)
        moment_z = [
            self.y_data[1][j] * positions[1][0] +  # LC2
            self.y_data[3][j] * positions[3][0]    # LC4
            for j in range(n)
        ]

        return moment_x, moment_y, moment_z


    def refresh_plot(self):
        plot_data = self.plot_data_selector.currentText()
        plot_mode = self.plot_mode_selector.currentText()
        smoothing_n = int(self.smoothing_selector.currentText().split()[0])

        # Determine which data to plot
        if plot_data == "Fx/Fy/Fz vs Time":
            data_indices = {
                "Fx": [5],        # LC6 (X)
                "Fy": [1, 3],     # LC2, LC4 (Y)
                "Fz": [0, 2, 4]   # LC1, LC3, LC5 (Z)
            }
            labels = ["Fx", "Fy", "Fz"]
        elif plot_data == "Mx/My/Mz vs Time":
            labels = ["Mx", "My", "Mz"]
        elif plot_data == "All Load Cells (F1–F6) vs Time":
            data_indices = {f"F{i+1}": [i] for i in range(6)}
            labels = list(data_indices.keys())
        elif plot_data == "Axial Loads (Z: F1, F3, F5) vs Time":
            data_indices = {"F1": [0], "F3": [2], "F5": [4]}
            labels = list(data_indices.keys())
        elif plot_data == "Lateral Loads (Y: F2, F4) vs Time":
            data_indices = {"F2": [1], "F4": [3]}
            labels = list(data_indices.keys())
        elif plot_data == "F6 (X) vs Time":
            data_indices = {"F6": [5]}
            labels = ["F6"]
        else:
            print("⚠ Unknown plot type")
            return

        mode_number = 1 if plot_mode == "Single Plot" else 2

        if getattr(self, 'current_mode', None) != (plot_data, mode_number):
            self.rebuild_plot_layout(plot_data, mode_number)
            self.current_mode = (plot_data, mode_number)

        def smooth(data, n):
            if n <= 1 or len(data) < n:
                return data
            return [sum(data[i:i+n])/n for i in range(len(data)-n+1)]

        time_data = list(self.x_data)
        if smoothing_n > 1:
            time_data = time_data[smoothing_n-1:]

        if plot_data == "Mx/My/Mz vs Time":
            labels = ["Mx", "My", "Mz"]
            moment_x, moment_y, moment_z = self.compute_moments()

            moment_x = smooth(moment_x, smoothing_n)
            moment_y = smooth(moment_y, smoothing_n)
            moment_z = smooth(moment_z, smoothing_n)

            if mode_number == 1:
                self.individual_lines[0].set_data(time_data, moment_x)
                self.individual_lines[1].set_data(time_data, moment_y)
                self.individual_lines[2].set_data(time_data, moment_z)

                self.ax.relim()
                self.ax.autoscale_view()
                self.ax.set_xlabel("Time")
                self.ax.set_ylabel("Moment (lbf-in)")
                self.ax.legend(["Mx", "My", "Mz"])
                self.ax.grid(True)
                self.ax.xaxis.set_major_formatter(ticker.FuncFormatter(format_msec))
            else:
                self.axes[0].clear()
                self.axes[0].plot(time_data, moment_x, label="Mx")
                self.axes[0].set_ylabel("Mx")
                self.axes[0].legend(fontsize=7)
                self.axes[0].grid(True)

                self.axes[1].clear()
                self.axes[1].plot(time_data, moment_y, label="My")
                self.axes[1].set_ylabel("My")
                self.axes[1].legend(fontsize=7)
                self.axes[1].grid(True)

                self.axes[2].clear()
                self.axes[2].plot(time_data, moment_z, label="Mz")
                self.axes[2].set_ylabel("Mz")
                self.axes[2].legend(fontsize=7)
                self.axes[2].grid(True)

                self.axes[-1].set_xlabel("Time")
                self.axes[-1].xaxis.set_major_formatter(ticker.FuncFormatter(format_msec))

        else:
            for i, label in enumerate(labels):
                indices = data_indices[label]
                vals = [sum(self.y_data[k][j] for k in indices) for j in range(len(self.x_data))]
                vals = smooth(vals, smoothing_n)

                if mode_number == 1:
                    self.individual_lines[i].set_data(time_data, vals)
                else:
                    ax = self.axes[i]
                    ax.clear()
                    ax.plot(time_data, vals, label=label)
                    ax.set_ylabel(label)
                    ax.legend(fontsize=7)
                    ax.grid(True)

            if mode_number == 1:
                self.ax.relim()
                self.ax.autoscale_view()
                self.ax.set_xlabel("Time")
                self.ax.set_ylabel("Force")
                self.ax.legend([line.get_label() for line in self.individual_lines[:len(labels)]])
                self.ax.grid(True)
                self.ax.xaxis.set_major_formatter(ticker.FuncFormatter(format_msec))
            else:
                self.axes[-1].set_xlabel("Time")
                self.axes[-1].xaxis.set_major_formatter(ticker.FuncFormatter(format_msec))

        self.canvas.figure.autofmt_xdate()
        self.canvas.draw()


    def toggle_live_mode(self, checked):
        self.live_mode = checked

        # Controls related to live plotting
        self.window_selector.setEnabled(checked)
        self.start_btn.setEnabled(checked)
        self.live_checkbox.setChecked(checked)
        self.start_live_from_past_checkbox.setEnabled(checked)

        # Controls related to historical plotting
        self.plot_button.setEnabled(not checked)
        self.start_time_edit.setEnabled(not checked or self.start_live_from_past_checkbox.isChecked())
        self.end_time_edit.setEnabled(not checked)
        self.averaging_selector.setEnabled(not checked)

        if not checked:
            self.live_timer.stop()
            self.start_btn.setText("Start")


    def toggle_live_history(self, checked):
        # Only matters if we're in live mode
        if self.live_mode:
            self.start_time_edit.setEnabled(checked)
            self.window_selector.setEnabled(not checked)

    def update_live_window(self, text):
        mapping = {
            "1 min": 1,
            "10 min": 10,
            "1 hr": 60,
            "5 hr": 300,
            "12 hr": 720
        }
        self.live_window_minutes = mapping.get(text, 10)
        self.max_live_points = self.live_window_minutes * 60 * 4  # 4 Hz

    def toggle_live_plotting(self):
        if self.live_timer.isActive():
            self.live_timer.stop()
            self.start_btn.setText("Start")
            self.window_selector.setEnabled(True)
            return

        self.appending_live_data = False  # Default to reset mode

        if self.start_live_from_past_checkbox.isChecked():
            # Start from past — fetch history first
            start_dt = self.start_time_edit.dateTime().toPyDateTime()
            end_dt = datetime.datetime.now()
            avg_n = int(self.smoothing_selector.currentText().split()[0])
            self.appending_live_data = True  # Enable appending mode
            self.worker.query_range(start_dt, end_dt, avg_n)
        else:
            # Start fresh
            self.x_data.clear()
            self.y_data = [collections.deque() for _ in range(6)]

        self.live_timer.start()
        self.start_btn.setText("Stop")
        self.window_selector.setEnabled(False)

    def request_latest_live_point(self):
        avg_n = int(self.smoothing_selector.currentText().split()[0])
        self.worker.query_last_n_samples(avg_n)

    def on_live_point_ready(self, dt, values):
        self.x_data.append(dt)
        for i in range(6):
            self.y_data[i].append(values[i])

        # if self.moment_widget:
        #     fx_vals = [self.y_data[5][-1]] if self.y_data[5] else [0]
        #     fy_vals = [self.y_data[1][-1], self.y_data[3][-1]] if self.y_data[1] and self.y_data[3] else [0, 0]
        #     fz_vals = [self.y_data[0][-1], self.y_data[2][-1], self.y_data[4][-1]] if self.y_data[0] and self.y_data[2] and self.y_data[4] else [0, 0, 0]
        #     self.moment_widget.update_forces(fx_vals, fy_vals, fz_vals)

        # Trim to max visible live window
        while len(self.x_data) > self.max_live_points:
            self.x_data.popleft()
            for i in range(6):
                self.y_data[i].popleft()

        self.refresh_plot()

    def plot_historical(self):
        start_dt = self.start_time_edit.dateTime().toPyDateTime()
        end_dt = self.end_time_edit.dateTime().toPyDateTime()
        avg_n = int(self.averaging_selector.currentText().split()[0])
        self.worker.query_range(start_dt, end_dt, avg_n)

    def on_data_ready(self, data):
        if not self.appending_live_data:
            self.x_data.clear()
            self.y_data = [collections.deque() for _ in range(6)]

        for dt, loads in data:
            self.x_data.append(dt)
            for i in range(6):
                self.y_data[i].append(loads[i])

        print(f"[PlotWindow] Loaded {len(data)} historical points")
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
            print(f"Clicked near: {self.x_data[nearest_index]} -> {y_vals}")

    def hideEvent(self, event):
        print("[PlotWindow] Window hidden — live timer paused.")
        if self.live_timer.isActive():
            self.live_timer.stop()
            self.start_btn.setText("Start")
            self.live_checkbox.setEnabled(True)
            self.window_selector.setEnabled(True)
        event.accept()

    def closeEvent(self, event):
        print("[PlotWindow] Window closed — stopping worker thread and live timer.")
        if self.live_timer.isActive():
            self.live_timer.stop()
        self.worker_thread.quit()
        self.worker_thread.wait()
        event.accept()
