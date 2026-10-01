from PyQt6.QtPrintSupport import QPrinter, QPrinterInfo
from PyQt6.QtGui import QPainter, QFont
from PyQt6.QtCore import Qt, QRectF, QMarginsF, QSizeF
from PyQt6.QtGui import QPageSize, QPageLayout
from datetime import datetime
import db.connection as db
from app_config import CAFE_NAME
from ui.fmt import fmt_qty, fmt_price

PRINTER_NAME = "T58&R58"

PAGE_MIN_MM = 200     # как раньше: короткие чеки печатаются так же
LINE_MM = 4.9         # высота строки чека (lh = 9% от ширины 54 мм)


def get_printer(height_mm: float = PAGE_MIN_MM) -> QPrinter:
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    # Ищем чековый принтер
    for info in QPrinterInfo.availablePrinters():
        n = info.printerName().lower()
        if any(x in n for x in ['t58', 'r58', 'mprint']):
            printer.setPrinterName(info.printerName())
            break
    # Лента 58 мм; длина — под содержимое, но не меньше PAGE_MIN_MM
    page_size = QPageSize(QSizeF(58, max(PAGE_MIN_MM, height_mm)),
                          QPageSize.Unit.Millimeter)
    layout = QPageLayout(
        page_size,
        QPageLayout.Orientation.Portrait,
        QMarginsF(2, 2, 2, 2),
        QPageLayout.Unit.Millimeter
    )
    printer.setPageLayout(layout)
    return printer


def _original_price(item) -> float:
    """Цена до скидки. При оплате со скидкой в PriceOut пишется цена
    со скидкой, а в Discount — процент (см. db.operations.close_table)."""
    price = float(item.get('PriceOut') or 0)
    d = float(item.get('Discount') or 0)
    if d <= 0:
        return price
    if d < 100:
        return round(price * 100 / (100 - d), 2)
    return float(item.get('ListPrice') or 0)


def print_receipt(acct: int, cafe_name: str = CAFE_NAME,
                  received_cash: float = None, change: float = 0.0) -> tuple:
    try:
        items = db.fetch_all("""
            SELECT g.Name as GoodName, o.Qtty, o.PriceOut, o.Discount,
                   g.PriceOut1 as ListPrice,
                   o.Qtty * o.PriceOut as LineTotal
            FROM Operations o
            JOIN Goods g ON o.GoodID = g.ID
            WHERE o.OperType = 2 AND o.Acct = ?
            ORDER BY o.ID
        """, [acct])

        if not items:
            return False, "Заказ не найден"

        payment = db.fetch_one("""
            SELECT
                SUM(CASE WHEN Mode=0 THEN Qtty ELSE 0 END) as Cash,
                SUM(CASE WHEN Mode=1 THEN Qtty ELSE 0 END) as Card,
                SUM(CASE WHEN Mode=2 THEN Qtty ELSE 0 END) as Transfer,
                SUM(Qtty) as Total
            FROM Payments WHERE OperType=2 AND Acct=?
        """, [acct])

        total = round(sum(float(i.get('LineTotal') or 0) for i in items), 2)
        orig_total = round(sum(float(i.get('Qtty') or 0) * _original_price(i)
                               for i in items), 2)
        discount = round(orig_total - total, 2)
        disc_pct = max(float(i.get('Discount') or 0) for i in items)
        cash = float((payment or {}).get('Cash') or 0)
        card = float((payment or {}).get('Card') or 0)
        transfer = float((payment or {}).get('Transfer') or 0)
        shown_cash = received_cash if received_cash is not None else cash

        # Шапка ~5 строк, по 2 на позицию, итоги и оплата ~10
        printer = get_printer((5 + 2 * len(items) + 12) * LINE_MM + 10)
        painter = QPainter()
        if not painter.begin(printer):
            return False, "Не удалось открыть принтер"

        W = painter.device().width()
        H = painter.device().height()
        y = 30
        lh = int(W * 0.09)  # высота строки пропорционально ширине

        def room(h):
            """Если строка не помещается на странице — следующая страница."""
            nonlocal y
            if y + h > H - 10:
                printer.newPage()
                y = 30

        def draw(txt, size=8, bold=False,
                 align=Qt.AlignmentFlag.AlignLeft, dy_mult=1.0):
            nonlocal y
            h = int(lh * dy_mult * 1.4)
            room(h)
            f = QFont("Courier New", size)
            f.setBold(bold)
            painter.setFont(f)
            painter.drawText(
                QRectF(5, y, W - 10, h),
                align | Qt.AlignmentFlag.AlignVCenter,
                txt
            )
            y += int(lh * dy_mult)

        def separator(char='-'):
            draw(char * 30, size=7, dy_mult=0.7)

        def two(left, right, size=8, bold=False):
            nonlocal y
            h = int(lh * 1.4)
            room(h)
            f = QFont("Courier New", size); f.setBold(bold)
            painter.setFont(f)
            lw = int((W - 10) * 0.65)
            rw = int((W - 10) * 0.35)
            painter.drawText(QRectF(5, y, lw, h),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, left)
            painter.drawText(QRectF(5 + lw, y, rw, h),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, right)
            y += lh

        # Шапка
        draw(cafe_name, size=12, bold=True, align=Qt.AlignmentFlag.AlignHCenter)
        draw(f"Чек № {acct}", size=8, align=Qt.AlignmentFlag.AlignHCenter)
        draw(datetime.now().strftime("%d.%m.%Y  %H:%M"),
             size=8, align=Qt.AlignmentFlag.AlignHCenter)
        separator()

        # Позиции: название отдельной строкой, под ним «кол-во x цена   сумма»
        for item in items:
            qty = float(item.get('Qtty') or 0)
            price = _original_price(item)
            draw((item.get('GoodName') or '')[:30], size=8)
            two(f"  {fmt_qty(qty)} x {fmt_price(price)}", f"{qty * price:.2f}", size=8)

        separator()
        if discount > 0.009:
            two("Сумма:", f"{orig_total:.2f}")
            two(f"Скидка {disc_pct:g}%:", f"-{discount:.2f}")
        two("ИТОГО:", f"{total:.2f}", size=10, bold=True)

        if shown_cash > 0:
            two("Наличными:", f"{shown_cash:.2f}")
            if change and change > 0:
                two("Сдача:", f"{change:.2f}")
        if card > 0:
            two("Картой:", f"{card:.2f}")
        if transfer > 0:
            two("Переводом:", f"{transfer:.2f}")

        separator('=')
        draw("Спасибо за посещение!", size=8, bold=True,
             align=Qt.AlignmentFlag.AlignHCenter)
        y += lh * 2  # отступ перед отрезом

        painter.end()
        return True, ""

    except Exception as e:
        return False, str(e)


