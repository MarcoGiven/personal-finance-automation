import re
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.database import get_connection
from app.sheets import VALID_CATEGORIES
from app.accounts import get_account_names

router = APIRouter(prefix="/api/review", tags=["Review"])


class TransactionUpdate(BaseModel):
    category: str | None = None
    transaction_type: Literal[
        "expense", "income", "transfer"
    ]


class ApprovalRequest(BaseModel):
    ids: list[int]


class ReimbursementRequest(BaseModel):
    category: str


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
    ] = "pending",
    month: str | None = None,
):
    if month and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(
            400, "Month must be in YYYY-MM format"
        )

    query = "SELECT * FROM transactions WHERE 1=1"
    parameters = []

    if status != "all":
        query += " AND status = ?"
        parameters.append(status)

    if month:
        query += " AND date LIKE ?"
        parameters.append(f"{month}-%")

    query += " ORDER BY date DESC, id DESC"

    with get_connection() as conn:
        rows = conn.execute(
            query, parameters
        ).fetchall()

    account_names = get_account_names()

    return [
        {
            **dict(row),
            "account_name": account_names.get(
                row["account_id"],
                "Unknown Account",
            ),
        }
        for row in rows
    ]



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
                status = 'pending',
                manual_override = 1
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

    with get_connection() as conn:
        for transaction_id in ids:
            transaction = get_transaction(conn, transaction_id)

            if transaction["status"] in ("synced", "excluded"):
                raise HTTPException(
                    409,
                    f"Transaction {transaction_id} cannot be approved",
                )

            transaction_type = transaction["transaction_type"]

            if transaction_type == "transfer":
                raise HTTPException(
                    400,
                    f"Transaction {transaction_id} is a transfer. "
                    "Exclude it instead.",
                )

            if transaction_type == "expense":
                if transaction["category"] not in VALID_CATEGORIES:
                    raise HTTPException(
                        400,
                        f"Transaction {transaction_id} needs a category",
                    )

            if transaction["amount_cents"] == 0:
                raise HTTPException(
                    400,
                    f"Transaction {transaction_id} has a zero amount",
                )

        for transaction_id in ids:
            conn.execute(
                """
                UPDATE transactions
                SET status = 'ready',
                    manual_override = 1
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
                SET status = 'pending',
                    manual_override = 1
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
                SET status = 'excluded',
                    manual_override = 1
                WHERE id = ?
                """,
                (transaction_id,),
            )

    return {"excluded": len(ids), "ids": ids}


@router.post("/transactions/{transaction_id}/reimbursement")
def mark_reimbursement(
    transaction_id: int,
    request: ReimbursementRequest,
):
    if request.category not in VALID_CATEGORIES:
        raise HTTPException(
            400, "A valid expense category is required"
        )

    with get_connection() as conn:
        transaction = get_transaction(conn, transaction_id)

        if transaction["status"] in ("synced", "excluded"):
            raise HTTPException(
                409,
                "This transaction cannot be modified"
            )

        # Plaid uses negative amounts for incoming money.
        if transaction["amount_cents"] >= 0:
            raise HTTPException(
                400,
                "Only incoming payments can be reimbursements"
            )

        description = transaction["description"]

        if not description.startswith("Reimbursement - "):
            description = f"Reimbursement - {description}"

        conn.execute(
            """
            UPDATE transactions
            SET description = ?,
                transaction_type = 'expense',
                category = ?,
                status = 'pending',
                manual_override = 1
            WHERE id = ?
            """,
            (
                description,
                request.category,
                transaction_id,
            ),
        )

    return {
        "status": "pending",
        "id": transaction_id,
        "category": request.category,
        "transaction_type": "expense",
    }

