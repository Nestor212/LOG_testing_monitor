import os
os.environ["QT_QPA_PLATFORM"] = "xcb"
os.environ["QT_SCALE_FACTOR"] = "1.5"

import sys
from PyQt5.QtWidgets import QApplication
from ui.main_window import MainWindow
from Database.db import initialize_db

def main():
    initialize_db()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
