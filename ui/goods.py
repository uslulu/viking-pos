from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QAbstractItemView, QDialog, QFormLayout,
    QDoubleSpinBox, QTabWidget, QFrame, QListWidget,
    QListWidgetItem, QSplitter, QInputDialog, QComboBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QFont
from db.goods import (
    get_all, get_groups, get_by_id, create, update, delete,
    create_group, update_group, delete_group
)
from ui.loader import LoaderSlot

C_BLUE = '#2B579A'; C_BLUE_D = '#1E3F7A'

# ── Диалог редактирования товара ──────────────────────────────────────────────

class PriceEdit(QLineEdit):
    """Поле цены: принимает и точку, и запятую (важно для сенсорной клавиатуры)."""
    def __init__(self):
        super().__init__()
        from PyQt6.QtGui import QRegularExpressionValidator
        from PyQt6.QtCore import QRegularExpression
        self.setValidator(QRegularExpressionValidator(
            QRegularExpression(r"^\d{0,7}([.,]\d{0,2})?$")))
        self.setFixedHeight(30); self.setText("0.00")
        self.setStyleSheet("font-size:14px;padding:0 8px;")

    def setValue(self, v):
        self.setText(f"{float(v or 0):.2f}")

    def value(self) -> float:
        try: return round(float((self.text() or "0").replace(",", ".")), 2)
        except ValueError: return 0.0


class GoodDialog(QDialog):
    def __init__(self, good=None, groups=None, parent=None):
        super().__init__(parent)
        self.good = good
        self.is_edit = good is not None
        self.groups = groups or []
        self.setWindowTitle("Редактировать товар" if self.is_edit else "Новый товар")
        self.setMinimumWidth(440)
        self.setModal(True)
        self._build()
        if self.is_edit:
            self._fill()

    def _build(self):
        v = QVBoxLayout(self); v.setContentsMargins(16,16,16,16); v.setSpacing(12)

        title = QLabel("Редактировать товар" if self.is_edit else "Новый товар")
        title.setStyleSheet(f"font-size:15px;font-weight:bold;color:{C_BLUE_D};")
        v.addWidget(title)

        form = QFormLayout(); form.setContentsMargins(4,4,4,4); form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.inp_name    = self._inp()
        self.spin_price_out1 = self._spin()
        self.spin_price_in   = self._spin()
        self.combo_group = QComboBox(); self.combo_group.setFixedHeight(28)
        self.combo_group.addItem("— Без группы —", None)
        for g in self.groups:
            self.combo_group.addItem(g["Name"], g["ID"])
        self.inp_measure = self._inp(); self.inp_measure.setText("шт")
        self.inp_code    = self._inp()
        self.inp_barcode = self._inp()

        form.addRow(self._lbl("Наименование:*"), self.inp_name)
        form.addRow(self._lbl("Цена продажи:*"), self.spin_price_out1)
        form.addRow(self._lbl("Цена закупки:"),  self.spin_price_in)
        form.addRow(self._lbl("Категория:"),     self.combo_group)
        form.addRow(self._lbl("Ед. изм.:"),      self.inp_measure)
        form.addRow(self._lbl("Код:"),           self.inp_code)
        form.addRow(self._lbl("Штрихкод:"),      self.inp_barcode)
        v.addLayout(form)

        bh = QHBoxLayout(); bh.addStretch()
        bc = QPushButton("Отмена"); bc.setFixedHeight(30); bc.clicked.connect(self.reject)
        bs = QPushButton("💾  Сохранить"); bs.setFixedHeight(30)
        bs.setStyleSheet(f"QPushButton{{background:{C_BLUE};border:none;border-radius:3px;"
            "color:#FFF;font-weight:bold;padding:0 16px;}"
            f"QPushButton:hover{{background:#4A7FD4;}}")
        bs.clicked.connect(self._save)
        bh.addWidget(bc); bh.addWidget(bs); v.addLayout(bh)

    def _inp(self):
        w = QLineEdit(); w.setFixedHeight(26); return w

    def _spin(self):
        return PriceEdit()

    def _lbl(self, t):
        l = QLabel(t); l.setStyleSheet("color:#444;font-size:12px;"); return l

    def _fill(self):
        g = self.good
        self.inp_name.setText(g.get("Name") or "")
        self.inp_code.setText(g.get("Code") or "")
        self.inp_barcode.setText(g.get("BarCode1") or "")
        self.inp_measure.setText(g.get("Measure1") or "шт")
        self.spin_price_in.setValue(float(g.get("PriceIn") or 0))
        self.spin_price_out1.setValue(float(g.get("PriceOut1") or 0))
        gid = g.get("GroupID")
        if gid:
            for i in range(self.combo_group.count()):
                if self.combo_group.itemData(i) == gid:
                    self.combo_group.setCurrentIndex(i); break

    def _save(self):
        name = self.inp_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Ошибка", "Укажите наименование"); return
        data = {
            "Code": self.inp_code.text().strip(),
            "BarCode1": self.inp_barcode.text().strip(),
            "Name": name,
            "Measure1": self.inp_measure.text().strip() or "шт",
            "PriceIn":   self.spin_price_in.value(),
            "PriceOut1": self.spin_price_out1.value(),
            "TaxGroup": 1,
            "GroupID": self.combo_group.currentData(),
        }
        if self.is_edit:
            ok, err = update(self.good["ID"], data)
            if ok:
                # Контроль: перечитываем из базы
                saved = get_by_id(self.good["ID"]) or {}
                if abs(float(saved.get("PriceOut1") or 0) - data["PriceOut1"]) > 0.001:
                    ok, err = False, "Цена в базе не изменилась после сохранения"
        else:
            ok, err = create(data), ""
        if ok: self.accept()
        else: QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить.\n{err}")