def print_receipt_dialog(acct: int, parent=None, cafe_name: str = CAFE_NAME):
    from PyQt6.QtWidgets import QMessageBox
    ok, err = print_receipt(acct, cafe_name)
    if ok:
        QMessageBox.information(parent, "✔ Печать",
            f"Чек № {acct} отправлен на принтер")
    else:
        QMessageBox.critical(parent, "Ошибка печати",
            f"Не удалось напечатать чек:\n{err}")


def print_kitchen(acct: int, table_num: int = 0, waiter: str = "") -> tuple:
    """Кухонный чек: весь заказ стола, без цен, крупным шрифтом."""
    try:
        items = db.fetch_all("""
            SELECT g.Name as GoodName, SUM(o.Qtty) as Qtty,
                   SUM(o.Qtty * o.PriceOut) as LineTotal
            FROM Operations o
            JOIN Goods g ON o.GoodID = g.ID
            WHERE o.OperType = 2 AND o.Acct = ?
            GROUP BY g.Name, o.GoodID
            ORDER BY MIN(o.ID)
        """, [acct])
        if not items:
            return False, "В заказе нет позиций"

        # Шапка ~60 мм, позиция крупным шрифтом с переносом — до 3 строк (~15 мм)
        printer = get_printer(60 + 15 * len(items) + 30)
        painter = QPainter()
        if not painter.begin(printer):
            return False, "Не удалось открыть принтер"

        W = painter.device().width()
        H = painter.device().height()
        y = 30
        lh = int(W * 0.09)
        wrap = Qt.TextFlag.TextWordWrap

        def measure(txt, size, bold, align, w):
            f = QFont("Arial", size); f.setBold(bold)
            painter.setFont(f)
            return painter.boundingRect(QRectF(0, 0, w, 10_000),
                                        int(align) | int(wrap), txt).height()

        def room(h):
            """Если блок не помещается на странице — следующая страница."""
            nonlocal y
            if y + h > H - 10:
                printer.newPage()
                y = 30

        def draw(txt, size=9, bold=False, align=Qt.AlignmentFlag.AlignLeft,
                 x=5, width=None):
            w = width or (W - 10)
            h = measure(txt, size, bold, align, w)
            painter.drawText(QRectF(x, y, w, h), int(align) | int(wrap), txt)
            return h

        def line_step(h):
            nonlocal y
            y += int(h + lh * 0.25)

        def line(txt, size=9, bold=False, align=Qt.AlignmentFlag.AlignLeft):
            room(measure(txt, size, bold, align, W - 10))
            line_step(draw(txt, size, bold, align))

        def separator(char='-'):
            line(char * 32, size=7)

        center = Qt.AlignmentFlag.AlignHCenter
        line("НА КУХНЮ", size=14, bold=True, align=center)
        if table_num:
            line(f"СТОЛ {table_num}", size=18, bold=True, align=center)
        line(f"Заказ № {acct}", size=8, align=center)
        line(datetime.now().strftime("%d.%m.%Y  %H:%M"), size=8, align=center)
        if waiter:
            line(f"Официант: {waiter}", size=8, align=center)
        separator()

        qty_w = int((W - 10) * 0.18)
        sum_w = int((W - 10) * 0.27)
        name_w = (W - 10) - qty_w - sum_w
        right = Qt.AlignmentFlag.AlignRight
        left = Qt.AlignmentFlag.AlignLeft
        total = 0.0
        for it in items:
            qty = float(it.get('Qtty') or 0)
            lt = float(it.get('LineTotal') or 0); total += lt
            name = it.get('GoodName') or ''
            # Строка позиции целиком на одной странице
            room(measure(name, 10, True, left, name_w))
            h1 = draw(f"{fmt_qty(qty)} x", size=10, bold=True, x=5, width=qty_w)
            h2 = draw(name, size=10, bold=True, x=5 + qty_w, width=name_w)
            h3 = draw(f"{lt:.2f}", size=9, align=right,
                      x=5 + qty_w + name_w, width=sum_w)
            line_step(max(h1, h2, h3))

        separator()
        room(measure("ИТОГО:", 12, True, left, W - 10))
        h1 = draw("ИТОГО:", size=12, bold=True, x=5, width=int((W - 10) * 0.5))
        h2 = draw(f"{total:.2f}", size=12, bold=True, align=right,
                  x=5 + int((W - 10) * 0.5), width=int((W - 10) * 0.5))
        line_step(max(h1, h2))
        separator('=')
        y += lh * 2
        painter.end()
        return True, ""
    except Exception as e:
        return False, str(e)
