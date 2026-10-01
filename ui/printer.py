from PyQt6.QtPrintSupport import QPrinter, QPrinterInfo
from PyQt6.QtGui import QPainter, QFont
from PyQt6.QtCore import Qt, QRectF, QMarginsF
from PyQt6.QtGui import QPageSize, QPageLayout
from datetime import datetime
import db.connection as db

PRINTER_NAME = "T58&R58"


def get_printer() -> QPrinter:
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    # Ищем чековый принтер
    for info in QPrinterInfo.availablePrinters():
        n = info.printerName().lower()
        if any(x in n for x in ['t58', 'r58', 'mprint']):
            printer.setPrinterName(info.printerName())
            break
    # Размер страницы 58мм (Custom)
    from PyQt6.QtCore import QSizeF
    page_size = QPageSize(QSizeF(58, 200), QPageSize.Unit.Millimeter)
    layout = QPageLayout(
        page_size,
        QPageLayout.Orientation.Portrait,
        QMarginsF(2, 2, 2, 2),
        QPageLayout.Unit.Millimeter
    )
    printer.setPageLayout(layout)
    return printer


def print_receipt(acct: int, cafe_name: str = "Викинг",
                  received_cash: float = None, change: float = 0.0) -> tuple:
    try:
        items = db.fetch_all("""
            SELECT g.Name as GoodName, o.Qtty, o.PriceOut,
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

        total = sum(float(i.get('LineTotal') or 0) for i in items)
        cash = float((payment or {}).get('Cash') or 0)
        card = float((payment or {}).get('Card') or 0)
        transfer = float((payment or {}).get('Transfer') or 0)
        paid_total = float((payment or {}).get('Total') or 0)
        discount = round(total - paid_total, 2) if paid_total > 0 else 0.0
        shown_cash = received_cash if received_cash is not None else cash

        printer = get_printer()
        painter = QPainter()
        if not painter.begin(printer):
            return False, "Не удалось открыть принтер"

        W = painter.device().width()
        y = 30
        lh = int(W * 0.09)  # высота строки пропорционально ширине

        def draw(txt, size=8, bold=False,
                 align=Qt.AlignmentFlag.AlignLeft, dy_mult=1.0):
            nonlocal y
            f = QFont("Courier New", size)
            f.setBold(bold)
            painter.setFont(f)
            h = int(lh * dy_mult * 1.4)
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
            f = QFont("Courier New", size); f.setBold(bold)
            painter.setFont(f)
            h = int(lh * 1.4)
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

        # Позиции
        for item in items:
            name = (item.get('GoodName') or '')[:22]
            qty  = float(item.get('Qtty') or 0)
            price= float(item.get('PriceOut') or 0)
            lt   = float(item.get('LineTotal') or 0)
            draw(name, size=8)
            y -= lh
            two(f"  {qty:.0f} x {price:.0f}", f"{lt:.2f}", size=8)

        separator()
        if discount > 0.009:
            two("Сумма:", f"{total:.2f}")
            two("Скидка:", f"-{discount:.2f}")
            two("ИТОГО:", f"{paid_total:.2f}", size=10, bold=True)
        else:
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


def print_receipt_dialog(acct: int, parent=None, cafe_name: str = "Викинг"):
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

        printer = get_printer()
        painter = QPainter()
        if not painter.begin(printer):
            return False, "Не удалось открыть принтер"

        W = painter.device().width()
        y = 30
        lh = int(W * 0.09)
        wrap = Qt.TextFlag.TextWordWrap

        def draw(txt, size=9, bold=False, align=Qt.AlignmentFlag.AlignLeft,
                 x=5, width=None):
            nonlocal y
            f = QFont("Arial", size); f.setBold(bold)
            painter.setFont(f)
            w = width or (W - 10)
            rect = painter.boundingRect(QRectF(x, y, w, 10_000),
                                        int(align) | int(wrap), txt)
            painter.drawText(QRectF(x, y, w, rect.height()),
                             int(align) | int(wrap), txt)
            return rect.height()

        def line_step(h):
            nonlocal y
            y += int(h + lh * 0.25)

        def separator(char='-'):
            line_step(draw(char * 32, size=7))

        center = Qt.AlignmentFlag.AlignHCenter
        line_step(draw("НА КУХНЮ", size=14, bold=True, align=center))
        if table_num:
            line_step(draw(f"СТОЛ {table_num}", size=18, bold=True, align=center))
        line_step(draw(f"Заказ № {acct}", size=8, align=center))
        line_step(draw(datetime.now().strftime("%d.%m.%Y  %H:%M"), size=8, align=center))
        if waiter:
            line_step(draw(f"Официант: {waiter}", size=8, align=center))
        separator()

        qty_w = int((W - 10) * 0.18)
        sum_w = int((W - 10) * 0.27)
        name_w = (W - 10) - qty_w - sum_w
        right = Qt.AlignmentFlag.AlignRight
        total = 0.0
        for it in items:
            qty = float(it.get('Qtty') or 0)
            lt = float(it.get('LineTotal') or 0); total += lt
            q = f"{qty:.0f}" if qty == int(qty) else f"{qty:.2f}"
            h1 = draw(f"{q} x", size=10, bold=True, x=5, width=qty_w)
            h2 = draw(it.get('GoodName') or '', size=10, bold=True,
                      x=5 + qty_w, width=name_w)
            h3 = draw(f"{lt:.2f}", size=9, align=right,
                      x=5 + qty_w + name_w, width=sum_w)
            line_step(max(h1, h2, h3))

        separator()
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
