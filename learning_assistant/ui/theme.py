"""A compact neutral theme shared by the main window and selection popup."""

APP_QSS = """
QWidget {
    font-family: "Segoe UI", "Microsoft YaHei UI";
    font-size: 14px;
    color: #172033;
}
QMainWindow, QDialog { background: #f5f7fb; }
QFrame#card {
    background: white;
    border: 1px solid #e3e8f1;
    border-radius: 14px;
}
QLabel#muted { color: #758096; font-size: 12px; }
QLabel#title { font-size: 20px; font-weight: 700; color: #111827; }
QLabel#word { font-size: 30px; font-weight: 700; color: #111827; }
QLabel#phonetic { color: #58657a; font-size: 15px; }
QLabel#section { color: #58657a; font-size: 12px; font-weight: 600; }
QPlainTextEdit {
    border: none;
    background: transparent;
    selection-background-color: #cfe1ff;
    font-size: 17px;
}
QPushButton#primary {
    background: #2563eb; color: white; border: none; border-radius: 9px;
    padding: 9px 18px; font-weight: 600;
}
QPushButton#primary:hover { background: #1d4ed8; }
QPushButton#primary:pressed { background: #1e40af; }
QPushButton#secondary, QToolButton {
    background: #f1f4f9; color: #334155; border: 1px solid #e1e6ef;
    border-radius: 8px; padding: 7px 10px;
}
QPushButton#secondary:hover, QToolButton:hover { background: #e8edf5; }
QPushButton#ghost {
    background: transparent; color: #516077; border: none; padding: 6px 8px;
}
QPushButton#ghost:hover { color: #1d4ed8; background: #eef4ff; border-radius: 7px; }
QComboBox, QLineEdit {
    background: white; border: 1px solid #dce2ec; border-radius: 8px;
    padding: 7px 10px; min-height: 20px;
}
QListWidget {
    background: white; border: 1px solid #e1e6ef; border-radius: 10px; padding: 4px;
}
QListWidget::item { padding: 8px; border-radius: 6px; }
QListWidget::item:selected { background: #e8f0ff; color: #1d4ed8; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { width: 8px; background: transparent; }
QScrollBar::handle:vertical { background: #cbd3df; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""

