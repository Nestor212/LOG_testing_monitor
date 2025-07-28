from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QComboBox, QCheckBox, QPushButton, QHBoxLayout

class TeensySettingsDialog(QDialog):
    def __init__(self, parent=None, socket_thread=None, log_callback=None, initial_settings=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Teensy Settings")
        self.socket_thread = socket_thread
        self.log_callback = log_callback

        layout = QVBoxLayout()

        # Conversion Mode
        self.conv_mode_combo = QComboBox()
        self.conv_mode_combo.addItems(["Single-Shot", "Continuous"])
        layout.addWidget(QLabel("Conversion Mode:"))
        layout.addWidget(self.conv_mode_combo)

        # SPS
        self.sps_combo = QComboBox()
        self.sps_combo.addItems(["100", "200", "400", "800"])
        layout.addWidget(QLabel("Samples Per Second (SPS):"))
        layout.addWidget(self.sps_combo)

        # Load Cell Checkboxes
        self.lc_checkboxes = []
        layout.addWidget(QLabel("Enabled Load Cells:"))
        for i in range(1, 7):
            cb = QCheckBox(f"LC{i}")
            cb.setChecked(False)
            self.lc_checkboxes.append(cb)
            layout.addWidget(cb)

        # Buttons
        button_layout = QHBoxLayout()
        send_btn = QPushButton("Send Settings")
        send_btn.clicked.connect(self.send_settings)
        button_layout.addWidget(send_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.close)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)
        self.setLayout(layout)

        if initial_settings:
            self.conv_mode_combo.setCurrentText(initial_settings["conv_mode"])
            self.sps_combo.setCurrentText(initial_settings["sps"])
            for i, state in enumerate(initial_settings["load_cells"]):
                self.lc_checkboxes[i].setChecked(state)

    def get_teensy_settings(self):
        return {
            "conv_mode": self.conv_mode_combo.currentText(),
            "sps": self.sps_combo.currentText(),
            "load_cells": [cb.isChecked() for cb in self.lc_checkboxes]
        }

    def send_settings(self):
        conv_mode = 0 if self.conv_mode_combo.currentText() == "Single-Shot" else 1
        sps = self.sps_combo.currentText()
        lc_states = [int(cb.isChecked()) for cb in self.lc_checkboxes]

        command = f"SET {conv_mode} {sps} " + " ".join(map(str, lc_states))

        if self.socket_thread:
            self.socket_thread.send_command(command)

        if self.log_callback:
            self.log_callback(f"Sent: {command}")

        self.accept()
