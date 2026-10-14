from fastapi.testclient import TestClient

from app.main import app


client = TestClient(
    app,
    client=("127.0.0.1", 50000),
)


def test_local_get():
    response = client.get(
        "/",
        headers={"host": "127.0.0.1:8000"},
    )
    assert response.status_code == 200


def test_untrusted_host():
    response = client.get(
        "/",
        headers={"host": "malicious.example"},
    )
    assert response.status_code == 400


def test_cross_origin_write():
    response = client.post(
        "/api/workflow/sync",
        headers={
            "host": "127.0.0.1:8000",
            "origin": "https://malicious.example",
        },
        json={"month": "October"},
    )
    assert response.status_code == 403


def test_missing_origin():
    response = client.post(
        "/api/workflow/sync",
        headers={"host": "127.0.0.1:8000"},
        json={"month": "October"},
    )
    assert response.status_code == 403


def test_nonlocal_client_rejected():
    remote_client = TestClient(
        app,
        client=("192.0.2.10", 50000),
    )

    response = remote_client.get(
        "/",
        headers={"host": "127.0.0.1:8000"},
    )

    assert response.status_code == 403