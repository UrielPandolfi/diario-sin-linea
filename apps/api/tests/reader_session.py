from fastapi.testclient import TestClient

_DEFAULT_EMAIL = "lector@sinlinea.test"
_DEFAULT_PASSWORD = "clave-segura-1"


def authenticate_reader(
    client: TestClient,
    email: str = _DEFAULT_EMAIL,
    password: str = _DEFAULT_PASSWORD,
) -> None:
    created = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    if created.status_code == 409:
        logged = client.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert logged.status_code == 200, logged.text
        return
    assert created.status_code == 201, created.text
