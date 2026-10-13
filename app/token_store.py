
import json
import os
from pathlib import Path
import tempfile

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
    """Save a new Plaid connection securely."""
    connections = load_connections()

    connections[item_id] = {
        "access_token": access_token,
        "cursor": "",
    }

    save_connections(connections)



def list_connection_ids():
    return list(load_connections().keys())

def save_connections(connections):
    """Atomically save the encrypted connection store."""
    STORE.parent.mkdir(parents=True, exist_ok=True)

    encrypted = get_cipher().encrypt(
        json.dumps(connections).encode()
    )

    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=STORE.parent,
            prefix=".plaid-",
            delete=False,
        ) as file:
            temp_path = Path(file.name)
            os.chmod(temp_path, 0o600)
            file.write(encrypted)
            file.flush()
            os.fsync(file.fileno())

        os.replace(temp_path, STORE)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def save_cursor(item_id, cursor):
    """Update a connection's sync cursor."""
    connections = load_connections()

    if item_id not in connections:
        raise ValueError("Unknown Plaid connection")

    connections[item_id]["cursor"] = cursor
    save_connections(connections)

