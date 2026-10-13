
from app.categorizer import categorize_transaction


def test_food_category():
    assert categorize_transaction("WAWA #1234") == (
        "Food & Groceries", "expense"
    )


def test_subscription_category():
    assert categorize_transaction("Spotify Premium") == (
        "Subscriptions", "expense"
    )


def test_entertainment_category():
    assert categorize_transaction("Steam Purchase") == (
        "Entertainment", "expense"
    )


def test_unknown_merchant():
    assert categorize_transaction("Unknown Merchant") == (
        None, "expense"
    )


def test_transfer_detection():
    assert categorize_transaction("Credit Card Payment") == (
        "Transfer", "transfer"
    )
