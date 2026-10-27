from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame,
    QDateEdit, QAbstractItemView
)
from PyQt6.QtCore import Qt, QDate, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont
import db.connection as db
from datetime import datetime, timedelta
from ui.loader import LoaderSlot

C_BLUE='#2B579A'; C_GREEN='#217346'; C_RED='#C00000'

class ReportLoader(QThread):
    done=pyqtSignal(dict)
    def __init__(self,date_from,date_to):
        super().__init__(); self.date_from=date_from; self.date_to=date_to
    def run(self):
        try:
            # Только оплаченные заказы: открытые столы в выручку не идут.
            # Скидка уже учтена в PriceOut (см. db.operations.close_table)
            # Итого
            r=db.fetch_one("""
                SELECT
                    COUNT(DISTINCT o.Acct) as orders,
                    SUM(o.Qtty*o.PriceOut) as revenue
                FROM Operations o
                WHERE o.OperType=2
                  AND CAST(o.Date AS DATE) BETWEEN ? AND ?
                  AND EXISTS (SELECT 1 FROM Payments p
                              WHERE p.OperType=2 AND p.Acct=o.Acct)
            """,[self.date_from,self.date_to])
            # Наличные vs карта из Payments
            pay=db.fetch_all("""
                SELECT p.Mode, SUM(p.Qtty) as total
                FROM Payments p
                WHERE p.OperType=2
                  AND CAST(p.Date AS DATE) BETWEEN ? AND ?
                GROUP BY p.Mode
            """,[self.date_from,self.date_to])
            cash=sum(float(x['total'] or 0) for x in pay if x['Mode']==0)
            card=sum(float(x['total'] or 0) for x in pay if x['Mode']==1)
            transfer=sum(float(x['total'] or 0) for x in pay if x['Mode']==2)
            paid_total=sum(float(x['total'] or 0) for x in pay)
            # Топ товаров
            top=db.fetch_all("""
                SELECT TOP 15
                    g.Name, SUM(o.Qtty) as qty, SUM(o.Qtty*o.PriceOut) as revenue
                FROM Operations o
                JOIN Goods g ON o.GoodID=g.ID
                WHERE o.OperType=2
                  AND CAST(o.Date AS DATE) BETWEEN ? AND ?
                  AND EXISTS (SELECT 1 FROM Payments p
                              WHERE p.OperType=2 AND p.Acct=o.Acct)
                GROUP BY g.Name ORDER BY revenue DESC
            """,[self.date_from,self.date_to])
            # По дням
            by_day=db.fetch_all("""
                SELECT CAST(o.Date AS DATE) as day,
                    COUNT(DISTINCT o.Acct) as orders,
                    SUM(o.Qtty*o.PriceOut) as revenue
                FROM Operations o
                WHERE o.OperType=2
                  AND CAST(o.Date AS DATE) BETWEEN ? AND ?
                  AND EXISTS (SELECT 1 FROM Payments p
                              WHERE p.OperType=2 AND p.Acct=o.Acct)
                GROUP BY CAST(o.Date AS DATE) ORDER BY day DESC
            """,[self.date_from,self.date_to])
            self.done.emit({'summary':r,'cash':cash,'card':card,'transfer':transfer,'paid_total':paid_total,'top':top,'by_day':by_day})
        except Exception as e:
            print(f'ReportLoader:{e}'); self.done.emit({})


