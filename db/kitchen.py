from decimal import Decimal

from db.operations import OrderError, _lock_unpaid, _run_order_tx


def _ensure_print_history(cur):
    cur.execute("""
        SELECT 1 FROM sys.tables
        WHERE object_id = OBJECT_ID(N'dbo.PosKitchenPrinted', N'U')
    """)
    if cur.fetchone() is not None:
        return
    # При первом запуске две кассы могут одновременно начать создание таблицы.
    cur.execute("""
        DECLARE @lock_result int;
        EXEC @lock_result = sys.sp_getapplock
            @Resource = N'VikingPOS:KitchenSchema', @LockMode = N'Exclusive',
            @LockOwner = N'Transaction', @LockTimeout = 5000;
        IF @lock_result < 0
            THROW 50001, N'Не удалось заблокировать подготовку истории кухонных чеков', 1;

        IF OBJECT_ID(N'dbo.PosKitchenPrinted', N'U') IS NULL
            CREATE TABLE dbo.PosKitchenPrinted (
                OperationID bigint NOT NULL PRIMARY KEY,
                PrintedQty decimal(28, 12) NOT NULL
            );
    """)


def send_kitchen_items(acct, print_items):
    """Передаёт принтеру добавленное количество и сохраняет успешную отправку."""
    def prepare(cur):
        _ensure_print_history(cur)
        return True

    def work(cur):
        # Транзакция удерживает блокировки до завершения передачи принтеру.
        _lock_unpaid(cur, acct)
        cur.execute("""
            SELECT o.ID, o.GoodID, g.Name AS GoodName,
                   CAST(o.Qtty AS decimal(28, 12)) AS Qtty, o.PriceOut,
                   p.PrintedQty
            FROM Operations o WITH (UPDLOCK, HOLDLOCK)
            JOIN Goods g ON o.GoodID = g.ID
            LEFT JOIN dbo.PosKitchenPrinted p ON p.OperationID = o.ID
            WHERE o.OperType = 2 AND o.Acct = ?
            ORDER BY o.ID
        """, [acct])
        items = {}
        printed = []
        for row in cur.fetchall():
            qty = row.Qtty
            previous_qty = row.PrintedQty or Decimal(0)
            delta = qty - previous_qty
            if delta <= 0:
                continue
            item = items.setdefault(row.GoodID, {
                "GoodName": row.GoodName, "Qtty": Decimal(0), "LineTotal": Decimal(0)
            })
            item["Qtty"] += delta
            item["LineTotal"] += delta * Decimal(str(row.PriceOut or 0))
            printed.append((qty, row.ID, row.PrintedQty is not None))

        if not printed:
            return False

        for qty, operation_id, has_history in printed:
            if has_history:
                cur.execute("UPDATE dbo.PosKitchenPrinted SET PrintedQty = ? WHERE OperationID = ?",
                            [qty, operation_id])
            else:
                cur.execute("INSERT INTO dbo.PosKitchenPrinted (PrintedQty, OperationID) VALUES (?, ?)",
                            [qty, operation_id])
        ok, error = print_items(list(items.values()))
        if not ok:
            raise OrderError(error or "Принтер не принял кухонный чек")
        return True

    ready, error = _run_order_tx("prepare_kitchen_history", prepare)
    if not ready:
        return False, error
    sent, error = _run_order_tx("send_kitchen_items", work)
    return bool(sent), error
