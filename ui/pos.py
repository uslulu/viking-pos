from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QStackedWidget,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem, QScrollArea,
    QFrame, QDialog, QLineEdit, QMessageBox, QAbstractItemView,
    QHeaderView, QSizePolicy, QDoubleSpinBox
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from app_config import CAFE_NAME
from db.goods import get_groups, get_all as get_goods, get_last_price
from db.operations import (
    get_open_tables, get_table_items,
    add_item, change_qty, remove_item, close_table, cancel_table,
    get_objects, get_default_partner, order_total
)
from ui.fmt import fmt_qty

C_BLUE='#2B579A'; C_BLUE_D='#1E3F7A'; C_BLUE_BTN='#316AC5'
C_GREEN='#217346'; C_RED='#C00000'; C_BG='#F0F0F0'
C_WHITE='#FFFFFF'; C_YELLOW='#FFFFC0'; FONT='Segoe UI'
GOODS_COLS=5; NUM_TABLES=12

def _btn(text,color=C_BLUE_BTN,fg=C_WHITE,fs=13,bold=True,minh=48,radius=6):
    b=QPushButton(text); b.setMinimumHeight(minh)
    w='bold' if bold else 'normal'
    b.setStyleSheet(f'QPushButton{{background:{color};color:{fg};border:none;'
        f'border-radius:{radius}px;font-size:{fs}px;font-weight:{w};padding:4px 8px;}}'
        f'QPushButton:pressed{{background:{C_BLUE_D};}}')
    return b

class ElideButton(QPushButton):
    """Кнопка, которая обрезает текст «…» по своей фактической ширине.
    Вторая строка (цена) не обрезается."""
    def __init__(self,title,sub=''):
        super().__init__(); self._title=title; self._sub=sub
        self.setToolTip(title); self._apply()
    def _apply(self):
        self.ensurePolished()
        fm=self.fontMetrics()
        w=max(20,self.width()-14)
        el=lambda s: fm.elidedText(s,Qt.TextElideMode.ElideRight,w)
        # Название в 2 строки по словам, вторая при нехватке места — с «…»
        words=self._title.split(); l1=''
        while words and fm.horizontalAdvance((l1+' '+words[0]).strip())<=w:
            l1=(l1+' '+words.pop(0)).strip()
        if not l1:  # одно очень длинное слово
            lines=[el(self._title)]
        else:
            rest=' '.join(words)
            lines=[l1]+([el(rest)] if rest else [])
        if self._sub:
            self.setText('\n'.join(lines+[self._sub]))
            self.setMinimumHeight(max(64,3*fm.lineSpacing()+18))
        else:
            self.setText('\n'.join(lines))
            self.setMinimumHeight(max(44,2*fm.lineSpacing()+16))

    def resizeEvent(self,e):
        super().resizeEvent(e); self._apply()


def _touch_scroll(area):
    """Прокрутка пальцем (свайпом) для сенсорного экрана."""
    try:
        from PyQt6.QtWidgets import QScroller
        QScroller.grabGesture(area.viewport(), QScroller.ScrollerGestureType.TouchGesture)
    except Exception as e: print(f'scroller: {e}')


