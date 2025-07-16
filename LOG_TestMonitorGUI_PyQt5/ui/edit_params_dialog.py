from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QComboBox, QPushButton, QHBoxLayout

class EditParamsDialog(QDialog):
    def __init__(self, current_params, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Parameters")

        layout = QVBoxLayout()

        self.wheel_selector = QComboBox()
        self.wheel_selector.addItems(["60/40", "120"])
        self.wheel_selector.setCurrentText(current_params["wheel"])

        self.depth_input = QLineEdit(str(current_params["depth"]))
        self.feed_input = QLineEdit(str(current_params["feed"]))
        self.pitch_input = QLineEdit(str(current_params["pitch"]))

        layout.addWidget(QLabel("Wheel:"))
        layout.addWidget(self.wheel_selector)
        layout.addWidget(QLabel("Depth (mm):"))
        layout.addWidget(self.depth_input)
        layout.addWidget(QLabel("Feed (mm/s):"))
        layout.addWidget(self.feed_input)
        layout.addWidget(QLabel("Pitch (mm):"))
        layout.addWidget(self.pitch_input)

        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Save")
        cancel_btn = QPushButton("Cancel")
        save_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def get_params(self):
        return {
            "wheel": self.wheel_selector.currentText(),
            "depth": float(self.depth_input.text()),
            "feed": float(self.feed_input.text()),
            "pitch": float(self.pitch_input.text())
        }
