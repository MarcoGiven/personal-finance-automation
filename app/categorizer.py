
import re

CATEGORY_RULES = {
    "Food & Groceries": [
        "jack fergies",
        "wawa",
        "wegmans",
        "aldi",
        "trader joe",
        "whole foods",
        "chipotle",
    ],
    "Utilities": [
        "peco",
        "verizon",
        "septa",
        "pwg",
    ],
    "Subscriptions": [
        "spotify",
        "netflix",
        "crunch membership",
        "movement subscription",
        "apple.com/bill",
    ],
    "Entertainment": [
        "steam",
        "amc theatres",
        "ticketmaster",
    ],
    "Shopping": [
        "amazon",
        "target",
        "best buy",
    ],
}

TRANSFER_KEYWORDS = [
    "payment thank you",
    "credit card payment",
    "autopay payment",
    "online payment to credit card",
    "transfer to savings",
    "transfer from savings",
]


def normalize_description(description):
    """Standardize merchant descriptions for matching."""
    description = description.casefold()
    description = re.sub(r"\s+", " ", description)
    return description.strip()


def categorize_transaction(description):
    normalized = normalize_description(description)

    for keyword in TRANSFER_KEYWORDS:
        if keyword in normalized:
            return "Transfer", "transfer"

    for category, keywords in CATEGORY_RULES.items():
        for keyword in keywords:
            if keyword in normalized:
                return category, "expense"

    return None, "expense"
