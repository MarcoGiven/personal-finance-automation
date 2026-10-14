
from app.categorizer import categorize_transaction


def test_grocery_category():
    assert categorize_transaction("The Fresh Grocer") == (
        "Food & Groceries", "expense"
    )


def test_subscription_category():
    assert categorize_transaction("Spotify Premium") == (
        "Subscriptions", "expense"
    )


def test_infrequent_purchase_requires_review():
    assert categorize_transaction("Steam Purchase") == (
        None, "expense"
    )


def test_restaurant_requires_review():
    assert categorize_transaction("Chipotle") == (
        None, "expense"
    )


def test_unknown_merchant():
    assert categorize_transaction("Unknown Merchant") == (
        None, "expense"
    )


def test_transfer_detection():
    assert categorize_transaction("Credit Card Payment") == (
        None, "transfer"
    )


def test_utility_category():
    assert categorize_transaction("PECO Energy") == (
        "Utilities", "expense"
    )


def test_gym_membership():
    assert categorize_transaction("Crunch Fitness") == (
        "Subscriptions", "expense"
    )
