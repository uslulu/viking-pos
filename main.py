import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Скрываем консольное окно (если программа запущена через .bat / py)
if sys.platform == "win32":
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:
        pass

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont, QIcon
from ui.styles import APP_STYLE
from ui.login import LoginDialog
from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Система учёта")
    app.setStyleSheet(APP_STYLE)
    app.setFont(QFont("Segoe UI", 10))

    icon_path = os.path.join(os.path.dirname(__file__), "resources", "icon.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    screen = app.primaryScreen().geometry()
    login = LoginDialog()
    login.move((screen.width()-login.width())//2,
               (screen.height()-login.height())//2)

    if login.exec() == LoginDialog.DialogCode.Accepted and login.user:
        import ui.keyboard as kb
        kb.install(app)
        window = MainWindow(login.user, role=login.role)
        window.showFullScreen()
        sys.exit(app.exec())
    sys.exit(0)


if __name__ == "__main__":
    main()
