from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QComboBox, QFrame, QProgressBar
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
import db.connection as db
from db.users import authenticate, get_all_users

SERVER   = r"localhost\SQLEXPRESS"
DATABASE = "cafel"


class ConnectWorker(QThread):
    success = pyqtSignal(list)
    failure = pyqtSignal(str)

    def run(self):
        ok = db.connect(SERVER, DATABASE)
        if ok:
            try:
                users = get_all_users()
                self.success.emit(users)
            except Exception as e:
                self.failure.emit(f"Ошибка загрузки пользователей: {e}")
        else:
            self.failure.emit("Не удалось подключиться к серверу")


class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.user = None
        self.role = "cashier"
        self.setWindowTitle("Вход в систему")
        self.setFixedSize(340, 340)
        self._worker = None
        self._build_ui()
        QTimer.singleShot(300, self._start_connect)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Шапка
        hdr = QFrame()
        hdr.setFixedHeight(56)
        hdr.setStyleSheet("background:#2B579A;")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(16, 0, 16, 0)
        lbl = QLabel("Система учёта")
        lbl.setStyleSheet("color:#FFFFFF; font-size:17px; font-weight:bold;")
        hl.addWidget(lbl)
        layout.addWidget(hdr)

        # Тело
        body = QFrame()
        body.setStyleSheet("background:#F0F0F0;")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(24, 16, 24, 16)
        bl.setSpacing(8)

        # Статус подключения
        self.lbl_status = QLabel("⏳ Подключение к базе данных...")
        self.lbl_status.setStyleSheet("color:#888888; font-size:12px;")
        bl.addWidget(self.lbl_status)

        # Прогресс бар
        self.progress = QProgressBar()
        self.progress.setFixedHeight(6)
        self.progress.setRange(0, 0)  # бесконечная анимация
        self.progress.setStyleSheet("""
            QProgressBar {
                border: none;
                border-radius: 3px;
                background: #E0E0E0;
            }
            QProgressBar::chunk {
                background: #316AC5;
                border-radius: 3px;
            }
        """)
        bl.addWidget(self.progress)

        bl.addSpacing(4)

        bl.addWidget(self._lbl("Пользователь:"))
        self.combo_user = QComboBox()
        self.combo_user.setFixedHeight(28)
        self.combo_user.setEnabled(False)
        bl.addWidget(self.combo_user)

        bl.addWidget(self._lbl("Пароль:"))
        self.inp_pwd = QLineEdit()
        self.inp_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        self.inp_pwd.setFixedHeight(28)
        self.inp_pwd.setPlaceholderText("Введите пароль...")
        self.inp_pwd.setEnabled(False)
        self.inp_pwd.returnPressed.connect(self._do_login)
        bl.addWidget(self.inp_pwd)

        self.lbl_error = QLabel("")
        self.lbl_error.setStyleSheet("color:#CC0000; font-size:12px;")
        bl.addWidget(self.lbl_error)

        bl.addSpacing(4)
        self.btn_login = QPushButton("Войти")
        self.btn_login.setFixedHeight(34)
        self.btn_login.setEnabled(False)
        self.btn_login.setStyleSheet("""
            QPushButton {
                background:#316AC5; border:1px solid #1A3F8A;
                border-radius:3px; color:#FFFFFF;
                font-weight:bold; font-size:14px;
            }
            QPushButton:hover   { background:#4A7FD4; }
            QPushButton:pressed { background:#1A3F8A; }
            QPushButton:disabled { background:#CCCCCC; color:#888; border-color:#AAA; }
        """)
        self.btn_login.clicked.connect(self._do_login)
        bl.addWidget(self.btn_login)
        layout.addWidget(body)

        # Подвал
        ftr = QFrame()
        ftr.setFixedHeight(24)
        ftr.setStyleSheet("background:#2B579A;")
        fl = QHBoxLayout(ftr)
        fl.setContentsMargins(10, 0, 10, 0)
        lbl2 = QLabel(f"База: {DATABASE}  •  {SERVER}")
        lbl2.setStyleSheet("color:#A0C0FF; font-size:11px;")
        fl.addWidget(lbl2)
        layout.addWidget(ftr)

    def _lbl(self, t):
        l = QLabel(t)
        l.setStyleSheet("color:#333; font-size:12px; font-weight:bold;")
        return l

    def _start_connect(self):
        self._worker = ConnectWorker()
        self._worker.success.connect(self._on_connected)
        self._worker.failure.connect(self._on_error)
        self._worker.start()

    def _on_connected(self, users):
        # Останавливаем прогресс
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.progress.setStyleSheet("""
            QProgressBar { border:none; border-radius:3px; background:#E0E0E0; }
            QProgressBar::chunk { background:#4CAF50; border-radius:3px; }
        """)
        self.lbl_status.setText("✓ Подключено: " + DATABASE)
        self.lbl_status.setStyleSheet("color:#006600; font-size:12px;")

        self.combo_user.clear()
        for u in users:
            self.combo_user.addItem(u["Name"] or u["Code"], u)
        self.combo_user.setEnabled(True)
        self.inp_pwd.setEnabled(True)
        self.btn_login.setEnabled(True)
        self.inp_pwd.setFocus()

    def _on_error(self, msg):
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setStyleSheet("""
            QProgressBar { border:none; border-radius:3px; background:#E0E0E0; }
            QProgressBar::chunk { background:#CC0000; border-radius:3px; }
        """)
        self.lbl_status.setText("✗ " + msg)
        self.lbl_status.setStyleSheet("color:#CC0000; font-size:12px;")
        # Кнопка повтора
        self.btn_login.setText("Повторить подключение")
        self.btn_login.setEnabled(True)
        self.btn_login.clicked.disconnect()
        self.btn_login.clicked.connect(self._retry)

    def _retry(self):
        self.lbl_status.setText("⏳ Подключение...")
        self.lbl_status.setStyleSheet("color:#888888; font-size:12px;")
        self.progress.setRange(0, 0)
        self.btn_login.setEnabled(False)
        self.btn_login.setText("Войти")
        self.btn_login.clicked.disconnect()
        self.btn_login.clicked.connect(self._do_login)
        self._start_connect()

    def _do_login(self):
        idx = self.combo_user.currentIndex()
        if idx < 0:
            self.lbl_error.setText("Выберите пользователя")
            return
        user_data = self.combo_user.itemData(idx)
        code = user_data.get("Code", "")
        password = self.inp_pwd.text()
        user = authenticate(code, password)
        if user:
            self.user = user
            level = int(user.get("UserLevel") or 0)
            self.role = "admin" if level > 0 else "cashier"
            self.accept()
        else:
            self.lbl_error.setText("Неверный пароль")
            self.inp_pwd.clear()
            self.inp_pwd.setFocus()

    def _set_error(self, msg):
        self.lbl_error.setText(msg)