# ── Главная страница товаров ──────────────────────────────────────────────────

class GoodsLoader(QThread):
    done = pyqtSignal(list)
    def __init__(self, search="", group_id=None):
        super().__init__(); self.search = search; self.group_id = group_id
    def run(self):
        try: goods = get_all(self.search, self.group_id)
        except Exception as e: print(f'GoodsLoader: {e}'); goods = []
        self.done.emit(goods)


class GoodsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._goods = []
        self._groups = []
        self._current_group_id = None  # None=все, -1=без группы, int=группа
        self._loader = LoaderSlot(self._on_goods)
        self._search_timer = QTimer(); self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._load_goods)
        self._build_ui()
        QTimer.singleShot(100, self._load_all)

    def _build_ui(self):
        v = QVBoxLayout(self); v.setContentsMargins(20,0,20,20); v.setSpacing(0)

        title = QLabel("Товары"); title.setObjectName("page_title")
        v.addWidget(title)

        # Сплиттер: левая = категории, правая = товары
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet("QSplitter::handle{background:#CCCCCC;width:2px;}")

        # ── Левая панель: категории ───────────────────────────────────────────
        left = QFrame()
        left.setFixedWidth(200)
        left.setStyleSheet("background:#FFFFFF;border:1px solid #CCCCCC;border-radius:4px;")
        lv = QVBoxLayout(left); lv.setContentsMargins(0,0,0,0); lv.setSpacing(0)

        cat_hdr = QFrame()
        cat_hdr.setStyleSheet(f"background:{C_BLUE};border-radius:4px 4px 0 0;")
        cat_hdr_l = QHBoxLayout(cat_hdr); cat_hdr_l.setContentsMargins(8,6,8,6)
        cat_hdr_l.addWidget(QLabel("Категории",
            styleSheet="color:#FFF;font-weight:bold;font-size:12px;"))
        lv.addWidget(cat_hdr)

        # Кнопки управления категориями
        cat_btns = QHBoxLayout(); cat_btns.setContentsMargins(4,4,4,4); cat_btns.setSpacing(4)
        for txt, slot in [("＋", self._add_group), ("✎", self._rename_group), ("✕", self._del_group)]:
            b = QPushButton(txt); b.setFixedSize(32,26)
            b.setStyleSheet("QPushButton{background:#E8E8E8;border:1px solid #CCC;"
                "border-radius:3px;font-size:13px;font-weight:bold;}"
                "QPushButton:hover{background:#D0E0FF;border-color:#316AC5;}")
            b.clicked.connect(slot); cat_btns.addWidget(b)
        cat_btns.addStretch()
        lv.addLayout(cat_btns)

        self.cat_list = QListWidget()
        self.cat_list.setStyleSheet("""
            QListWidget { border:none; background:#FFFFFF; outline:none; }
            QListWidget::item { padding:7px 10px; font-size:13px; color:#333; border-bottom:1px solid #F0F0F0; }
            QListWidget::item:selected { background:#D0E4FF; color:#000; font-weight:bold; }
            QListWidget::item:hover { background:#EEF4FF; }
        """)
        self.cat_list.currentRowChanged.connect(self._on_cat_changed)
        lv.addWidget(self.cat_list)
        splitter.addWidget(left)

        # ── Правая панель: товары ─────────────────────────────────────────────
        right = QWidget()
        rv = QVBoxLayout(right); rv.setContentsMargins(0,0,0,0); rv.setSpacing(6)

        # Тулбар товаров
        tb = QHBoxLayout(); tb.setSpacing(6)
        for txt, slot, primary, danger in [
            ("+ Добавить",  self._add_good,  True,  False),
            ("✎ Изменить",  self._edit_good, False, False),
            ("✕ Удалить",   self._del_good,  False, True),
        ]:
            b = QPushButton(txt); b.setFixedHeight(28)
            if primary:
                b.setStyleSheet(f"QPushButton{{background:{C_BLUE};border:none;border-radius:3px;"
                    "color:#FFF;font-weight:bold;padding:0 12px;}"
                    "QPushButton:hover{background:#4A7FD4;}")
            elif danger:
                b.setStyleSheet("QPushButton{background:#F0E0E0;border:1px solid #CC4444;"
                    "border-radius:3px;color:#CC0000;padding:0 12px;}"
                    "QPushButton:hover{background:#FFD0D0;}")
            b.clicked.connect(slot); tb.addWidget(b)
        tb.addStretch()
        self.inp_search = QLineEdit()
        self.inp_search.setPlaceholderText("🔍  Поиск...")
        self.inp_search.setFixedHeight(28); self.inp_search.setMinimumWidth(200)
        self.inp_search.textChanged.connect(lambda: self._search_timer.start(350))
        tb.addWidget(self.inp_search)
        rv.addLayout(tb)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color:#888;font-size:11px;")
        rv.addWidget(self.lbl_status)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ["Наименование", "Код", "Ед.", "Цена закупки", "Цена продажи", "Группа"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(True)
        self.table.doubleClicked.connect(self._edit_good)

        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in (1,2,3,4,5):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setStyleSheet("""
            QTableWidget{background:#FFF;border:1px solid #CCC;
                selection-background-color:#D0E4FF;alternate-background-color:#F5F8FF;}
            QTableWidget::item{padding:4px 8px;font-size:13px;}
            QHeaderView::section{background:#F0F0F0;color:#333;font-weight:bold;
                font-size:12px;padding:5px 8px;border:none;border-bottom:2px solid #CCC;}
        """)
        rv.addWidget(self.table)
        splitter.addWidget(right)
        splitter.setSizes([200, 800])
        v.addWidget(splitter, 1)

    # ── Загрузка ──────────────────────────────────────────────────────────────

    def _load_all(self):
        self._groups = get_groups()
        self._rebuild_cat_list()
        self._load_goods()

    def _rebuild_cat_list(self):
        self.cat_list.blockSignals(True)
        self.cat_list.clear()

        # "Все товары"
        item_all = QListWidgetItem("📦  Все товары")
        item_all.setData(Qt.ItemDataRole.UserRole, None)
        item_all.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.cat_list.addItem(item_all)

        # Группы
        for g in self._groups:
            item = QListWidgetItem(f"   {g['Name']}")
            item.setData(Qt.ItemDataRole.UserRole, g["ID"])
            self.cat_list.addItem(item)

        # "Без группы"
        item_none = QListWidgetItem("   — Без группы")
        item_none.setData(Qt.ItemDataRole.UserRole, -1)
        item_none.setForeground(QColor("#888"))
        self.cat_list.addItem(item_none)

        # Восстанавливаем выбор
        for i in range(self.cat_list.count()):
            it = self.cat_list.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == self._current_group_id:
                self.cat_list.setCurrentRow(i)
                break
        else:
            self.cat_list.setCurrentRow(0)

        self.cat_list.blockSignals(False)

    def _on_cat_changed(self, row):
        if row < 0: return
        item = self.cat_list.item(row)
        if not item: return
        self._current_group_id = item.data(Qt.ItemDataRole.UserRole)
        self._load_goods()

    def _load_goods(self):
        search = self.inp_search.text().strip()
        gid = self._current_group_id  # None=все, -1=без группы, int=группа
        self.lbl_status.setText("Загрузка...")
        self._loader.start(GoodsLoader(search, gid))

    def _on_goods(self, goods):
        self._goods = goods
        self.table.setRowCount(len(goods))
        zero_count = 0
        for row, g in enumerate(goods):
            price = float(g.get("PriceOut1") or 0)
            if price == 0: zero_count += 1
            vals = [
                g.get("Name") or "",
                g.get("Code") or "",
                g.get("Measure1") or "",
                f"{float(g.get('PriceIn') or 0):.2f}",
                f"{price:.2f}",
                g.get("GroupName") or "—",
            ]
            for col, val in enumerate(vals):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter |
                    (Qt.AlignmentFlag.AlignLeft if col in (0,1,2,5)
                     else Qt.AlignmentFlag.AlignRight))
                if col == 4 and price == 0:
                    item.setForeground(QColor("#CC0000"))
                self.table.setItem(row, col, item)
        status = f"Товаров: {len(goods)}"
        if zero_count: status += f"  |  ⚠ Без цены: {zero_count}"
        self.lbl_status.setText(status)

    def _selected_good(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._goods): return None
        return self._goods[row]

    # ── Категории: CRUD ───────────────────────────────────────────────────────

    def _add_group(self):
        name, ok = QInputDialog.getText(self, "Новая категория", "Название:")
        if ok and name.strip():
            if create_group(name.strip()):
                self._load_all()
            else:
                QMessageBox.critical(self, "Ошибка", "Не удалось создать категорию")

    def _rename_group(self):
        item = self.cat_list.currentItem()
        if not item: return
        gid = item.data(Qt.ItemDataRole.UserRole)
        if not gid or gid == -1:
            QMessageBox.information(self, "", "Выберите категорию для переименования")
            return
        g = next((x for x in self._groups if x["ID"] == gid), None)
        if not g: return
        name, ok = QInputDialog.getText(self, "Переименовать", "Новое название:", text=g["Name"])
        if ok and name.strip():
            if update_group(gid, name.strip()):
                self._load_all()
            else:
                QMessageBox.critical(self, "Ошибка", "Не удалось переименовать")

    def _del_group(self):
        item = self.cat_list.currentItem()
        if not item: return
        gid = item.data(Qt.ItemDataRole.UserRole)
        if not gid or gid == -1:
            QMessageBox.information(self, "", "Выберите категорию для удаления")
            return
        g = next((x for x in self._groups if x["ID"] == gid), None)
        if not g: return
        reply = QMessageBox.question(
            self, "Удалить категорию",
            f"Удалить категорию «{g['Name']}»?\n"
            f"Товары из неё перейдут в «Без группы».",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            if delete_group(gid):
                self._current_group_id = None
                self._load_all()
            else:
                QMessageBox.critical(self, "Ошибка", "Не удалось удалить категорию")

    # ── Товары: CRUD ──────────────────────────────────────────────────────────

    def _add_good(self):
        dlg = GoodDialog(groups=self._groups, parent=self)
        # Предустанавливаем текущую группу
        if self._current_group_id and self._current_group_id != -1:
            for i in range(dlg.combo_group.count()):
                if dlg.combo_group.itemData(i) == self._current_group_id:
                    dlg.combo_group.setCurrentIndex(i); break
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._load_goods()

    def _edit_good(self):
        g = self._selected_good()
        if not g:
            QMessageBox.information(self, "", "Выберите товар в таблице"); return
        full = get_by_id(g["ID"])
        dlg = GoodDialog(good=full, groups=self._groups, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._load_goods()

    def _del_good(self):
        g = self._selected_good()
        if not g:
            QMessageBox.information(self, "", "Выберите товар в таблице"); return
        if QMessageBox.question(
            self, "Удалить", f"Удалить «{g.get('Name')}»?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            if delete(g["ID"]): self._load_goods()
