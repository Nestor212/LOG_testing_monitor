# y = 8
# -----------------------------------
# | lc5                         lc1 |
# |  z                           z  |
# |              lc6                |
# |               x                  |
# |                                 |
# |                                 |
# |                                 |
# | lc4           lc3           lc2 |
# |  y             z             y  |
# -----------------------------------
# x = 0                         x = 16
# y = 0

import collections
import numpy as np
import matplotlib.dates as mdates

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QCheckBox, QComboBox, QDateTimeEdit
)
from PyQt5.QtCore import QDateTime, QTimer, QThread
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas, NavigationToolbar2QT as NavigationToolbar
from ui.sql_worker import SqlWorker

USE_SUBPLOTS = False

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
        # Map of LC index to axis label
        axis_labels = ["Z", "Y", "Z", "Y", "Z", "X"]

        self.individual_lines = [
            self.ax.plot([], [], label=f"LC{i+1} ({axis_labels[i]})")[0] for i in range(6)
        ]
        self.net_lines = [self.ax.plot([], [], label=lbl)[0] for lbl in ["Net X", "Net Y", "Net Z"]]
        self.ax.set_xlabel("Time", fontsize=9)
        self.ax.set_ylabel("Load", fontsize=8)
        self.ax.legend(fontsize=7)
        self.ax.grid(True)
        self.ax.tick_params(labelsize=8)
        # self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S.%0.2f"))
        self.ax.xaxis.set_major_formatter(ticker.FuncFormatter(format_msec))        
        self.canvas.figure.autofmt_xdate()

        # Controls
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

        self.live_checkbox = QCheckBox("Live")
        self.live_checkbox.setChecked(True)
        self.live_checkbox.toggled.connect(self.toggle_live_mode)

        self.window_selector = QComboBox()
        self.window_selector.addItems(["1 min", "10 min", "1 hr", "5 hr", "12 hr"])
        self.window_selector.currentTextChanged.connect(self.update_live_window)

        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self.toggle_live_plotting)

        self.plot_mode_selector = QComboBox()
        self.plot_mode_selector.addItems(["Individual Load Cells", "Net Forces"])
        self.plot_mode_selector.currentIndexChanged.connect(self.refresh_plot)

        live_control_layout = QHBoxLayout()
        live_control_layout.addWidget(self.live_checkbox)
        live_control_layout.addWidget(QLabel("Window:"))
        live_control_layout.addWidget(self.window_selector)
        live_control_layout.addWidget(self.start_btn)
        live_control_layout.addWidget(QLabel("Plot Mode:"))
        live_control_layout.addWidget(self.plot_mode_selector)
        live_control_layout.addStretch()

        self.start_time_edit = QDateTimeEdit(QDateTime.currentDateTime().addSecs(-600))
        self.start_time_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.start_time_edit.setCalendarPopup(True)

        self.end_time_edit = QDateTimeEdit(QDateTime.currentDateTime())
        self.end_time_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.end_time_edit.setCalendarPopup(True)

        self.averaging_selector = QComboBox()
        self.averaging_selector.addItems(["1 (64 Hz)", "2 (32 Hz)", "4 (16 Hz)", "8 (8 Hz)", "16 (4 Hz)", "32 (2 Hz)", "64 (1 Hz)"])

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
        layout.addWidget(self.canvas)
        layout.insertWidget(0, self.toolbar)
        self.setLayout(layout)

        self.toggle_live_mode(self.live_mode)

        self.live_avg_n = 18  # Default averaging for live mode

    def refresh_plot(self):
        mode = self.plot_mode_selector.currentText()
        for line in self.individual_lines + self.net_lines:
            line.set_visible(False)

        if mode == "Individual Load Cells":
            for i, line in enumerate(self.individual_lines):
                line.set_data(self.x_data, self.y_data[i])
                line.set_visible(True)
        else:
            net_x = [self.y_data[5][i] if i < len(self.y_data[5]) else 0 for i in range(len(self.x_data))]
            net_y = [sum(self.y_data[j][i] if i < len(self.y_data[j]) else 0 for j in [1, 3]) for i in range(len(self.x_data))]
            net_z = [sum(self.y_data[j][i] if i < len(self.y_data[j]) else 0 for j in [0, 2, 4]) for i in range(len(self.x_data))]

            self.net_lines[0].set_data(self.x_data, net_x)
            self.net_lines[1].set_data(self.x_data, net_y)
            self.net_lines[2].set_data(self.x_data, net_z)
            for line in self.net_lines:
                line.set_visible(True)

        if self.x_data:
            self.ax.set_xlim(self.x_data[0], self.x_data[-1])
            all_y = []
            for line in self.individual_lines + self.net_lines:
                if line.get_visible():
                    all_y += list(line.get_ydata())
            if all_y:
                self.ax.set_ylim(min(all_y), max(all_y))

        handles = [line for line in self.individual_lines + self.net_lines if line.get_visible()]
        labels = [line.get_label() for line in handles]
        self.ax.legend(handles, labels, fontsize=7)
        self.canvas.draw()


    def toggle_live_mode(self, checked):
        self.live_mode = checked
        self.window_selector.setEnabled(checked)
        self.start_btn.setEnabled(checked)
        self.plot_button.setEnabled(not checked)
        self.start_time_edit.setEnabled(not checked)
        self.end_time_edit.setEnabled(not checked)
        self.averaging_selector.setEnabled(not checked)

        if not checked:
            self.live_timer.stop()
            self.start_btn.setText("Start")

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
            # self.live_checkbox.setEnabled(True)
            self.window_selector.setEnabled(True)
        else:
            self.x_data.clear()
            self.y_data = [collections.deque() for _ in range(6)]
            self.live_timer.start()
            self.start_btn.setText("Stop")
            # self.live_checkbox.setEnabled(False)
            self.window_selector.setEnabled(False)

    def request_latest_live_point(self):
        self.worker.query_last_n_samples(self.live_avg_n)

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
        self.x_data.clear()
        self.y_data = [collections.deque() for _ in range(6)]
        for dt, loads in data:
            self.x_data.append(dt)
            for i in range(6):
                self.y_data[i].append(loads[i])
        print(f"[PlotWindow] Received {len(data)} data points")
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
