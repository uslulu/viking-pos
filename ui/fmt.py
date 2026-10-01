"""Форматирование чисел для экрана и чеков."""


def fmt_qty(q) -> str:
    """Количество: 2 -> «2», 0.5 -> «0.5», 1.25 -> «1.25»."""
    q = float(q or 0)
    if q == int(q):
        return f"{q:.0f}"
    return f"{q:.3f}".rstrip("0").rstrip(".")


def fmt_price(p) -> str:
    """Цена в строке чека: 150 -> «150», 150.5 -> «150.50»."""
    p = float(p or 0)
    return f"{p:.0f}" if p == int(p) else f"{p:.2f}"
