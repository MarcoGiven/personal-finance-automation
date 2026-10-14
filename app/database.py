
import sqlite3
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

ENV = os.getenv("PLAID_ENV", "sandbox")

if ENV not in ("sandbox", "production"):
    raise ValueError("Invalid PLAID_ENV")

DB_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / f"finance_{ENV}.db"
)


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn



def initialize_database():
    with get_connection() as conn:
        # Main transaction table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
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
                manual_override INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,

                UNIQUE(source, account_id, external_id)
            )
        """)

        # Add manual_override to databases created before
        # this feature was implemented.
        columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(transactions)"
            )
        }

        if "manual_override" not in columns:
            conn.execute("""
                ALTER TABLE transactions
                ADD COLUMN manual_override INTEGER NOT NULL DEFAULT 0
            """)

            # Protect classifications in existing records.
            conn.execute("""
                UPDATE transactions
                SET manual_override = 1
            """)

        # Plaid authorizations: never eligible for Sheets export.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS processing_transactions (
                account_id TEXT NOT NULL,
                external_id TEXT NOT NULL,
                date TEXT NOT NULL,
                description TEXT NOT NULL,
                amount_cents INTEGER NOT NULL,
                transaction_type TEXT NOT NULL,
                PRIMARY KEY (account_id, external_id)
            )
        """)

        # Track bank changes requiring manual review.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_conflicts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_id INTEGER,
                account_id TEXT NOT NULL,
                external_id TEXT NOT NULL,
                change_type TEXT NOT NULL,
                old_data TEXT,
                new_data TEXT,
                detected_at TEXT DEFAULT CURRENT_TIMESTAMP,
                resolved INTEGER NOT NULL DEFAULT 0
            )
        """)



def insert_transaction(transaction):
    """Insert a transaction, skipping existing IDs."""

    with get_connection() as conn:
        cursor = conn.execute("""
            INSERT OR IGNORE INTO transactions (
                source,
                account_id,
                external_id,
                date,
                description,
                amount_cents,
                category,
                transaction_type,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            transaction["source"],
            transaction["account_id"],
            transaction["external_id"],
            transaction["date"],
            transaction["description"],
            transaction["amount_cents"],
            transaction["category"],
            transaction["transaction_type"],
            transaction["status"],
        ))

        return cursor.rowcount == 1


def get_transactions(status=None):
    with get_connection() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM transactions "
                "WHERE status = ? ORDER BY date, id",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM transactions ORDER BY date, id"
            ).fetchall()

        return [dict(row) for row in rows]
