APP_STYLE = """
* {
    font-family: 'Segoe UI', Tahoma, sans-serif;
    font-size: 13px;
    color: #1A1A1A;
}

QMainWindow, QDialog, QWidget {
    background-color: #ECE9D8;
}

/* Sidebar */
#sidebar {
    background-color: #2B579A;
    border-right: 2px solid #1E3F7A;
}

#sidebar QPushButton {
    background: transparent;
    border: none;
    border-radius: 2px;
    padding: 8px 12px;
    text-align: left;
    color: #C8D8F0;
    font-size: 12px;
    margin: 1px 4px;
}

#sidebar QPushButton:hover {
    background-color: #3A6BBF;
    color: #FFFFFF;
}

#sidebar QPushButton:checked {
    background-color: #1A3060;
    color: #FFFFFF;
    font-weight: 600;
    border-left: 3px solid #FFD700;
    padding-left: 9px;
}

/* Content */
#content { background-color: #ECE9D8; }

#page_title {
    font-size: 16px;
    font-weight: 700;
    color: #2B579A;
    padding: 12px 0 8px 0;
}

/* Standard buttons - Windows XP style */
QPushButton {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #F4F4F4, stop:1 #DCDCDC);
    border: 1px solid #ADADAD;
    border-radius: 3px;
    padding: 4px 12px;
    color: #1A1A1A;
    min-height: 22px;
}

QPushButton:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #EEF4FF, stop:1 #C8DCFF);
    border-color: #2B579A;
}

QPushButton:pressed {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #C0D4F0, stop:1 #A0B8E0);
    border-color: #1A3F8A;
}

QPushButton:checked {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #C0D4F0, stop:1 #A0B8E0);
    border: 2px solid #2B579A;
    font-weight: 600;
}

QPushButton:disabled {
    background-color: #F4F4F4;
    color: #ADADAD;
    border-color: #D5D5D5;
}

/* Tables */
QTableWidget {
    background-color: #FFFFFF;
    border: 1px solid #808080;
    gridline-color: #D0D0D0;
    selection-background-color: #316AC5;
    selection-color: #FFFFFF;
    alternate-background-color: #F0F4FF;
}

QTableWidget::item {
    padding: 3px 6px;
    border: none;
    color: #000000;
}

QTableWidget::item:hover {
    background-color: #E8F0FF;
    color: #000000;
}

QHeaderView::section {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #F4F4F4, stop:1 #DCDCDC);
    color: #1A1A1A;
    font-weight: 600;
    font-size: 12px;
    padding: 4px 6px;
    border: none;
    border-right: 1px solid #C0C0C0;
    border-bottom: 2px solid #808080;
}

/* Input fields */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {
    background-color: #FFFFFF;
    border: 1px solid #7F9DB9;
    border-radius: 2px;
    padding: 3px 6px;
    color: #000000;
    selection-background-color: #316AC5;
    selection-color: #FFFFFF;
}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QDateEdit:focus {
    border-color: #316AC5;
}

QComboBox::drop-down {
    border: none;
    width: 18px;
    background: transparent;
}

QComboBox QAbstractItemView {
    background-color: #FFFFFF;
    border: 1px solid #7F9DB9;
    selection-background-color: #316AC5;
    selection-color: #FFFFFF;
    color: #000000;
}

/* Scrollbars */
QScrollBar:vertical {
    background: transparent;
    width: 12px;
    margin: 2px;
    border: none;
}
QScrollBar::handle:vertical {
    background: #B8C4D6;
    border-radius: 4px;
    min-height: 40px;
}
QScrollBar::handle:vertical:hover, QScrollBar::handle:vertical:pressed { background: #7F95B8; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }

QScrollBar:horizontal {
    background: transparent;
    height: 12px;
    margin: 2px;
    border: none;
}
QScrollBar::handle:horizontal {
    background: #B8C4D6;
    border-radius: 4px;
    min-width: 40px;
}
QScrollBar::handle:horizontal:hover, QScrollBar::handle:horizontal:pressed { background: #7F95B8; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }

/* Status bar */
QStatusBar {
    background-color: #2B579A;
    color: #FFFFFF;
    font-size: 12px;
}

QStatusBar::item { border: none; }

/* Tabs */
QTabWidget::pane {
    border: 1px solid #ADADAD;
    background: #FFFFFF;
    top: -1px;
}

QTabBar::tab {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #F4F4F4, stop:1 #DCDCDC);
    color: #444444;
    padding: 5px 12px;
    border: 1px solid #ADADAD;
    border-bottom: none;
    border-radius: 3px 3px 0 0;
    margin-right: 2px;
}

QTabBar::tab:selected {
    background: #FFFFFF;
    color: #000000;
    font-weight: 600;
}

QTabBar::tab:hover { background: #E4EEFF; }

/* Frames */
QFrame[frameShape="4"], QFrame[frameShape="5"] {
    color: #ADADAD;
}

/* Message boxes */
QMessageBox { background-color: #ECE9D8; }
QMessageBox QPushButton { min-width: 75px; padding: 4px 12px; }

/* Splitter */
QSplitter::handle { background: #C0C0C0; }
QSplitter::handle:horizontal { width: 3px; }
QSplitter::handle:vertical { height: 3px; }
"""
