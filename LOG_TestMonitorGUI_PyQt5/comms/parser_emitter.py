from PyQt5.QtCore import QObject, pyqtSignal
import datetime

class ParserEmitter(QObject):
    new_data = pyqtSignal(str, list, list, int, int)  # timestamp, loads, accels, accel_on, accel_stale
    update_sps = pyqtSignal(int, int)  # lc_sps, accel_sps
    trigger_started = pyqtSignal(datetime.datetime)


