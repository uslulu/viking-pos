"""Управление сотрудниками — CRUD + смена пароля"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QDialog, QFormLayout, QLineEdit, QComboBox, QMessageBox, QFrame
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from db.users import (
    get_all_users, get_groups, create_user,
    update_user, change_password, delete_user
)

LEVELS = {0: "Кассир / Официант", 1: "Менеджер", 2: "Администратор"}


class UserDialog(QDialog):
    def __init__(self, user=None, parent=None):
        super().__init__(parent)
        self.user = user
        self.is_edit = user is not None
        self.setWindowTitle("Редактировать" if self.is_edit else "Новый сотрудник")
        self.setFixedSize(380, 320)
        self.setModal(True)
        self._build()
        if self.is_edit:
            self._fill()

    def _build(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 16, 20, 16)
        v.setSpacing(10)

        title = QLabel("Редактировать сотрудника" if self.is_edit else "Новый сотрудник")
        title.setStyleSheet("font-size:15px; font-weight:bold; color:#2B579A;")
        v.addWidget(title)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.inp_name = QLineEdit(); self.inp_name.setFixedHeight(28)
        self.inp_code = QLineEdit(); self.inp_code.setFixedHeight(28)
        self.inp_pwd  = QLineEdit(); self.inp_pwd.setFixedHeight(28)
        self.inp_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        if self.is_edit:
            self.inp_pwd.setPlaceholderText("Оставьте пустым — без изменений")

        self.combo_level = QComboBox(); self.combo_level.setFixedHeight(28)
        for k, v_name in LEVELS.items():
            self.combo_level.addItem(v_name, k)

        def lbl(t):
            l = QLabel(t); l.setStyleSheet("color:#444; font-size:12px;")
            return l

        form.addRow(lbl("Имя:*"),    self.inp_name)
        form.addRow(lbl("Логин:*"),  self.inp_code)
        form.addRow(lbl("Пароль:"),  self.inp_pwd)
        form.addRow(lbl("Роль:"),    self.combo_level)
        v.addLayout(form)

        v.addStretch()
        bh = QHBoxLayout(); bh.setSpacing(8); bh.addStretch()
        bc = QPushButton("Отмена"); bc.setFixedSize(90, 30); bc.clicked.connect(self.reject)
        bs = QPushButton("💾 Сохранить")
        bs.setFixedHeight(30)
        bs.setStyleSheet("""
            QPushButton { background:#316AC5; border:none; border-radius:3px;
                color:#FFF; font-weight:bold; padding:0 16px; }
            QPushButton:hover { background:#4A7FD4; }
        """)
        bs.clicked.connect(self._save)
        bh.addWidget(bc); bh.addWidget(bs)
        v.addLayout(bh)

    def _fill(self):
        self.inp_name.setText(self.user.get("Name") or "")
        self.inp_code.setText(self.user.get("Code") or "")
        level = int(self.user.get("UserLevel") or 0)
        for i in range(self.combo_level.count()):
            if self.combo_level.itemData(i) == level:
                self.combo_level.setCurrentIndex(i); break

    def _save(self):
        name = self.inp_name.text().strip()
        code = self.inp_code.text().strip()
        if not name or not code:
            QMessageBox.warning(self, "Ошибка", "Заполните имя и логин")
            return
        data = {
            "Name":      name,
            "Code":      code,
            "UserLevel": self.combo_level.currentData(),
            "GroupID":   self.user.get("GroupID") if self.is_edit else None,
            "Password":  self.inp_pwd.text(),
        }
        if self.is_edit:
            ok = update_user(self.user["ID"], data)
            pwd = self.inp_pwd.text()
            if pwd:
                change_password(self.user["ID"], pwd)
        else:
            if not self.inp_pwd.text():
                QMessageBox.warning(self, "Ошибка", "Укажите пароль для нового сотрудника")
                return
            ok = create_user(data)
        if ok:
            self.accept()
        else:
            QMessageBox.critical(self, "Ошибка", "Не удалось сохранить")


class StaffPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._users = []
        self._build_ui()
        QTimer.singleShot(100, self._load)

    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 0, 20, 20)
        v.setSpacing(0)

        title = QLabel("Сотрудники")
        title.setObjectName("page_title")
        v.addWidget(title)

        tb = QHBoxLayout(); tb.setSpacing(6)
        for txt, slot, primary in [
            ("+ Добавить",   self._add,    True),
            ("✎ Изменить",   self._edit,   False),
            ("🔑 Сменить пароль", self._pwd, False),
            ("✕ Удалить",    self._delete, False),
        ]:
            b = QPushButton(txt); b.setFixedHeight(28)
            if primary:
                b.setStyleSheet("QPushButton{background:#316AC5;border:none;"
                    "border-radius:3px;color:#FFF;font-weight:bold;padding:0 12px;}"
                    "QPushButton:hover{background:#4A7FD4;}")
            b.clicked.connect(slot)
            tb.addWidget(b)
        tb.addStretch()
        v.addLayout(tb)
        v.addSpacing(8)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color:#888; font-size:11px; margin-bottom:4px;")
        v.addWidget(self.lbl_status)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Логин", "Имя", "Роль"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(True)
        self.table.doubleClicked.connect(self._edit)

        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        v.addWidget(self.table)

    def _load(self):
        try:
            self._users = get_all_users()
        except Exception as e:
            self._users = []
            self.lbl_status.setText(f"Ошибка: {e}")
            return
        self.table.setRowCount(len(self._users))
        for row, u in enumerate(self._users):
            level = int(u.get("UserLevel") or 0)
            role_name = LEVELS.get(level, str(level))
            vals = [
                str(u["ID"]),
                u.get("Code") or "",
                u.get("Name") or "",
                role_name,
            ]
            for col, val in enumerate(vals):
                item = QTableWidgetItem(val)
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                if col == 3:
                    color = "#006600" if level >= 2 else (
                        "#000080" if level == 1 else "#444444")
                    item.setForeground(QColor(color))
                self.table.setItem(row, col, item)
        self.lbl_status.setText(f"Сотрудников: {len(self._users)}")

    def _selected(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._users):
            return None
        return self._users[row]

    def _add(self):
        if UserDialog(parent=self).exec() == QDialog.DialogCode.Accepted:
            self._load()

    def _edit(self):
        u = self._selected()
        if not u:
            QMessageBox.information(self, "Выберите сотрудника",
                "Нажмите на строку в таблице")
            return
        if UserDialog(user=u, parent=self).exec() == QDialog.DialogCode.Accepted:
            self._load()

    def _pwd(self):
        u = self._selected()
        if not u:
            QMessageBox.information(self, "Выберите сотрудника",
                "Нажмите на строку в таблице")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Смена пароля — {u.get('Name')}")
        dlg.setFixedSize(300, 160)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(16, 16, 16, 16); v.setSpacing(10)
        v.addWidget(QLabel(f"Новый пароль для «{u.get('Name')}»:",
            styleSheet="font-size:13px;"))
        inp = QLineEdit(); inp.setEchoMode(QLineEdit.EchoMode.Password)
        inp.setFixedHeight(30); v.addWidget(inp)
        bh = QHBoxLayout(); bh.addStretch()
        bc = QPushButton("Отмена"); bc.clicked.connect(dlg.reject)
        bo = QPushButton("Сохранить")
        bo.setStyleSheet("QPushButton{background:#316AC5;border:none;border-radius:3px;"
            "color:#FFF;font-weight:bold;padding:0 12px;}")
        def _save():
            pwd = inp.text()
            if not pwd:
                QMessageBox.warning(dlg, "Ошибка", "Введите пароль"); return
            if change_password(u["ID"], pwd):
                dlg.accept()
            else:
                QMessageBox.critical(dlg, "Ошибка", "Не удалось сменить пароль")
        bo.clicked.connect(_save)
        bh.addWidget(bc); bh.addWidget(bo)
        v.addLayout(bh)
        dlg.exec()

    def _delete(self):
        u = self._selected()
        if not u:
            QMessageBox.information(self, "Выберите сотрудника",
                "Нажмите на строку в таблице")
            return
        if QMessageBox.question(
            self, "Удалить сотрудника",
            f"Удалить «{u.get('Name')}»?\nСотрудник будет деактивирован.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            if delete_user(u["ID"]):
                self._load()
