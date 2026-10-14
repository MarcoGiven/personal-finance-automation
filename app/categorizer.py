
import re


# Predictable merchants and recurring expenses only.
CATEGORY_RULES = {
    "Food & Groceries": [
        "fresh grocer",
        "aldi",
        "wegmans",
        "trader joe",
        "whole foods",
        "acme market",
    ],
    "Utilities": [
        "peco",
        "verizon",
        "philadelphia gas works",
    ],
    "Subscriptions": [
        "crunch fitness",
        "movement",
        "spotify",
        "netflix",
    ],
}


# Recognizable credit card payments.
# Ambiguous person-to-person payments are NOT transfers
# by default; they require review.
TRANSFER_KEYWORDS = [
    "credit card payment",
    "payment thank you",
    "autopay payment",
    "discover des:e-payment",
    "capital one des:mobile pmt",
]


def normalize_description(description):
    description = description.casefold()
    description = re.sub(r"\s+", " ", description)
    return description.strip()


def categorize_transaction(description):
    normalized = normalize_description(description)

    for keyword in TRANSFER_KEYWORDS:
        if keyword in normalized:
            return None, "transfer"

    for category, keywords in CATEGORY_RULES.items():
        if any(keyword in normalized for keyword in keywords):
            return category, "expense"

    return None, "expense"
