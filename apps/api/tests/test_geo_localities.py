"""Interest locality: GeoRef catalog, search, and per-reader preference."""

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.main import app
from app.models.geo_locality import GeoLocality
from app.services.geo_localities import parse_localities_csv, upsert_localities
from tests.reader_session import authenticate_reader
from tests.test_public_api import _publish_passed, _seed

_CSV = """\
id,nombre,provincia_id,provincia_nombre,departamento_id,departamento_nombre
82084120,Rosario,82,Santa Fe,82084,Rosario
90084010,Tafí Viejo,90,Tucumán,90084,Tafí Viejo
06805010,San Justo,06,Buenos Aires,06805,La Matanza
82063100,San Justo,82,Santa Fe,82063,San Justo
06539020,San Justo,06,Buenos Aires,06539,San Justo
"""


def _load(session: Session) -> None:
    rows = parse_localities_csv(_CSV)
    assert rows[2]["province_id"] == "06"
    assert any(row["province_name"] == "Tucumán" for row in rows)
    upsert_localities(session, rows)
    upsert_localities(session, parse_localities_csv(_CSV.replace("Simoca", "Simoca")))
    session.commit()
    assert session.scalar(select(func.count()).select_from(GeoLocality)) == 5


def test_catalog_search_is_local_folded_and_marks_homonyms(db_session: Session) -> None:
    _load(db_session)
    with TestClient(app) as anon, TestClient(app) as client:
        denied = anon.get("/api/v1/geo/localities", params={"q": "rosa"})
        assert denied.status_code == 401
        authenticate_reader(client, email="busca@sinlinea.test")
        assert client.get("/api/v1/geo/localities", params={"q": "r"}).json()["items"] == []
        rosario = client.get("/api/v1/geo/localities", params={"q": "RÓS"}).json()["items"]
        assert rosario[0]["id"] == "82084120"
        assert rosario[0]["province_name"] == "Santa Fe"
        assert rosario[0]["country_code"] == "AR"
        assert rosario[0]["show_department"] is False
        tucuman = client.get("/api/v1/geo/localities", params={"q": "tafi"}).json()["items"]
        assert tucuman[0]["name"] == "Tafí Viejo"
        assert tucuman[0]["province_name"] == "Tucumán"
        homonyms = client.get("/api/v1/geo/localities", params={"q": "san justo"}).json()["items"]
        assert len(homonyms) == 3
        by_id = {item["id"]: item for item in homonyms}
        assert by_id["82063100"]["show_department"] is False
        assert by_id["06805010"]["show_department"] is True
        assert by_id["06539020"]["show_department"] is True
        assert by_id["06805010"]["department_name"] == "La Matanza"


def test_preference_is_validated_optional_and_private(db_session: Session) -> None:
    _load(db_session)
    event, _article = _seed(db_session, locality="San Justo", headline="San Justo Santa Fe", hash_key="geo-sf")
    _publish_passed(db_session, event)
    db_session.refresh(event)
    event.province = "Santa Fe"
    other, _other_article = _seed(db_session, locality="San Justo", headline="San Justo Buenos Aires", hash_key="geo-ba")
    _publish_passed(db_session, other)
    db_session.refresh(other)
    other.province = "Buenos Aires"
    db_session.commit()

    with TestClient(app) as ana, TestClient(app) as bruno, TestClient(app) as again:
        authenticate_reader(ana, email="ana-lugar@sinlinea.test")
        authenticate_reader(bruno, email="bruno-lugar@sinlinea.test")
        assert ana.get("/api/v1/auth/session").json()["locality_step"] == "pending"
        missing = ana.put("/api/v1/auth/locality", json={"locality_id": "no-existe"})
        assert missing.status_code == 404
        assert ana.put("/api/v1/auth/locality", json={"locality_id": "texto libre"}).status_code == 404
        saved = ana.put("/api/v1/auth/locality", json={"locality_id": "82063100"})
        assert saved.status_code == 200
        body = saved.json()
        assert body["locality_step"] == "done"
        assert body["locality"]["id"] == "82063100"
        assert body["locality"]["province_id"] == "82"
        assert "password_hash" not in saved.text

        assert bruno.get("/api/v1/auth/session").json()["locality"] is None
        local = ana.get("/api/v1/local", params={"locality": "San Justo", "province": "Santa Fe"})
        headlines = {item["headline"] for item in local.json()["items"]}
        assert headlines == {"San Justo Santa Fe"}
        nearby = ana.get("/api/v1/nearby")
        assert {item["headline"] for item in nearby.json()["items"]} == {"San Justo Santa Fe"}
        assert bruno.get("/api/v1/nearby").status_code == 400

        skipped = bruno.post("/api/v1/auth/locality/skip")
        assert skipped.status_code == 200
        assert skipped.json()["locality"] is None
        assert skipped.json()["locality_step"] == "skipped"

        cleared = ana.delete("/api/v1/auth/locality")
        assert cleared.status_code == 200
        assert cleared.json()["locality"] is None
        assert cleared.json()["locality_step"] == "done"

        authenticate_reader(again, email="ana-lugar@sinlinea.test")
        restored = again.put("/api/v1/auth/locality", json={"locality_id": "82084120"})
        assert restored.status_code == 200
        login = again.post(
            "/api/v1/auth/login",
            json={"email": "ana-lugar@sinlinea.test", "password": "clave-segura-1"},
        )
        assert login.json()["locality"]["name"] == "Rosario"
        assert login.json()["locality_step"] == "done"
        assert again.get("/api/v1/auth/session").json()["locality"]["id"] == "82084120"
        assert bruno.get("/api/v1/auth/session").json()["locality"] is None
