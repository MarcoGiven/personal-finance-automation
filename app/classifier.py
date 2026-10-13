
from app.categorizer import categorize_transaction


def normalize(value):
    """Normalize descriptions and Plaid enum values."""
    return str(value or "").strip().casefold()


def classify_transaction(transaction, account):
    """
    Classify a Plaid transaction using account metadata,
    Plaid categories, and merchant rules.

    Returns: (transaction_type, category, signed_amount)
    """

    name = normalize(transaction.name)
    merchant = normalize(transaction.merchant_name)
    description = f"{name} {merchant}"

    account_type = normalize(account.type)
    account_subtype = normalize(account.subtype)

    pfc = transaction.personal_finance_category

    primary = normalize(pfc.primary) if pfc else ""
    detailed = normalize(pfc.detailed) if pfc else ""

    amount = transaction.amount

    # 1. Explicit credit card payments
    credit_payment = (
        "credit_card_payment" in detailed
        or any(keyword in description for keyword in [
            "credit card payment",
            "autopay payment",
            "payment thank you",
            "payment received",
        ])
    )

    if credit_payment:
        return "transfer", None, amount

    # 2. Explicit account transfers
    account_transfer = (
        "account_transfer" in detailed
        or "transfer_in" in detailed
        or "transfer_out" in detailed
        or any(keyword in description for keyword in [
            "transfer to savings",
            "transfer from savings",
        ])
    )

    if account_transfer:
        return "transfer", None, amount

    # 3. Interest earned
    if amount < 0 and (
        "interest_earned" in detailed
        or "interest income" in description
        or "interest payment" in description
    ):
        return "income", None, amount

    # 4. Savings account movements
    if account_type == "depository" and account_subtype == "savings":
        return "transfer", None, amount

    # 5. Negative credit card transactions
    # Could be refunds, statement credits, rewards, etc.
    # Preserve the negative amount for review.
    if account_type == "credit" and amount < 0:
        return "expense", None, amount

    # 6. Incoming checking transactions
    if amount < 0:
        if (
            "income" in primary
            or "wages" in detailed
            or "payroll" in description
        ):
            return "income", None, amount

        # Unknown incoming money: don't assume it's income.
        return "transfer", None, amount

    # 7. Outgoing purchases
    category, inferred_type = categorize_transaction(
        transaction.name or transaction.merchant_name or ""
    )

    if inferred_type == "transfer":
        return "transfer", None, amount

    return "expense", category, amount
