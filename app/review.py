
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.database import get_connection
from app.sheets import VALID_CATEGORIES

router = APIRouter(prefix="/api/review", tags=["Review"])


class TransactionUpdate(BaseModel):
    category: str | None = None
    transaction_type: Literal[
        "expense", "income", "transfer"
    ]


class ApprovalRequest(BaseModel):
    ids: list[int]


def get_transaction(conn, transaction_id):
    row = conn.execute(
        "SELECT * FROM transactions WHERE id = ?",
        (transaction_id,),
    ).fetchone()

    if row is None:
        raise HTTPException(404, "Transaction not found")

    return row


@router.get("/transactions")
def list_transactions(
    status: Literal[
        "pending", "ready", "synced", "excluded", "all"
    ] = "pending"
):
    with get_connection() as conn:
        if status == "all":
            rows = conn.execute(
                """
                SELECT * FROM transactions
                ORDER BY date DESC, id DESC
                """
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM transactions
                WHERE status = ?
                ORDER BY date DESC, id DESC
                """,
                (status,),
            ).fetchall()

    return [dict(row) for row in rows]


@router.patch("/transactions/{transaction_id}")
def update_transaction(
    transaction_id: int,
    update: TransactionUpdate,
):
    if (
        update.transaction_type == "expense"
        and update.category is not None
        and update.category not in VALID_CATEGORIES
    ):
        raise HTTPException(400, "Invalid category")

    category = (
        update.category
        if update.transaction_type == "expense"
        else None
    )

    with get_connection() as conn:
        transaction = get_transaction(conn, transaction_id)

        if transaction["status"] == "synced":
            raise HTTPException(
                409,
                "Already synced transactions cannot be edited",
            )

        conn.execute(
            """
            UPDATE transactions
            SET category = ?,
                transaction_type = ?,
                status = 'pending'
            WHERE id = ?
            """,
            (
                category,
                update.transaction_type,
                transaction_id,
            ),
        )

    return {"status": "updated", "id": transaction_id}


@router.post("/approve")
def approve_transactions(request: ApprovalRequest):
    ids = list(dict.fromkeys(request.ids))

    if not ids:
        raise HTTPException(400, "No transactions selected")

    # Validate the entire selection before making changes.
    with get_connection() as conn:
        for transaction_id in ids:
            transaction = get_transaction(conn, transaction_id)

            if transaction["status"] == "synced":
                raise HTTPException(
                    409,
                    f"Transaction {transaction_id} is already synced",
                )

            if transaction["transaction_type"] != "expense":
                raise HTTPException(
                    400,
                    f"Transaction {transaction_id} is not an expense",
                )

            if transaction["category"] not in VALID_CATEGORIES:
                raise HTTPException(
                    400,
                    f"Transaction {transaction_id} needs a category",
                )

            if transaction["amount_cents"] <= 0:
                raise HTTPException(
                    400,
                    f"Transaction {transaction_id} requires "
                    "income/refund/transfer handling before approval",
                )

        for transaction_id in ids:
            conn.execute(
                """
                UPDATE transactions
                SET status = 'ready'
                WHERE id = ?
                """,
                (transaction_id,),
            )

    return {"approved": len(ids), "ids": ids}


@router.post("/hold")
def hold_transactions(request: ApprovalRequest):
    ids = list(dict.fromkeys(request.ids))

    if not ids:
        raise HTTPException(400, "No transactions selected")

    with get_connection() as conn:
        for transaction_id in ids:
            transaction = get_transaction(conn, transaction_id)

            if transaction["status"] == "synced":
                raise HTTPException(
                    409, "Cannot change a synced transaction"
                )

        for transaction_id in ids:
            conn.execute(
                """
                UPDATE transactions
                SET status = 'pending'
                WHERE id = ?
                """,
                (transaction_id,),
            )

    return {"held": len(ids)}


@router.post("/exclude")
def exclude_transactions(request: ApprovalRequest):
    ids = list(dict.fromkeys(request.ids))

    if not ids:
        raise HTTPException(400, "No transactions selected")

    with get_connection() as conn:
        # Validate all records before updating any of them.
        for transaction_id in ids:
            transaction = get_transaction(conn, transaction_id)

            if transaction["status"] == "synced":
                raise HTTPException(
                    409,
                    "Cannot exclude an already synced transaction"
                )

            if transaction["status"] == "excluded":
                raise HTTPException(
                    409,
                    "Transaction is already excluded"
                )

        for transaction_id in ids:
            conn.execute(
                """
                UPDATE transactions
                SET status = 'excluded'
                WHERE id = ?
                """,
                (transaction_id,),
            )

    return {"excluded": len(ids), "ids": ids}