class ReportsPage(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent); self._loader=LoaderSlot(self._on_data); self._build_ui()

    def _build_ui(self):
        v=QVBoxLayout(self); v.setContentsMargins(20,0,20,20); v.setSpacing(0)
        title=QLabel('Отчёты по продажам'); title.setObjectName('page_title'); v.addWidget(title)

        # Панель периода
        ph=QHBoxLayout(); ph.setSpacing(8)

        def period_btn(txt,slot):
            b=QPushButton(txt); b.setFixedHeight(28)
            b.setStyleSheet('QPushButton{background:#E8E8E8;border:1px solid #CCC;'
                'border-radius:3px;font-size:12px;padding:0 10px;}'
                'QPushButton:hover{background:#D0E0FF;border-color:#316AC5;}')
            b.clicked.connect(slot); return b

        ph.addWidget(period_btn('Сегодня',self._today))
        ph.addWidget(period_btn('Вчера',self._yesterday))
        ph.addWidget(period_btn('Неделя',self._week))
        ph.addWidget(period_btn('Месяц',self._month))
        ph.addSpacing(10)
        ph.addWidget(QLabel('С:',styleSheet='font-size:12px;'))
        self.date_from=QDateEdit(); self.date_from.setCalendarPopup(True)
        self.date_from.setDate(QDate.currentDate()); self.date_from.setFixedHeight(28)
        ph.addWidget(self.date_from)
        ph.addWidget(QLabel('По:',styleSheet='font-size:12px;'))
        self.date_to=QDateEdit(); self.date_to.setCalendarPopup(True)
        self.date_to.setDate(QDate.currentDate()); self.date_to.setFixedHeight(28)
        ph.addWidget(self.date_to)
        btn_run=QPushButton('Показать'); btn_run.setFixedHeight(28)
        btn_run.setStyleSheet('QPushButton{background:#316AC5;border:none;border-radius:3px;'
            'color:#FFF;font-weight:bold;padding:0 12px;}'
            'QPushButton:hover{background:#4A7FD4;}')
        btn_run.clicked.connect(self._run); ph.addWidget(btn_run)
        ph.addStretch()
        self.lbl_loading=QLabel(''); self.lbl_loading.setStyleSheet('color:#888;font-size:12px;')
        ph.addWidget(self.lbl_loading)
        v.addLayout(ph); v.addSpacing(10)

        # Карточки сводки
        cards=QHBoxLayout(); cards.setSpacing(12)
        self._cards={}
        for key,label,color in [
            ('revenue','Выручка',C_BLUE),
            ('orders','Заказов','#444'),
            ('cash','Наличными',C_GREEN),
            ('card','Картой','#7B1FA2'),
            ('transfer','Переводом','#C06000'),
        ]:
            f=QFrame(); f.setStyleSheet(f'background:#FFF;border:1px solid #CCC;'
                f'border-left:4px solid {color};border-radius:4px;')
            fv=QVBoxLayout(f); fv.setContentsMargins(12,8,12,8); fv.setSpacing(2)
            fv.addWidget(QLabel(label,styleSheet=f'color:#888;font-size:11px;font-weight:bold;'))
            lval=QLabel('—'); lval.setStyleSheet(f'font-size:22px;font-weight:bold;color:{color};')
            fv.addWidget(lval); self._cards[key]=lval; cards.addWidget(f)
        v.addLayout(cards); v.addSpacing(10)

        # Таблицы
        tables_h=QHBoxLayout(); tables_h.setSpacing(12)

        # По дням
        day_f=QFrame(); day_f.setStyleSheet('background:#FFF;border:1px solid #CCC;border-radius:4px;')
        dv=QVBoxLayout(day_f); dv.setContentsMargins(8,8,8,8); dv.setSpacing(4)
        dv.addWidget(QLabel('По дням',styleSheet=f'font-weight:bold;color:{C_BLUE};font-size:13px;'))
        self.tbl_days=self._make_table(['Дата','Заказов','Выручка'])
        dv.addWidget(self.tbl_days); tables_h.addWidget(day_f)

        # Топ товаров
        top_f=QFrame(); top_f.setStyleSheet('background:#FFF;border:1px solid #CCC;border-radius:4px;')
        tv=QVBoxLayout(top_f); tv.setContentsMargins(8,8,8,8); tv.setSpacing(4)
        tv.addWidget(QLabel('Топ товаров',styleSheet=f'font-weight:bold;color:{C_BLUE};font-size:13px;'))
        self.tbl_top=self._make_table(['Наименование','Кол-во','Выручка'])
        tv.addWidget(self.tbl_top); tables_h.addWidget(top_f)

        v.addLayout(tables_h,1)
        self._today()

    def _make_table(self,headers):
        t=QTableWidget(); t.setColumnCount(len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.verticalHeader().setVisible(False); t.setAlternatingRowColors(True)
        t.setShowGrid(True)
        hh=t.horizontalHeader()
        hh.setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        for i in range(1,len(headers)): hh.setSectionResizeMode(i,QHeaderView.ResizeMode.ResizeToContents)
        t.setStyleSheet('QTableWidget{background:#FFF;border:none;'
            'selection-background-color:#D0E4FF;alternate-background-color:#F5F8FF;}'
            'QTableWidget::item{padding:3px 6px;font-size:12px;}'
            'QHeaderView::section{background:#F0F0F0;color:#333;font-weight:bold;'
            'font-size:11px;padding:4px 6px;border:none;border-bottom:1px solid #CCC;}')
        return t

    def _set_dates(self,df,dt):
        self.date_from.setDate(QDate(df.year,df.month,df.day))
        self.date_to.setDate(QDate(dt.year,dt.month,dt.day))
        self._run()

    def _today(self):
        t=datetime.now().date(); self._set_dates(t,t)
    def _yesterday(self):
        t=datetime.now().date()-timedelta(days=1); self._set_dates(t,t)
    def _week(self):
        t=datetime.now().date(); self._set_dates(t-timedelta(days=6),t)
    def _month(self):
        t=datetime.now().date(); self._set_dates(t.replace(day=1),t)

    def _run(self):
        df=self.date_from.date().toPyDate()
        dt=self.date_to.date().toPyDate()
        self.lbl_loading.setText('Загрузка...')
        self._loader.start(ReportLoader(df,dt))

    def _on_data(self,data):
        self.lbl_loading.setText('')
        if not data: return
        s=data.get('summary') or {}
        rev=float(data.get('paid_total') or s.get('revenue') or 0)
        orders=int(s.get('orders') or 0)
        cash=float(data.get('cash') or 0)
        card=float(data.get('card') or 0)
        self._cards['revenue'].setText(f'{rev:.2f}')
        self._cards['orders'].setText(str(orders))
        self._cards['cash'].setText(f'{cash:.2f}')
        self._cards['card'].setText(f'{card:.2f}')
        self._cards['transfer'].setText(f"{float(data.get('transfer') or 0):.2f}")

        # По дням
        days=data.get('by_day') or []
        self.tbl_days.setRowCount(len(days))
        for row,d in enumerate(days):
            day_str=str(d['day']) if d.get('day') else '—'
            r=float(d.get('revenue') or 0)
            for col,(val,align) in enumerate([
                (day_str,Qt.AlignmentFlag.AlignLeft),
                (str(d.get('orders') or 0),Qt.AlignmentFlag.AlignCenter),
                (f'{r:.2f}',Qt.AlignmentFlag.AlignRight),
            ]):
                it=QTableWidgetItem(val)
                it.setTextAlignment(Qt.AlignmentFlag.AlignVCenter|align)
                if col==2: it.setForeground(QColor(C_BLUE)); it.setFont(QFont('Segoe UI',11,QFont.Weight.Bold))
                self.tbl_days.setItem(row,col,it)

        # Топ
        top=data.get('top') or []
        self.tbl_top.setRowCount(len(top))
        for row,d in enumerate(top):
            r=float(d.get('revenue') or 0)
            for col,(val,align) in enumerate([
                (d.get('Name') or '',Qt.AlignmentFlag.AlignLeft),
                (f"{d.get('qty') or 0:.1f}",Qt.AlignmentFlag.AlignCenter),
                (f'{r:.2f}',Qt.AlignmentFlag.AlignRight),
            ]):
                it=QTableWidgetItem(val)
                it.setTextAlignment(Qt.AlignmentFlag.AlignVCenter|align)
                if col==2: it.setForeground(QColor(C_GREEN))
                self.tbl_top.setItem(row,col,it)
