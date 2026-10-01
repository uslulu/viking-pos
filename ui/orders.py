"""Завершённые заказы — для администратора и официанта"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame,
    QDateEdit, QAbstractItemView, QDialog, QComboBox, QMessageBox
)
from PyQt6.QtCore import Qt, QDate, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont
import db.connection as db
from datetime import datetime, timedelta
from ui.fmt import fmt_qty

C_BLUE='#2B579A'; C_BLUE_D='#1E3F7A'; C_GREEN='#217346'

class OrdersLoader(QThread):
    done = pyqtSignal(list)
    def __init__(self, date_from, date_to, user_id=None):
        super().__init__()
        self.date_from = date_from
        self.date_to = date_to
        self.user_id = user_id

    def run(self):
        try:
            sql = """
                SELECT pay.Acct, pay.Date, pay.Total, pay.Cash, pay.Card, pay.Transfer,
                    ops.UserName, ops.Items, ops.OperatorID
                FROM (
                    SELECT Acct, MAX(Date) AS Date, SUM(Qtty) AS Total,
                        SUM(CASE WHEN Mode=0 THEN Qtty ELSE 0 END) AS Cash,
                        SUM(CASE WHEN Mode=1 THEN Qtty ELSE 0 END) AS Card,
                        SUM(CASE WHEN Mode=2 THEN Qtty ELSE 0 END) AS Transfer
                    FROM Payments WHERE OperType=2
                      AND CAST(Date AS DATE) BETWEEN ? AND ?
                    GROUP BY Acct
                ) pay
                JOIN (
                    SELECT o.Acct, MAX(u.Name) AS UserName, MAX(o.OperatorID) AS OperatorID,
                        COUNT(*) AS Items
                    FROM Operations o LEFT JOIN Users u ON o.OperatorID=u.ID
                    WHERE o.OperType=2 GROUP BY o.Acct
                ) ops ON ops.Acct=pay.Acct
            """
            params = [self.date_from, self.date_to]
            if self.user_id:
                sql += " WHERE ops.OperatorID=?"
                params.append(self.user_id)
            sql += " ORDER BY pay.Date DESC"
            self.done.emit(db.fetch_all(sql, params))
        except Exception as e:
            print(f'OrdersLoader: {e}')
            self.done.emit([])


class OrderDetailDialog(QDialog):
    def __init__(self, acct, parent=None):
        super().__init__(parent)
        self.acct = acct
        self.setWindowTitle(f'Заказ № {acct}')
        self.setFixedSize(500, 400)
        self.setModal(True)
        self._build()
        self._load()

    def _build(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(16,16,16,16); v.setSpacing(10)
        self.lbl_title = QLabel(f'Заказ № {self.acct}')
        self.lbl_title.setStyleSheet(f'font-size:16px;font-weight:bold;color:{C_BLUE_D};')
        v.addWidget(self.lbl_title)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(['Наименование','Кол-во','Цена','Сумма'])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in (1,2,3): hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setStyleSheet('QTableWidget{background:#FFF;border:1px solid #CCC;'
            'alternate-background-color:#F5F8FF;}'
            'QTableWidget::item{padding:4px 6px;font-size:13px;}')
        v.addWidget(self.table)

        self.lbl_total = QLabel('Итого: 0.00')
        self.lbl_total.setStyleSheet(f'font-size:16px;font-weight:bold;color:{C_BLUE_D};')
        self.lbl_total.setAlignment(Qt.AlignmentFlag.AlignRight)
        v.addWidget(self.lbl_total)

        bh = QHBoxLayout(); bh.addStretch()
        bp = QPushButton('🖨  Печать чека')
        bp.setFixedHeight(34)
        bp.setStyleSheet("QPushButton{background:#2B579A;border:none;border-radius:3px;"
            "color:#FFF;font-weight:bold;padding:0 14px;}"
            "QPushButton:hover{background:#4A7FD4;}")
        bp.clicked.connect(self._print)
        bh.addWidget(bp)
        bc = QPushButton('Закрыть'); bc.setFixedHeight(34); bc.clicked.connect(self.reject)
        bh.addWidget(bc)
        v.addLayout(bh)

    def _print(self):
        from ui.printer import print_receipt_dialog
        print_receipt_dialog(self.acct, self)

    def _load(self):
        try:
            items = db.fetch_all("""
                SELECT g.Name as GoodName, o.Qtty, o.PriceOut, o.Qtty*o.PriceOut as LineTotal
                FROM Operations o JOIN Goods g ON o.GoodID=g.ID
                WHERE o.OperType=2 AND o.Acct=? ORDER BY o.ID
            """, [self.acct])
            self.table.setRowCount(len(items))
            total = 0.0
            for row, item in enumerate(items):
                lt = float(item.get('LineTotal') or 0); total += lt
                for col,(val,align) in enumerate([
                    (item.get('GoodName') or '', Qt.AlignmentFlag.AlignLeft),
                    (fmt_qty(item.get('Qtty')), Qt.AlignmentFlag.AlignCenter),
                    (f"{item.get('PriceOut',0):.2f}", Qt.AlignmentFlag.AlignRight),
                    (f'{lt:.2f}', Qt.AlignmentFlag.AlignRight),
                ]):
                    t = QTableWidgetItem(val)
                    t.setTextAlignment(Qt.AlignmentFlag.AlignVCenter|align)
                    if col==3: t.setForeground(QColor(C_BLUE_D))
                    self.table.setItem(row,col,t)
            self.lbl_total.setText(f'Итого: {total:.2f}')
        except Exception as e:
            print(f'OrderDetail: {e}')


class OrdersPage(QWidget):
    def __init__(self, user=None, parent=None):
        super().__init__(parent)
        self.user = user or {}
        self.user_id = user.get('ID') if user else None
        # Администратор видит все, кассир — только свои
        level = int((user or {}).get('UserLevel') or 0)
        self.is_admin = level > 0
        self._orders = []
        self._loader = None
        self._build_ui()
        self._today()

    def _build_ui(self):
        v = QVBoxLayout(self); v.setContentsMargins(20,0,20,20); v.setSpacing(0)
        title = QLabel('Завершённые заказы'); title.setObjectName('page_title')
        v.addWidget(title)

        # Панель фильтров
        ph = QHBoxLayout(); ph.setSpacing(8)

        def pbtn(txt, slot):
            b = QPushButton(txt); b.setFixedHeight(28)
            b.setStyleSheet('QPushButton{background:#E8E8E8;border:1px solid #CCC;'
                'border-radius:3px;font-size:12px;padding:0 10px;}'
                'QPushButton:hover{background:#D0E0FF;border-color:#316AC5;}')
            b.clicked.connect(slot); return b

        ph.addWidget(pbtn('Сегодня', self._today))
        ph.addWidget(pbtn('Вчера', self._yesterday))
        ph.addWidget(pbtn('Неделя', self._week))
        ph.addSpacing(8)
        ph.addWidget(QLabel('С:', styleSheet='font-size:12px;'))
        self.date_from = QDateEdit(); self.date_from.setCalendarPopup(True)
        self.date_from.setDate(QDate.currentDate()); self.date_from.setFixedHeight(28)
        ph.addWidget(self.date_from)
        ph.addWidget(QLabel('По:', styleSheet='font-size:12px;'))
        self.date_to = QDateEdit(); self.date_to.setCalendarPopup(True)
        self.date_to.setDate(QDate.currentDate()); self.date_to.setFixedHeight(28)
        ph.addWidget(self.date_to)
        br = QPushButton('Показать'); br.setFixedHeight(28)
        br.setStyleSheet('QPushButton{background:#316AC5;border:none;border-radius:3px;'
            'color:#FFF;font-weight:bold;padding:0 12px;}'
            'QPushButton:hover{background:#4A7FD4;}')
        br.clicked.connect(self._run); ph.addWidget(br)
        ph.addStretch()
        self.lbl_status = QLabel('')
        self.lbl_status.setStyleSheet('color:#888;font-size:12px;')
        ph.addWidget(self.lbl_status)
        v.addLayout(ph); v.addSpacing(8)

        # Таблица
        self.table = QTableWidget()
        cols = ['№ заказа','Дата','Официант','Позиций','Сумма','Наличные','Карта','Перевод']
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(True)
        self.table.doubleClicked.connect(self._open_detail)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for i in (3,4,5,6,7): hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setStyleSheet('QTableWidget{background:#FFF;border:1px solid #CCC;'
            'selection-background-color:#D0E4FF;alternate-background-color:#F5F8FF;}'
            'QTableWidget::item{padding:4px 8px;font-size:13px;}'
            'QHeaderView::section{background:#F0F0F0;color:#333;font-weight:bold;'
            'font-size:12px;padding:5px 8px;border:none;border-bottom:2px solid #CCC;}')
        v.addWidget(self.table)

        # Подсказка
        hint = QLabel('Двойной клик — просмотр состава заказа')
        hint.setStyleSheet('color:#888;font-size:11px;padding:4px 0;')
        v.addWidget(hint)

    def _set_dates(self, df, dt):
        self.date_from.setDate(QDate(df.year,df.month,df.day))
        self.date_to.setDate(QDate(dt.year,dt.month,dt.day))
        self._run()

    def _today(self):
        t=datetime.now().date(); self._set_dates(t,t)
    def _yesterday(self):
        t=datetime.now().date()-timedelta(days=1); self._set_dates(t,t)
    def _week(self):
        t=datetime.now().date(); self._set_dates(t-timedelta(days=6),t)

    def _run(self):
        df = self.date_from.date().toPyDate()
        dt = self.date_to.date().toPyDate()
        uid = None if self.is_admin else self.user_id
        self.lbl_status.setText('Загрузка...')
        self._loader = OrdersLoader(df, dt, uid)
        self._loader.done.connect(self._on_data)
        self._loader.start()

    def _on_data(self, orders):
        self._orders = orders
        self.table.setRowCount(len(orders))
        total_sum = 0.0
        for row, o in enumerate(orders):
            total = float(o.get('Total') or 0); total_sum += total
            cash = float(o.get('Cash') or 0)
            card = float(o.get('Card') or 0)
            tr = float(o.get('Transfer') or 0)
            date_str = ''
            if o.get('Date'):
                try: date_str = o['Date'].strftime('%d.%m.%Y %H:%M')
                except: date_str = str(o['Date'])
            vals = [
                (str(o.get('Acct','')), Qt.AlignmentFlag.AlignCenter),
                (date_str, Qt.AlignmentFlag.AlignLeft),
                (o.get('UserName') or '—', Qt.AlignmentFlag.AlignLeft),
                (str(o.get('Items',0)), Qt.AlignmentFlag.AlignCenter),
                (f'{total:.2f}', Qt.AlignmentFlag.AlignRight),
                (f'{cash:.2f}', Qt.AlignmentFlag.AlignRight),
                (f'{card:.2f}', Qt.AlignmentFlag.AlignRight),
                (f'{tr:.2f}', Qt.AlignmentFlag.AlignRight),
            ]
            for col,(val,align) in enumerate(vals):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter|align)
                if col==4: item.setForeground(QColor(C_BLUE_D)); item.setFont(QFont('Segoe UI',12,QFont.Weight.Bold))
                if col==5 and cash>0: item.setForeground(QColor(C_GREEN))
                if col==6 and card>0: item.setForeground(QColor('#7B1FA2'))
                if col==7 and tr>0: item.setForeground(QColor('#C06000'))
                self.table.setItem(row,col,item)
        self.lbl_status.setText(f'Заказов: {len(orders)}  |  Выручка: {total_sum:.2f}')

    def _open_detail(self):
        row = self.table.currentRow()
        if row<0 or row>=len(self._orders): return
        acct = self._orders[row].get('Acct')
        if acct: OrderDetailDialog(acct, self).exec()