class FlowGrid(QWidget):
    """Сетка кнопок: число колонок подстраивается под ширину экрана."""
    MIN_W=125
    def __init__(self):
        super().__init__()
        self._btns=[]; self._cols=0
        self._grid=QGridLayout(self); self._grid.setSpacing(6)
        self._grid.setContentsMargins(6,6,6,6)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop)
    def add(self,b):
        self._btns.append(b)
    def _relayout(self,width):
        cols=max(2,(width-12)//(self.MIN_W+6))
        if cols==self._cols: return
        self._cols=cols
        for b in self._btns: self._grid.removeWidget(b)
        for i,b in enumerate(self._btns): self._grid.addWidget(b,i//cols,i%cols)
        for i in range(cols): self._grid.setColumnStretch(i,1)
    def resizeEvent(self,e):
        self._relayout(e.size().width()); super().resizeEvent(e)
    def showEvent(self,e):
        self._relayout(self.width()); super().showEvent(e)


class GoodsLoader(QThread):
    done=pyqtSignal(list,list)
    def run(self):
        try:
            goods=get_goods(); groups=get_groups()
            # Цены «по последней продаже» для товаров без цены — ОДНИМ запросом
            last={}
            try:
                from db.connection import fetch_all
                for r in fetch_all("""
                    SELECT GoodID, PriceOut FROM (
                        SELECT GoodID, PriceOut,
                               ROW_NUMBER() OVER (PARTITION BY GoodID ORDER BY Date DESC, ID DESC) AS rn
                        FROM Operations WHERE OperType=2 AND PriceOut>0
                    ) t WHERE rn=1"""):
                    last[r['GoodID']]=float(r['PriceOut'] or 0)
            except Exception as e: print(f'last prices: {e}')
            for g in goods:
                p=float(g.get('PriceOut1') or 0)
                g['_price']=p if p>0 else last.get(g['ID'],0.0)
            self.done.emit(goods,groups)
        except Exception as e: print(f'GoodsLoader:{e}'); self.done.emit([],[])

class TablesLoader(QThread):
    done=pyqtSignal(list)
    def run(self):
        try: self.done.emit(get_open_tables())
        except Exception as e: print(f'TablesLoader:{e}'); self.done.emit([])

PAY_MODES=[('cash',0,'💵 Наличные','Наличными:'),
           ('card',1,'💳 Карта','Картой:'),
           ('transfer',2,'📲 Перевод','Переводом:')]

class PayDialog(QDialog):
    """Оплата: наличные / карта / перевод / смешанная. Экранный нумпад."""
    def __init__(self,items,parent=None):
        super().__init__(parent); self.items=items
        total=order_total(items); self.total=total
        self.discount_pct=0.0; self._pay_mode='cash'
        self.to_pay=total; self.change=0.0; self.received_cash=0.0
        self.payments={}  # {Mode: сумма в выручку}
        self._active_input=None; self._np_buf=''
        self.setWindowTitle('Оплата'); self.setFixedSize(720,600); self.setModal(True)
        self._build()

    def _build(self):
        root=QHBoxLayout(self); root.setContentsMargins(12,12,12,12); root.setSpacing(12)
        left=QVBoxLayout(); left.setSpacing(8)

        tot_f=QFrame(); tot_f.setStyleSheet(f'background:{C_YELLOW};border:1px solid #CCAA00;border-radius:6px;')
        th=QHBoxLayout(tot_f); th.setContentsMargins(12,8,12,8)
        th.addWidget(QLabel('К оплате:',styleSheet='font-size:14px;color:#444;'))
        self.lbl_topay=QLabel(f'{self.total:.2f}')
        self.lbl_topay.setStyleSheet(f'font-size:28px;font-weight:bold;color:{C_BLUE_D};')
        self.lbl_topay.setAlignment(Qt.AlignmentFlag.AlignRight); th.addWidget(self.lbl_topay)
        left.addWidget(tot_f)

        dh=QHBoxLayout()
        dh.addWidget(QLabel('Скидка %:',styleSheet='font-size:13px;'))
        self.spin_disc=QDoubleSpinBox(); self.spin_disc.setRange(0,100)
        self.spin_disc.setDecimals(1); self.spin_disc.setFixedHeight(40)
        self.spin_disc.setStyleSheet('font-size:14px;padding:4px;')
        self.spin_disc.valueChanged.connect(self._recalc); dh.addWidget(self.spin_disc)
        self.lbl_disc=QLabel(''); self.lbl_disc.setStyleSheet('font-size:12px;color:#888;')
        dh.addWidget(self.lbl_disc); dh.addStretch(); left.addLayout(dh)

        # Способ оплаты
        ph=QGridLayout(); ph.setSpacing(6)
        self._mode_btns={}
        for idx,(key,label) in enumerate([('cash','💵 Наличные'),('card','💳 Карта'),
                                          ('transfer','📲 Перевод'),('mixed','✂ Смешанная')]):
            b=QPushButton(label); b.setFixedHeight(46); b.setCheckable(True)
            b.setStyleSheet('QPushButton{background:#E8E8E8;border:1px solid #CCC;'
                'border-radius:6px;font-size:13px;padding:0 10px;color:#333;}'
                'QPushButton:checked{background:#316AC5;color:#FFF;border-color:#1A3F8A;font-weight:bold;}')
            b.clicked.connect(lambda _,k=key:self._mode(k))
            self._mode_btns[key]=b; ph.addWidget(b,idx//2,idx%2)
        left.addLayout(ph)

        # Поля сумм
        self._inputs={}
        g=QGridLayout(); g.setSpacing(6)
        for row,(key,_m,_b,lbl) in enumerate(PAY_MODES):
            g.addWidget(QLabel(lbl,styleSheet='font-size:13px;color:#444;'),row,0)
            inp=QLineEdit('0.00'); inp.setFixedHeight(46); inp.setReadOnly(True)
            inp.mousePressEvent=lambda e,i=inp:self._activate(i) if i.isEnabled() else None
            self._inputs[key]=inp; g.addWidget(inp,row,1)
        left.addLayout(g)

        self.lbl_change=QLabel('Сдача:  0.00')
        self.lbl_change.setStyleSheet(f'font-size:20px;font-weight:bold;color:{C_GREEN};')
        left.addWidget(self.lbl_change)
        left.addStretch()

        bh=QHBoxLayout(); bh.setSpacing(10)
        bc=_btn('Отмена',color='#CCC',fg='#333',fs=14,minh=48); bc.clicked.connect(self.reject)
        bo=_btn('✔  Провести',color=C_GREEN,fs=15,minh=48); bo.clicked.connect(self._confirm)
        bh.addWidget(bc); bh.addWidget(bo); left.addLayout(bh)
        root.addLayout(left,3)

        # Нумпад
        np=QVBoxLayout(); np.setSpacing(6)
        np.addWidget(QLabel('Нажмите на поле суммы, наберите и OK',
            styleSheet='font-size:12px;color:#888;font-weight:bold;'))
        self.np_display=QLabel('0'); self.np_display.setFixedHeight(52)
        self.np_display.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
        self.np_display.setStyleSheet('background:#F8F8F8;border:2px solid #CCC;'
            'border-radius:6px;font-size:24px;font-weight:bold;color:#000;padding:0 10px;')
        np.addWidget(self.np_display)
        dg=QGridLayout(); dg.setSpacing(6)
        for txt,r,c in [('7',0,0),('8',0,1),('9',0,2),('4',1,0),('5',1,1),('6',1,2),
                         ('1',2,0),('2',2,1),('3',2,2),('.',3,0),('0',3,1),('00',3,2)]:
            b=QPushButton(txt); b.setFixedHeight(56)
            b.setStyleSheet('QPushButton{background:#FFF;border:1px solid #CCC;'
                'border-radius:6px;font-size:22px;font-weight:bold;color:#CC0000;}'
                'QPushButton:pressed{background:#FFE0E0;}')
            b.clicked.connect(lambda _,t=txt:self._np_press(t)); dg.addWidget(b,r,c)
        cl=QPushButton('C'); cl.setFixedHeight(56)
        cl.setStyleSheet('QPushButton{background:#EEE;border:1px solid #AAA;border-radius:6px;'
            'font-size:20px;font-weight:bold;color:#333;}QPushButton:pressed{background:#DDD;}')
        cl.clicked.connect(self._np_clear); dg.addWidget(cl,0,3)
        rest=QPushButton('Остаток'); rest.setFixedHeight(56)
        rest.setStyleSheet('QPushButton{background:#E0ECFF;border:1px solid #316AC5;border-radius:6px;'
            'font-size:13px;font-weight:bold;color:#1E3F7A;}QPushButton:pressed{background:#C0D8FF;}')
        rest.clicked.connect(self._np_rest); dg.addWidget(rest,1,3)
        bs=QPushButton('⌫'); bs.setFixedHeight(56)
        bs.setStyleSheet('QPushButton{background:#FF8080;border:1px solid #CC0000;'
            'border-radius:6px;font-size:22px;font-weight:bold;color:#FFF;}'
            'QPushButton:pressed{background:#FF5050;}')
        bs.clicked.connect(self._np_back); dg.addWidget(bs,2,3)
        ok=QPushButton('OK ✔'); ok.setFixedHeight(56)
        ok.setStyleSheet(f'QPushButton{{background:{C_GREEN};border:1px solid #1A5C35;'
            'border-radius:6px;font-size:16px;font-weight:bold;color:#FFF;}'
            'QPushButton:pressed{background:#1A5C35;}')
        ok.clicked.connect(self._np_ok); dg.addWidget(ok,3,3)
        np.addLayout(dg); np.addStretch()
        root.addLayout(np,2)

        self._recalc()

    # ── поля ──
    def _val(self,key):
        try: return float(self._inputs[key].text().replace(',','.') or '0')
        except: return 0.0

    def _style_inputs(self):
        for inp in self._inputs.values():
            if not inp.isEnabled(): bg,br='#F0F0F0','#DDD'
            elif inp is self._active_input: bg,br='#EEF4FF','#316AC5'
            else: bg,br='#FFF','#CCC'
            inp.setStyleSheet(f'font-size:20px;font-weight:bold;border:2px solid {br};'
                f'border-radius:6px;padding:0 10px;background:{bg};color:#000;')

    def _activate(self,inp):
        self._active_input=inp; self._np_buf=''; self.np_display.setText('0')
        self._style_inputs()

    # ── нумпад ──
    def _np_press(self,key):
        if self._active_input is None: return
        if key=='.' and '.' in self._np_buf: return
        if len(self._np_buf)>=9: return
        self._np_buf+=key; self.np_display.setText(self._np_buf)

    def _np_back(self):
        self._np_buf=self._np_buf[:-1]; self.np_display.setText(self._np_buf or '0')

    def _np_clear(self):
        self._np_buf=''; self.np_display.setText('0')

    def _np_ok(self):
        if self._active_input is None: return
        try: val=float(self._np_buf or '0')
        except: val=0.0
        self._active_input.setText(f'{val:.2f}')
        self._np_buf=''; self.np_display.setText('0'); self._upd()

    def _np_rest(self):
        """Вписать в активное поле оставшуюся к оплате сумму"""
        if self._active_input is None: return
        others=sum(self._val(k) for k,i in self._inputs.items() if i is not self._active_input)
        self._active_input.setText(f'{max(self.to_pay-others,0):.2f}')
        self._np_buf=''; self.np_display.setText('0'); self._upd()

    # ── режимы ──
    def _mode(self,m):
        self._pay_mode=m
        for k,b in self._mode_btns.items(): b.setChecked(k==m)
        for key,inp in self._inputs.items():
            if m=='mixed':
                inp.setEnabled(True); inp.setText('0.00')
            else:
                inp.setEnabled(key==m)
                inp.setText(f'{self.to_pay:.2f}' if key==m else '0.00')
        first='cash' if m=='mixed' else m
        self._activate(self._inputs[first]); self._upd()

    def _recalc(self):
        self.discount_pct=self.spin_disc.value()
        # Так же, как скидка запишется в базу при оплате (close_table)
        self.to_pay=order_total(self.items,self.discount_pct)
        self.lbl_topay.setText(f'{self.to_pay:.2f}')
        self.lbl_disc.setText(f'Скидка: -{self.total-self.to_pay:.2f}' if self.discount_pct>0 else '')
        self._mode(self._pay_mode)

    def _upd(self):
        paid=sum(self._val(k) for k in self._inputs)
        diff=round(paid-self.to_pay,2)
        if diff<0:
            self.lbl_change.setText(f'Не хватает:  {-diff:.2f}')
            self.lbl_change.setStyleSheet(f'font-size:20px;font-weight:bold;color:{C_RED};')
        else:
            self.lbl_change.setText(f'Сдача:  {diff:.2f}')
            self.lbl_change.setStyleSheet(f'font-size:20px;font-weight:bold;color:{C_GREEN};')

    def _confirm(self):
        cash,card,tr=self._val('cash'),self._val('card'),self._val('transfer')
        paid=cash+card+tr; change=round(paid-self.to_pay,2)
        if change<-0.009:
            QMessageBox.warning(self,'Ошибка',f'Не хватает {-change:.2f}'); return
        if change>cash+0.009:
            QMessageBox.warning(self,'Ошибка','Картой и переводом нельзя оплатить больше суммы заказа — сдача возможна только с наличных'); return
        change=max(change,0.0)
        self.received_cash=cash; self.change=change
        # Наличными в выручку идёт полученное минус сдача
        self.payments={m:round(v,2) for m,v in ((0,cash-change),(1,card),(2,tr)) if v>0.009}
        if not self.payments: self.payments={0:0.0}
        self.accept()


class POSPage(QWidget):
    def __init__(self,user,parent=None):
        super().__init__(parent); self.user=user
        self.user_id=user.get('ID',1); self.user_name=user.get('Name') or user.get('Code','')
        try: objs=get_objects(); self.obj=objs[0] if objs else None
        except: self.obj=None
        try: self.partner=get_default_partner()
        except: self.partner=None
        self.obj_id=self.obj['ID'] if self.obj else 1
        self.partner_id=self.partner['ID'] if self.partner else 1
        self.current_acct=None; self.current_items=[]; self.current_table_num=None
        self._all_goods=[]; self._cat_buttons=[]; self._goods_cache={}
        # Состояния столов: {1: None, 2: acct, ...}
        self._table_accts={i:None for i in range(1,NUM_TABLES+1)}
        self._build_ui()
        QTimer.singleShot(200,self._load_goods)
        QTimer.singleShot(300,self._refresh_tables)

    def _build_ui(self):
        root=QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        self.stack=QStackedWidget(); root.addWidget(self.stack)
        self.stack.addWidget(self._screen_tables())
        self.stack.addWidget(self._screen_order())
        self.stack.setCurrentIndex(0)

    # ── Экран столов ──────────────────────────────────────────────────────────
    def _screen_tables(self):
        w=QWidget(); w.setStyleSheet(f'background:{C_BG};')
        v=QVBoxLayout(w); v.setContentsMargins(20,16,20,16); v.setSpacing(12)
        hdr=QHBoxLayout()
        hdr.addWidget(QLabel('Столы',styleSheet=f'font-size:24px;font-weight:bold;color:{C_BLUE_D};'))
        hdr.addStretch()
        btn_orders=_btn('🧾  Мои заказы',color='#2B579A',fs=14,minh=46)
        btn_orders.setMinimumWidth(130)
        btn_orders.clicked.connect(self._show_my_orders)
        hdr.addWidget(btn_orders)
        btn_min=_btn('—  Свернуть',color='#555555',fs=14,minh=46)
        btn_min.setMinimumWidth(120)
        btn_min.clicked.connect(self._minimize_app)
        hdr.addWidget(btn_min)
        btn_exit=_btn('✕  Выйти',color=C_RED,fs=14,minh=46)
        btn_exit.setMinimumWidth(110)
        btn_exit.clicked.connect(self._exit_app)
        hdr.addWidget(btn_exit)
        v.addLayout(hdr)
        sep=QFrame(); sep.setFrameShape(QFrame.Shape.HLine); sep.setStyleSheet(f'color:{C_BLUE_BTN};')
        v.addWidget(sep)
        # Легенда
        leg=QHBoxLayout(); leg.setSpacing(16)
        for color,label in [('#E8F5E8','Свободен'),('#FFF3CD','Занят')]:
            f=QFrame(); f.setFixedSize(14,14)
            f.setStyleSheet(f'background:{color};border:1px solid #999;border-radius:2px;')
            leg.addWidget(f); leg.addWidget(QLabel(label,styleSheet='font-size:12px;color:#666;'))
        leg.addStretch(); v.addLayout(leg)
        # Сетка столов фиксированного размера
        self.tables_grid=QGridLayout(); self.tables_grid.setSpacing(16)
        self.tables_grid.setAlignment(Qt.AlignmentFlag.AlignTop|Qt.AlignmentFlag.AlignLeft)
        self._table_btns={}
        for i in range(1,NUM_TABLES+1):
            b=QPushButton(f'Стол {i}\nСвободен')
            b.setMinimumSize(130,100); b.setMaximumWidth(220)
            b.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
            self._set_table_style(b,False)
            b.clicked.connect(lambda _,n=i:self._click_table(n))
            self._table_btns[i]=b
            self.tables_grid.addWidget(b,(i-1)//4,(i-1)%4)
        v.addLayout(self.tables_grid)
        v.addStretch()
        v.addWidget(self._status_bar())
        return w

    def _set_table_style(self,btn,occupied,total=0):
        if occupied:
            bg='#FFF3CD'; border='#FFC107'; color=C_BLUE_D
        else:
            bg='#E8F5E8'; border='#4CAF50'; color='#1B5E20'
        btn.setStyleSheet(f'''QPushButton{{
            background:{bg}; color:{color}; border:2px solid {border};
            border-radius:10px; font-size:14px; font-weight:bold; padding:8px;
        }} QPushButton:pressed{{background:#B0C8F0;}}''')

    # ── Экран заказа ──────────────────────────────────────────────────────────
    def _screen_order(self):
        w=QWidget(); w.setStyleSheet(f'background:{C_BG};')
        root=QVBoxLayout(w); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        hdr=QFrame(); hdr.setFixedHeight(56)
        hdr.setStyleSheet(f'background:{C_BLUE};border-bottom:2px solid {C_BLUE_D};')
        hh=QHBoxLayout(hdr); hh.setContentsMargins(10,0,10,0); hh.setSpacing(10)
        bb=_btn('←  Столы',color=C_BLUE_D,fs=13,minh=38); bb.setMinimumWidth(100); bb.clicked.connect(self._go_tables)
        hh.addWidget(bb)
        self.lbl_title=QLabel('Заказ'); self.lbl_title.setStyleSheet('color:#FFF;font-size:18px;font-weight:bold;')
        hh.addWidget(self.lbl_title); hh.addStretch()
        self.lbl_hdr_total=QLabel('0.00')
        self.lbl_hdr_total.setStyleSheet(f'color:{C_YELLOW};font-size:24px;font-weight:bold;background:{C_BLUE_D};padding:4px 14px;border-radius:4px;')
        self.lbl_hdr_total.hide()  # итог показан в блоке ИТОГО справа
        bk=_btn('🍳  НА КУХНЮ',color='#B35C00',fs=14,minh=38); bk.setMinimumWidth(130); bk.clicked.connect(self._to_kitchen)
        hh.addWidget(bk)
        bp=_btn('✔  ОПЛАТИТЬ',color=C_GREEN,fs=14,minh=38); bp.setMinimumWidth(130); bp.clicked.connect(self._pay)
        hh.addWidget(bp); root.addWidget(hdr)
        body=QHBoxLayout(); body.setContentsMargins(0,0,0,0); body.setSpacing(0)
        # Левая: категории + товары
        left=QWidget(); left.setStyleSheet(f'background:{C_BG};')
        lv=QVBoxLayout(left); lv.setContentsMargins(6,6,4,6); lv.setSpacing(6)
        ch=QHBoxLayout(); ch.setSpacing(6)
        cat_frame=QFrame(); cat_frame.setFixedWidth(165)
        cat_frame.setStyleSheet(f'background:{C_WHITE};border:1px solid #CCC;border-radius:4px;')
        cv=QVBoxLayout(cat_frame); cv.setContentsMargins(4,4,4,4); cv.setSpacing(4)
        cv.addWidget(QLabel('Категории',styleSheet=f'color:{C_BLUE_D};font-weight:bold;font-size:12px;'))
        self.cat_scroll=QScrollArea(); self.cat_scroll.setWidgetResizable(True)
        self.cat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.cat_scroll.setStyleSheet('QScrollArea{border:none;background:transparent;}')
        self.cat_inner=QWidget(); self.cat_inner.setStyleSheet('background:transparent;')
        self.cat_vbox=QVBoxLayout(self.cat_inner); self.cat_vbox.setSpacing(4)
        self.cat_vbox.setContentsMargins(0,0,0,0); self.cat_vbox.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.cat_scroll.setWidget(self.cat_inner); cv.addWidget(self.cat_scroll); _touch_scroll(self.cat_scroll)
        ch.addWidget(cat_frame)
        self.goods_stack=QStackedWidget()
        self.goods_stack.setStyleSheet(f'background:{C_WHITE};border:1px solid #CCC;border-radius:4px;')
        ch.addWidget(self.goods_stack,1); lv.addLayout(ch,1); body.addWidget(left,3)
        # Правая: корзина
        right=QFrame(); right.setMinimumWidth(260); right.setMaximumWidth(380)
        right.setStyleSheet(f'background:{C_WHITE};border-left:2px solid #CCC;')
        rv=QVBoxLayout(right); rv.setContentsMargins(8,8,8,8); rv.setSpacing(6)
        rv.addWidget(QLabel('Заказ',styleSheet=f'font-size:14px;font-weight:bold;color:{C_BLUE_D};'))
        self.cart=QTableWidget(); self.cart.setColumnCount(4)
        self.cart.setHorizontalHeaderLabels(['Наименование','Кол','Цена','Сумма'])
        self.cart.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.cart.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.cart.verticalHeader().setVisible(False); self.cart.setAlternatingRowColors(True)
        hh2=self.cart.horizontalHeader(); hh2.setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        for i in (1,2,3): hh2.setSectionResizeMode(i,QHeaderView.ResizeMode.ResizeToContents)
        self.cart.setStyleSheet(f'QTableWidget{{background:{C_WHITE};border:1px solid #CCC;'
            'selection-background-color:#D0E4FF;selection-color:#000;'
            'alternate-background-color:#F5F8FF;gridline-color:#EEE;}'
            'QTableWidget::item{padding:4px 6px;color:#000;font-size:13px;}'
            'QHeaderView::section{background:#F0F0F0;color:#333;font-weight:bold;'
            'font-size:12px;padding:4px 6px;border:none;border-bottom:2px solid #CCC;}')
        rv.addWidget(self.cart,1)
        _orig_resize=self.cart.resizeEvent
        def _cart_resize(e,_o=_orig_resize):
            self.cart.setColumnHidden(2,e.size().width()<330); _o(e)
        self.cart.resizeEvent=_cart_resize
        qh=QHBoxLayout(); qh.setSpacing(6)
        bpl=_btn('＋',color='#E8F4E8',fg=C_GREEN,fs=16,minh=38,bold=True); bpl.setFixedWidth(50); bpl.clicked.connect(self._plus)
        bmi=_btn('－',color='#F4E8E8',fg=C_RED,fs=16,minh=38,bold=True); bmi.setFixedWidth(50); bmi.clicked.connect(self._minus)
        bdl=_btn('Удалить строку',color='#FFEEEE',fg=C_RED,fs=12,minh=38); bdl.clicked.connect(self._del_line)
        qh.addWidget(bmi); qh.addWidget(bpl); qh.addWidget(bdl); rv.addLayout(qh)
        tf=QFrame(); tf.setStyleSheet(f'background:{C_YELLOW};border:1px solid #CCAA00;border-radius:4px;')
        th=QHBoxLayout(tf); th.setContentsMargins(12,8,12,8)
        th.addWidget(QLabel('ИТОГО:',styleSheet=f'font-size:16px;font-weight:bold;color:{C_BLUE_D};'))
        self.lbl_total=QLabel('0.00')
        self.lbl_total.setStyleSheet(f'font-size:24px;font-weight:bold;color:{C_BLUE_D};')
        self.lbl_total.setAlignment(Qt.AlignmentFlag.AlignRight); th.addWidget(self.lbl_total)
        rv.addWidget(tf)
        bc2=_btn('✕  Отменить заказ',color='#FFEEEE',fg=C_RED,fs=12,minh=36); bc2.clicked.connect(self._cancel); rv.addWidget(bc2)
        body.addWidget(right,2); bw=QWidget(); bw.setLayout(body); root.addWidget(bw,1)
        root.addWidget(self._status_bar()); return w

    def _status_bar(self):
        sb=QFrame(); sb.setFixedHeight(24); sb.setStyleSheet(f'background:{C_BLUE};')
        sl=QHBoxLayout(sb); sl.setContentsMargins(12,0,12,0); sl.setSpacing(30)
        from datetime import datetime
        for txt in [f'👤 {self.user_name}',f'📍 {self.obj["Name"] if self.obj else "—"}']:
            l=QLabel(txt); l.setStyleSheet('color:#FFF;font-size:11px;'); sl.addWidget(l)
        clock=QLabel(); clock.setStyleSheet('color:#FFF;font-size:11px;'); sl.addWidget(clock)
        tick=lambda: clock.setText(datetime.now().strftime('%d.%m.%Y %H:%M'))
        tick(); t=QTimer(sb); t.timeout.connect(tick); t.start(10_000)
        sl.addStretch(); return sb

    # ── Загрузка товаров ──────────────────────────────────────────────────────
    def _load_goods(self):
        self._gl=GoodsLoader(); self._gl.done.connect(self._on_goods); self._gl.start()

    def reload_goods(self):
        """Перечитать товары и цены из базы (после правок в карточках)."""
        self._load_goods()

    def _on_goods(self,goods,groups):
        # Убираем старые страницы товаров
        for page in list(getattr(self,'_goods_cache',{}).values()):
            self.goods_stack.removeWidget(page); page.deleteLater()
        self._goods_cache={}
        self._all_goods=goods
        self._groups=groups
        # Группируем товары заранее (быстро, без UI)
        self._goods_by_group={None:goods}
        for g in groups:
            self._goods_by_group[g['ID']]=[x for x in goods if x.get('GroupID')==g['ID']]

        for i in reversed(range(self.cat_vbox.count())):
            w=self.cat_vbox.itemAt(i).widget()
            if w: w.deleteLater()
        self._cat_buttons=[]

        def mc(label,gid):
            b=ElideButton(label); b.setCheckable(True)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
            b.setStyleSheet(f'QPushButton{{background:{C_BG};color:#333;border:1px solid #CCC;'
                'border-radius:4px;font-size:12px;padding:4px 6px;text-align:left;}'
                f'QPushButton:checked{{background:{C_BLUE_BTN};color:#FFF;border-color:{C_BLUE_D};font-weight:bold;}}'
                'QPushButton:pressed{background:#B0C8F0;color:#000;}')
            return b

        ba=mc('Все товары',None); ba.setChecked(True); ba.clicked.connect(lambda:self._show_group(None,ba))
        self.cat_vbox.addWidget(ba); self._cat_buttons.append((None,ba))
        for g in groups:
            b=mc(g['Name'],g['ID']); gid=g['ID']
            b.clicked.connect(lambda _,gi=gid,btn=b:self._show_group(gi,btn))
            self.cat_vbox.addWidget(b); self._cat_buttons.append((gid,b))
        self.cat_vbox.addStretch()

        # Строим только первую страницу сразу
        self._goods_cache={}
        first=self._make_page(goods)
        self._goods_cache[None]=first
        self.goods_stack.addWidget(first)
        self.goods_stack.setCurrentWidget(first)

    def _make_page(self,goods):
        scroll=QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet('QScrollArea{border:none;background:#FFF;}')
        c=FlowGrid()
        # Один стиль на всю страницу (быстрее, чем стиль на каждую кнопку)
        c.setStyleSheet('QWidget{background:#FFF;}'
            'QPushButton{background:#FAFAF5;color:#000;border:1px solid #CCC;'
            'border-radius:6px;font-size:12px;padding:6px 4px;text-align:center;}'
            'QPushButton[noprice="true"]{color:#999;}'
            f'QPushButton:pressed{{background:#D0E4FF;border-color:{C_BLUE_BTN};}}')
        for g in goods:
            name=g.get('Name') or ''; price=float(g.get('_price') or 0)
            ps=f'{price:.2f}' if price>0 else 'нет цены'
            b=ElideButton(name,ps)
            b.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            if price<=0: b.setProperty('noprice',True)
            b.clicked.connect(lambda _,good=g,p=price:self._add_good(good,p))
            c.add(b)
        scroll.setWidget(c); _touch_scroll(scroll); return scroll

    def _show_group(self,gid,clicked):
        for _,b in self._cat_buttons: b.setChecked(False)
        clicked.setChecked(True)
        # Строим страницу лениво при первом открытии
        if gid not in self._goods_cache:
            page=self._make_page(self._goods_by_group.get(gid,[]))
            self._goods_cache[gid]=page
            self.goods_stack.addWidget(page)
        self.goods_stack.setCurrentWidget(self._goods_cache[gid])

    # ── Столы ─────────────────────────────────────────────────────────────────
    def _show_my_orders(self):
        from ui.orders import OrdersPage, OrderDetailDialog
        dlg = __import__('PyQt6.QtWidgets', fromlist=['QDialog']).QDialog(self)
        dlg.setWindowTitle('Мои завершённые заказы')
        dlg.resize(900, 600)
        from PyQt6.QtWidgets import QVBoxLayout
        v = QVBoxLayout(dlg)
        v.setContentsMargins(0,0,0,0)
        page = OrdersPage(self.user)
        v.addWidget(page)
        dlg.exec()

    def _minimize_app(self):
        w = self.window()
        if w: w.showMinimized()

    def _exit_app(self):
        from PyQt6.QtWidgets import QMessageBox, QApplication
        if QMessageBox.question(self,'Выход','Выйти из программы?',
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No
        )==QMessageBox.StandardButton.Yes:
            QApplication.quit()

    def _refresh_tables(self):
        self._tl=TablesLoader(); self._tl.done.connect(self._on_tables); self._tl.start()

    def _on_tables(self,tables):
        # Сбрасываем
        for i in range(1,NUM_TABLES+1): self._table_accts[i]=None
        # Восстанавливаем из БД по TableNum в Note
        unassigned = []
        for t in tables:
            num = t.get('TableNum', 0)
            if 1 <= num <= NUM_TABLES:
                self._table_accts[num] = t['Acct']
            else:
                unassigned.append(t)
        # Заказы без номера стола — на первый свободный
        for t in unassigned:
            for i in range(1,NUM_TABLES+1):
                if self._table_accts[i] is None:
                    self._table_accts[i] = t['Acct']; break
        # Обновляем кнопки
        for i in range(1,NUM_TABLES+1):
            acct=self._table_accts[i]; b=self._table_btns[i]
            if acct:
                t=next((x for x in tables if x['Acct']==acct),None)
                total=float(t['Total']) if t else 0
                b.setText(f'Стол {i}\nЗанят\n{total:.2f}')
                self._set_table_style(b,True,total)
            else:
                b.setText(f'Стол {i}\nСвободен')
                self._set_table_style(b,False)

    def _click_table(self,num):
        acct=self._table_accts[num]
        if acct: self._open_table(acct,num)
        else: self._new_table(num)

    def _new_table(self,num):
        # Номер заказа выдаёт база при добавлении первой позиции (add_item)
        self.current_acct=None; self.current_table_num=num
        self.current_items=[]; self.lbl_title.setText(f'Стол {num}  —  новый заказ')
        self._update_cart(); self.stack.setCurrentIndex(1)

    def _open_table(self,acct,num):
        self.current_acct=acct; self.current_table_num=num
        try: self.current_items=get_table_items(acct)
        except Exception as e: print(f'open_table:{e}'); self.current_items=[]
        self.lbl_title.setText(f'Стол {num}'); self._update_cart(); self.stack.setCurrentIndex(1)

    def _go_tables(self):
        self.current_acct=None; self.current_items=[]; self.current_table_num=None
        self._refresh_tables(); self.stack.setCurrentIndex(0)

    # ── Заказ ─────────────────────────────────────────────────────────────────
    def _add_good(self,good,price):
        # Берём актуальную цену из базы (могла измениться в карточке товара)
        try:
            from db.connection import fetch_one
            r=fetch_one("SELECT PriceOut1 FROM Goods WHERE ID=?",[good['ID']])
            fresh=float((r or {}).get('PriceOut1') or 0)
            if fresh>0: price=fresh
        except Exception as e: print(f'fresh price: {e}')
        # Тот же товар по той же цене — увеличиваем количество в его строке
        ex=next((i for i in self.current_items if i.get('GoodID')==good['ID']
                 and abs(float(i.get('PriceOut') or 0)-price)<0.005),None)
        if ex:
            ok=change_qty(ex['ID'],1)
        else:
            acct=add_item(self.current_acct,good['ID'],1.0,price,
                float(good.get('PriceIn') or 0),self.partner_id,self.obj_id,self.user_id,self.user_id,
                self.current_table_num or 0)
            ok=acct is not None
            if ok and self.current_acct is None:
                self.current_acct=acct; self._table_accts[self.current_table_num]=acct
        if not ok:
            QMessageBox.critical(self,'Ошибка','Не удалось добавить позицию. Проверьте связь с базой и повторите.')
        self._reload_items()

    def _reload_items(self):
        if self.current_acct is None: return
        try:
            self.current_items=get_table_items(self.current_acct)
            if not self.current_items:
                # Пустой заказ в базе не существует — номер выдадим заново
                self._table_accts[self.current_table_num]=None; self.current_acct=None
        except Exception as e:
            print(f'reload_items:{e}')
            QMessageBox.critical(self,'Ошибка',f'Не удалось обновить заказ:\n{e}')
        self._update_cart()

    def _plus(self):
        row=self.cart.currentRow()
        if 0<=row<len(self.current_items): self._chg_qty(self.current_items[row],1)

    def _minus(self):
        row=self.cart.currentRow()
        if 0<=row<len(self.current_items):
            item=self.current_items[row]
            if float(item.get('Qtty') or 0)<=1: self._del_line()
            else: self._chg_qty(item,-1)

    def _chg_qty(self,item,delta):
        # Строка меняется на месте: стол, себестоимость и порядок в корзине сохраняются
        if not change_qty(item['ID'],delta):
            QMessageBox.critical(self,'Ошибка','Не удалось изменить количество. Повторите.')
        self._reload_items()

    def _del_line(self):
        row=self.cart.currentRow()
        if row<0 or row>=len(self.current_items): QMessageBox.information(self,'','Выберите строку'); return
        if not remove_item(self.current_items[row]['ID']):
            QMessageBox.critical(self,'Ошибка','Не удалось удалить строку. Повторите.')
        self._reload_items()

    def _cancel(self):
        if not self.current_acct: self._go_tables(); return
        if QMessageBox.question(self,'Отмена','Отменить весь заказ?',
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            if not cancel_table(self.current_acct):
                QMessageBox.critical(self,'Ошибка','Не удалось отменить заказ. Повторите.'); return
            self._go_tables()

    def _to_kitchen(self):
        if not self.current_items:
            QMessageBox.information(self,'','Добавьте товары в заказ'); return
        from ui.printer import print_kitchen
        ok,err=print_kitchen(self.current_acct,self.current_table_num or 0,self.user_name)
        if ok:
            QMessageBox.information(self,'🍳 На кухню',f'Заказ стола {self.current_table_num or ""} отправлен на печать')
        else:
            QMessageBox.critical(self,'Ошибка печати',f'Не удалось напечатать:\n{err}')

    def _pay(self):
        if not self.current_items: QMessageBox.information(self,'','Добавьте товары'); return
        dlg=PayDialog(self.current_items,self)
        if dlg.exec()==PayDialog.DialogCode.Accepted:
            try:
                total=dlg.total; tp=dlg.to_pay
                ok,err=close_table(self.current_acct,dlg.payments,self.partner_id,self.obj_id,
                                   self.user_id,dlg.discount_pct,tp)
                if ok:
                    names={0:'Наличными',1:'Картой',2:'Переводом'}
                    msg=f'Заказ закрыт\n\nИтого: {total:.2f}\n'
                    if dlg.discount_pct>0: msg+=f'Скидка: {dlg.discount_pct:.1f}% (-{total-tp:.2f})\nК оплате: {tp:.2f}\n'
                    for m in (0,1,2):
                        if m==0 and dlg.received_cash>0: msg+=f'Наличными: {dlg.received_cash:.2f}\n'
                        elif m in dlg.payments and m!=0: msg+=f'{names[m]}: {dlg.payments[m]:.2f}\n'
                    if dlg.change>0: msg+=f'Сдача: {dlg.change:.2f}'
                    QMessageBox.information(self,'✔ Оплачено',msg)
                    # Печать чека
                    try:
                        from ui.printer import print_receipt
                        print_receipt(self.current_acct, CAFE_NAME, dlg.received_cash, dlg.change)
                    except Exception as pe:
                        print(f'print error: {pe}')
                    self._go_tables()
                else: QMessageBox.critical(self,'Ошибка',f'Не удалось провести оплату:\n{err}')
            except Exception as e: QMessageBox.critical(self,'Ошибка',str(e))

    def _update_cart(self):
        self.cart.setRowCount(len(self.current_items)); total=0.0
        for row,item in enumerate(self.current_items):
            lt=float(item.get('LineTotal') or 0); total+=lt
            for col,(val,align) in enumerate([
                (item.get('GoodName') or '',Qt.AlignmentFlag.AlignLeft),
                (fmt_qty(item.get('Qtty')),Qt.AlignmentFlag.AlignCenter),
                (f"{item.get('PriceOut',0):.2f}",Qt.AlignmentFlag.AlignRight),
                (f'{lt:.2f}',Qt.AlignmentFlag.AlignRight),
            ]):
                t=QTableWidgetItem(val); t.setTextAlignment(Qt.AlignmentFlag.AlignVCenter|align)
                if col==3: t.setForeground(QColor(C_BLUE_D)); t.setFont(QFont(FONT,12,QFont.Weight.Bold))
                self.cart.setItem(row,col,t)
        s=f'{total:.2f}'; self.lbl_total.setText(s); self.lbl_hdr_total.setText(s)
