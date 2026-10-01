from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QStackedWidget, QFrame, QStatusBar
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QKeySequence, QShortcut
import os


class NavBtn(QPushButton):
    def __init__(self, icon, text, parent=None):
        super().__init__(f"  {icon}  {text}", parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(38)
        self.setStyleSheet("""
            QPushButton {
                background:transparent; border:none; border-radius:2px;
                padding:0 8px; text-align:left;
                color:#C8D8F0; font-size:12px; margin:1px 4px;
            }
            QPushButton:hover  { background:#3A6BBF; color:#FFF; }
            QPushButton:checked {
                background:#1A3060; color:#FFF; font-weight:bold;
                border-left:3px solid #FFD700; padding-left:5px;
            }
        """)


class MainWindow(QMainWindow):
    def __init__(self, user: dict, role: str = "admin"):
        super().__init__()
        self.user = user
        self.role = role
        self._pages = {}
        self._nav_buttons = []

        # Иконка
        icon_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "resources", "icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        title = "Касса" if role == "cashier" else "Управление"
        self.setWindowTitle(title)

        self._build_ui()
        self._navigate("pos")

        # Выход из fullscreen по Escape (для администратора)
        if role == "admin":
            esc = QShortcut(QKeySequence("Escape"), self)
            esc.activated.connect(self._toggle_fullscreen)

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showMaximized()
        else:
            self.showFullScreen()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        if self.role == "admin":
            root.addWidget(self._build_sidebar())

        content = QWidget()
        content.setObjectName("content")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        self.stack = QStackedWidget()
        cl.addWidget(self.stack)
        root.addWidget(content)

        sb = QStatusBar()
        self.setStatusBar(sb)
        user_name = self.user.get("Name") or self.user.get("Code", "")
        role_txt = "Кассир" if self.role == "cashier" else "Администратор"
        sb.showMessage(f"{role_txt}: {user_name}  •  База: cafel  "
                       f"| Escape — выход из полноэкранного режима")

    def _build_sidebar(self):
        w = QWidget()
        w.setObjectName("sidebar")
        w.setFixedWidth(170)
        w.setStyleSheet("background:#2B579A; border-right:2px solid #1E3F7A;")
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        hdr = QFrame()
        hdr.setFixedHeight(52)
        hdr.setStyleSheet("background:#1E3F7A;")
        hl = QVBoxLayout(hdr)
        hl.setContentsMargins(12, 0, 12, 0)
        lbl = QLabel("Система учёта")
        lbl.setStyleSheet("color:#FFF; font-size:14px; font-weight:bold;")
        hl.addWidget(lbl)
        v.addWidget(hdr)

        sep = QFrame(); sep.setFixedHeight(1)
        sep.setStyleSheet("background:#1E3F7A;")
        v.addWidget(sep)
        v.addSpacing(4)

        nav = [
            ("pos",        "🍽",  "Касса / Продажи"),
            ("goods",      "📦",  "Товары"),
            ("staff",      "👥",  "Сотрудники"),
            ("orders",     "🧾",  "Завершённые заказы"),
            ("reports",    "📈",  "Отчёты"),
        ]

        for key, icon, label in nav:
            btn = NavBtn(icon, label)
            btn.clicked.connect(lambda _, k=key: self._navigate(k))
            self._nav_buttons.append((key, btn))
            v.addWidget(btn)
            if key == "pos":
                s2 = QFrame(); s2.setFixedHeight(1)
                s2.setStyleSheet("background:#3A6BBF; margin:3px 8px;")
                v.addWidget(s2)

        v.addStretch()

        s3 = QFrame(); s3.setFixedHeight(1)
        s3.setStyleSheet("background:#1E3F7A;")
        v.addWidget(s3)

        user_name = self.user.get("Name") or self.user.get("Code", "")
        lbl_u = QLabel(f"👤  {user_name}")
        lbl_u.setStyleSheet(
            "color:#A0C0E8; font-size:11px; padding:8px 12px 2px 12px;")
        v.addWidget(lbl_u)

        btn_out = QPushButton("↩  Выйти")
        btn_out.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_out.setFixedHeight(30)
        btn_out.setStyleSheet("""
            QPushButton { background:transparent; border:none; border-radius:2px;
                text-align:left; color:#FF9090; font-size:12px;
                margin:0 6px 10px 6px; padding:0 8px; }
            QPushButton:hover { background:#5A1A1A; color:#FFBBBB; }
        """)
        btn_out.clicked.connect(self._logout)
        v.addWidget(btn_out)
        return w

    def _get_page(self, key):
        if key in self._pages:
            return self._pages[key]
        if key == "pos":
            from ui.pos import POSPage
            page = POSPage(self.user)
        elif key == "goods":
            from ui.goods import GoodsPage
            page = GoodsPage()
        elif key == "staff":
            from ui.staff import StaffPage
            page = StaffPage()
        elif key == "orders":
            from ui.orders import OrdersPage
            page = OrdersPage(self.user)
        elif key == "reports":
            from ui.reports import ReportsPage
            page = ReportsPage()
        else:
            page = self._placeholder(key)
        self._pages[key] = page
        self.stack.addWidget(page)
        return page

    def _placeholder(self, key):
        icons = {"reports": ("📈", "Отчёты")}
        icon, title = icons.get(key, ("📄", key))
        p = QWidget()
        v = QVBoxLayout(p)
        v.setContentsMargins(32, 32, 32, 32)
        t = QLabel(title); t.setObjectName("page_title"); v.addWidget(t)
        v.addStretch()
        l = QLabel(icon); l.setStyleSheet("font-size:48px;")
        l.setAlignment(Qt.AlignmentFlag.AlignCenter); v.addWidget(l)
        d = QLabel("Раздел в разработке")
        d.setStyleSheet("font-size:14px; color:#888;")
        d.setAlignment(Qt.AlignmentFlag.AlignCenter); v.addWidget(d)
        v.addStretch()
        return p

    def _navigate(self, key):
        for k, b in self._nav_buttons:
            b.setChecked(k == key)
        existed = key in self._pages
        page = self._get_page(key)
        if existed and hasattr(page, "reload_goods"):
            page.reload_goods()
        self.stack.setCurrentWidget(page)

    def _logout(self):
        from PyQt6.QtWidgets import QMessageBox
        if QMessageBox.question(
            self, "Выход", "Выйти из системы?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            import db.connection as db_conn
            db_conn.close()
            self.close()
