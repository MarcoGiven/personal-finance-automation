
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Literal

from app.database import get_connection

router = APIRouter(prefix="/api/conflicts", tags=["Conflicts"])


class Resolution(BaseModel):
    action: Literal[
        "accept_plaid",
        "keep_existing",
        "confirm_reconciled",
    ]


@router.get("")
def list_conflicts():
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                c.*,
                t.description,
                t.amount_cents,
                t.date,
                t.category,
                t.status
            FROM sync_conflicts c
            LEFT JOIN transactions t
                ON c.transaction_id = t.id
            WHERE c.resolved = 0
            ORDER BY c.detected_at DESC, c.id DESC
            """
        ).fetchall()

    results = []

    for row in rows:
        item = dict(row)
        item["old_data"] = json.loads(
            item["old_data"] or "{}"
        )
        item["new_data"] = json.loads(
            item["new_data"] or "{}"
        )
        results.append(item)

    return results


@router.post("/{conflict_id}/resolve")
def resolve_conflict(conflict_id: int, request: Resolution):
    with get_connection() as conn:
        conflict = conn.execute(
            """
            SELECT * FROM sync_conflicts
            WHERE id = ? AND resolved = 0
            """,
            (conflict_id,),
        ).fetchone()

        if conflict is None:
            raise HTTPException(404, "Unresolved conflict not found")

        transaction = conn.execute(
            "SELECT * FROM transactions WHERE id = ?",
            (conflict["transaction_id"],),
        ).fetchone()

        if transaction is None:
            raise HTTPException(
                409, "Original transaction no longer exists"
            )

        status = transaction["status"]
        action = request.action

        # A previously exported transaction must be
        # reconciled with Google Sheets manually.
        if status == "synced":
            if action != "confirm_reconciled":
                raise HTTPException(
                    409,
                    "Transaction was already exported. "
                    "Reconcile Google Sheets before confirming."
                )
        elif action == "confirm_reconciled":
            raise HTTPException(
                400,
                "This action is only for synced transactions"
            )

        elif action == "accept_plaid":
            if conflict["change_type"] == "removed":
                conn.execute(
                    "DELETE FROM transactions WHERE id = ?",
                    (transaction["id"],),
                )
            elif conflict["change_type"] == "modified":
                new = json.loads(conflict["new_data"])

                # Apply only bank-authoritative fields.
                # Preserve the manually selected category,
                # transaction type, and description.
                conn.execute(
                    """
                    UPDATE transactions
                    SET date = ?,
                        amount_cents = ?,
                        status = 'pending',
                        manual_override = 1
                    WHERE id = ?
                    """,
                    (
                        new["date"],
                        new["amount_cents"],
                        transaction["id"],
                    ),
                )
            else:
                raise HTTPException(
                    400, "Unsupported conflict type"
                )

        elif action == "keep_existing" and status == "ready":
            # Require reapproval before exporting an amount
            # that disagrees with the latest bank data.
            conn.execute(
                """
                UPDATE transactions
                SET status = 'pending',
                    manual_override = 1
                WHERE id = ?
                """,
                (transaction["id"],),
        )

        # "keep_existing" leaves the transaction unchanged.

        conn.execute(
            """
            UPDATE sync_conflicts
            SET resolved = 1
            WHERE id = ?
            """,
            (conflict_id,),
        )

    return {"status": "resolved", "action": action}
