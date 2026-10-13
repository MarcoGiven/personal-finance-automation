
import sqlite3

from app.database import get_connection


def add_excluded_status():
    with get_connection() as conn:
        row = conn.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'table' AND name = 'transactions'"
        ).fetchone()

        if not row:
            raise RuntimeError("Transactions table not found.")

        if "'excluded'" in row["sql"]:
            print("Migration already applied.")
            return

        conn.execute("""
            CREATE TABLE transactions_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                account_id TEXT NOT NULL,
                external_id TEXT NOT NULL,
                date TEXT NOT NULL,
                description TEXT NOT NULL,
                amount_cents INTEGER NOT NULL,
                category TEXT,
                transaction_type TEXT NOT NULL
                    CHECK (transaction_type IN
                        ('expense', 'income', 'transfer')),
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN
                        ('pending', 'ready', 'synced', 'excluded')),
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,

                UNIQUE(source, account_id, external_id)
            )
        """)

        conn.execute("""
            INSERT INTO transactions_new
            SELECT * FROM transactions
        """)

        conn.execute("DROP TABLE transactions")
        conn.execute(
            "ALTER TABLE transactions_new RENAME TO transactions"
        )

    print("Migration completed: excluded status supported.")


if __name__ == "__main__":
    add_excluded_status()
