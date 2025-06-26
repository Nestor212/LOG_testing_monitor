# LOG_Testing_Monitor

**LOG_Testing_Monitor** is a PyQt5-based graphical user interface (GUI) application designed for real-time and historical monitoring of load cell and accelerometer data. It interfaces with a Teensy microcontroller over a socket connection, logs incoming data to an SQLite database, and provides interactive plotting and data export features.

## 🔧 Features

- Real-time data plotting for 6 load cell channels
- Historical data visualization with averaging and date range selection
- Zoom and pan enabled plots using Matplotlib
- CSV export for:
  - Load cell data
  - Accelerometer data
  - Zeroing offsets (load cells & accelerometers)
- Separate tables for structured database logging:
  - `load_cells`
  - `accelerometer`
  - `load_cell_zeros`
  - `accelerometer_zeros`

## 🗃️ Directory Structure
```
LOG_TestMonitorGUI_PyQt5/
├── comms/
│   ├── parser_emitter.py       # Parses incoming socket data and buffers it for database logging
│   ├── teensy_socket.py        # Manages socket connection to Teensy and receives real-time data
│   └── ...
├── Database/
│   ├── Data/data_log.db        # SQLite3 database
│   ├── ExportData/*.csv        # Data exported with 'export_data.py' goes here
│   ├── db.py                   # SQLite class for initiating and connecting to database
│   ├── export_data.py          # CLI tool for exporting CSVs
│   └── ...
├── ui/
│   ├── plotter.py              # Main GUI plot window
│   ├── sql_worker.py           # SQL db worker used by plotter.py
│   ├── main_window.py          # Main UI window with controls and labels
│   └── ...
├── main.py                     # Entry point of the GUI
└── README.md
```

## 🚀 Getting Started

### Prerequisites

- Python 3.8+
- PyQt5
- Matplotlib
- SQLite3

### Installation

sudo apt update
sudo apt install python3-pyqt5 python3-matplotlib sqlite3

Or Use pip in a virtual environment

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

## Running the GUI

python3 main.py

## Exporting Data

### Export all tables for a specific day
python3 Database/export_data.py 2025-06-26

### Export by time range
python3 Database/export_data.py 2025-06-26 00:00:00 2025-06-26 23:59:59
