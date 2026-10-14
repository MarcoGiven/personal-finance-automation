from app.database import get_connection

with get_connection() as conn:
    venmo = conn.execute(
        """
        SELECT * FROM transactions
        WHERE date = '2026-10-06'
          AND description = 'Venmo'
          AND amount_cents = -10811
          AND transaction_type = 'income'
          AND status = 'synced'
        """
    ).fetchall()

    zelle = conn.execute(
        """
        SELECT * FROM transactions
        WHERE date = '2026-10-05'
          AND description LIKE 'Reimbursement - Zelle%'
          AND amount_cents = -5695
          AND transaction_type = 'expense'
          AND status = 'synced'
        """
    ).fetchall()

    if len(venmo) != 1 or len(zelle) != 1:
        raise RuntimeError(
            "Expected exactly one matching Venmo and Zelle "
            "transaction. No changes applied."
        )

    conn.execute(
        """
        UPDATE transactions
        SET description = 'Reimbursement - Venmo',
            transaction_type = 'expense',
            category = 'Utilities',
            manual_override = 1
        WHERE id = ?
        """,
        (venmo[0]["id"],),
    )

    conn.execute(
        """
        UPDATE transactions
        SET category = 'Utilities',
            manual_override = 1
        WHERE id = ?
        """,
        (zelle[0]["id"],),
    )

print("Both reimbursement records corrected.")