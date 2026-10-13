
import json
import os
from pathlib import Path

from cryptography.fernet import Fernet

STORE = Path(__file__).resolve().parent.parent / "data" / "plaid_tokens.enc"


def get_cipher():
    key = os.environ["FINANCE_ENCRYPTION_KEY"]
    return Fernet(key.encode())


def load_connections():
    if not STORE.exists():
        return {}

    encrypted = STORE.read_bytes()
    plaintext = get_cipher().decrypt(encrypted)
    return json.loads(plaintext)


def save_connection(item_id, access_token):
    connections = load_connections()

    connections[item_id] = {
        "access_token": access_token,
        "cursor": "",
    }

    STORE.parent.mkdir(parents=True, exist_ok=True)

    encrypted = get_cipher().encrypt(
        json.dumps(connections).encode()
    )

    # Restrict access to the current OS user.
    fd = os.open(
        STORE,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o600,
    )

    with os.fdopen(fd, "wb") as file:
        file.write(encrypted)

    os.chmod(STORE, 0o600)


def list_connection_ids():
    return list(load_connections().keys())
