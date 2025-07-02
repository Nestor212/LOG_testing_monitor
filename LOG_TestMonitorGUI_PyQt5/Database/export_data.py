from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
    QDateTimeEdit, QFileDialog, QMessageBox, QCheckBox
)
from PyQt5.QtCore import QDateTime
import sqlite3
import csv
import datetime
import os
from Database.db import get_connection


class DataExportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export Sensor Data")
        self.resize(400, 200)

        layout = QVBoxLayout()

        # Date/time inputs
        self.start_dt = QDateTimeEdit(QDateTime.currentDateTime().addSecs(-3600))
        self.start_dt.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.start_dt.setCalendarPopup(True)
        layout.addWidget(QLabel("Start Time:"))
        layout.addWidget(self.start_dt)

        self.end_dt = QDateTimeEdit(QDateTime.currentDateTime())
        self.end_dt.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.end_dt.setCalendarPopup(True)
        layout.addWidget(QLabel("End Time:"))
        layout.addWidget(self.end_dt)

        # Checkboxes
        self.cb_load_cells = QCheckBox("Export Load Cells")
        self.cb_load_cells.setChecked(True)
        self.cb_accel = QCheckBox("Export Accelerometer")
        self.cb_accel.setChecked(True)
        self.cb_lc_offsets = QCheckBox("Export Load Cell Zero Offsets")
        self.cb_lc_offsets.setChecked(True)
        self.cb_accel_offsets = QCheckBox("Export Accelerometer Zero Offsets")
        self.cb_accel_offsets.setChecked(True)
        layout.addWidget(self.cb_load_cells)
        layout.addWidget(self.cb_accel)
        layout.addWidget(self.cb_lc_offsets)
        layout.addWidget(self.cb_accel_offsets)

        # Folder selector
        folder_layout = QHBoxLayout()
        self.folder_label = QLabel("No folder selected")
        self.select_folder_btn = QPushButton("Select Folder")
        self.select_folder_btn.clicked.connect(self.select_folder)
        folder_layout.addWidget(self.folder_label)
        folder_layout.addWidget(self.select_folder_btn)
        layout.addLayout(folder_layout)

        # Export button
        self.export_btn = QPushButton("Export")
        self.export_btn.clicked.connect(self.run_export)
        layout.addWidget(self.export_btn)

        self.setLayout(layout)
        self.output_folder = None

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Export Folder")
        if folder:
            self.output_folder = folder
            self.folder_label.setText(folder)

    def run_export(self):
        if not self.output_folder:
            QMessageBox.warning(self, "No folder", "Please select a destination folder.")
            return

        start = self.start_dt.dateTime().toPyDateTime()
        end = self.end_dt.dateTime().toPyDateTime()
        base = f"{start.strftime('%Y-%m-%d_%H-%M-%S')}_to_{end.strftime('%Y-%m-%d_%H-%M-%S')}"
        row_counts = []

        try:
            if self.cb_load_cells.isChecked():
                n = self.export_table("load_cells",
                                      ["timestamp", "lc1", "lc2", "lc3", "lc4", "lc5", "lc6"],
                                      start, end, f"load_cells_{base}.csv")
                row_counts.append(f"Load Cells: {n}")

            if self.cb_accel.isChecked():
                n = self.export_table("accelerometer",
                                      ["timestamp", "ax", "ay", "az"],
                                      start, end, f"accelerometer_{base}.csv")
                row_counts.append(f"Accelerometer: {n}")

            if self.cb_lc_offsets.isChecked():
                n = self.export_table("load_cell_zero_offsets",
                                      ["timestamp", "lc1_offset", "lc2_offset", "lc3_offset", "lc4_offset", "lc5_offset", "lc6_offset"],
                                      start, end, f"load_cell_zero_offsets_{base}.csv")
                row_counts.append(f"Load Cell Zero Offsets: {n}")

            if self.cb_accel_offsets.isChecked():
                n = self.export_table("accelerometer_zero_offsets",
                                      ["timestamp", "ax_offset", "ay_offset", "az_offset"],
                                      start, end, f"accelerometer_zero_offsets_{base}.csv")
                row_counts.append(f"Accelerometer Zero Offsets: {n}")

            summary = "\n".join(row_counts)
            QMessageBox.information(self, "Export Complete", f"✅ Data export complete.\n\n{summary}")

        except Exception as e:
            QMessageBox.critical(self, "Export Failed", f"❌ Error: {e}")

    def export_table(self, table, columns, start_time, end_time, filename):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT {', '.join(columns)}
            FROM {table}
            WHERE timestamp BETWEEN ? AND ?
            ORDER BY timestamp
        """, (start_time, end_time))
        rows = cursor.fetchall()
        conn.close()

        full_path = os.path.join(self.output_folder, filename)
        with open(full_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            for row in rows:
                ts = row[0]
                if isinstance(ts, datetime.datetime):
                    ts_str = ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                else:
                    ts_str = str(ts)
                writer.writerow([ts_str] + list(row[1:]))

        return len(rows)
