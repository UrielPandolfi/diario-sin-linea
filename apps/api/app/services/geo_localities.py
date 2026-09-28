"""Local catalog of Argentine localities. Search never calls GeoRef."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Mapping

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.text import normalize_name
from app.models.geo_locality import GeoLocality
from app.models.reader import Reader

SEARCH_LIMIT = 10
MIN_QUERY = 2

OFFICIAL_LOCALITIES_URL = "https://apis.datos.gob.ar/georef/api/v2.0/localidades.csv"
# Columns verified on 2026-09-28 against the v2.0 CSV download:
# id, nombre, provincia_id, provincia_nombre, departamento_id, departamento_nombre


def fold_query(value: str | None) -> str:
    return normalize_name(value or "")


def _like_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def parse_localities_csv(payload: str) -> list[dict[str, str]]:
    """Read the official GeoRef localidades CSV. Ids stay text."""
    reader = csv.DictReader(io.StringIO(payload))
    by_id: dict[str, dict[str, str]] = {}
    for raw in reader:
        locality_id = (raw.get("id") or "").strip()
        name = (raw.get("nombre") or "").strip()
        province_id = (raw.get("provincia_id") or "").strip()
        province_name = (raw.get("provincia_nombre") or "").strip()
        department_id = (raw.get("departamento_id") or "").strip()
        department_name = (raw.get("departamento_nombre") or "").strip()
        folded = fold_query(name)
        if not locality_id or not folded or not province_id or not province_name:
            continue
        by_id[locality_id] = {
            "id": locality_id,
            "name": name,
            "name_folded": folded,
            "province_id": province_id,
            "province_name": province_name,
            "department_id": department_id,
            "department_name": department_name or province_name,
            "country_code": "AR",
        }
    return list(by_id.values())


def upsert_localities(session: Session, rows: Iterable[Mapping[str, str]]) -> int:
    """Insert or update by official id. Repeat runs do not duplicate rows."""
    payload = [dict(row) for row in rows]
    if not payload:
        return 0
    statement = insert(GeoLocality).values(payload)
    statement = statement.on_conflict_do_update(
        index_elements=[GeoLocality.id],
        set_={
            "name": statement.excluded.name,
            "name_folded": statement.excluded.name_folded,
            "province_id": statement.excluded.province_id,
            "province_name": statement.excluded.province_name,
            "department_id": statement.excluded.department_id,
            "department_name": statement.excluded.department_name,
            "country_code": statement.excluded.country_code,
        },
    )
    session.execute(statement)
    return len(payload)


def _public(row: GeoLocality, *, show_department: bool) -> dict[str, str | bool]:
    return {
        "id": row.id,
        "name": row.name,
        "province_id": row.province_id,
        "province_name": row.province_name,
        "department_id": row.department_id,
        "department_name": row.department_name,
        "country_code": row.country_code,
        "show_department": show_department,
    }


def _department_flags(session: Session, rows: list[GeoLocality]) -> dict[tuple[str, str], bool]:
    if not rows:
        return {}
    keys = {(row.name_folded, row.province_id) for row in rows}
    clauses = [
        and_(GeoLocality.name_folded == name, GeoLocality.province_id == province_id)
        for name, province_id in keys
    ]
    counts = session.execute(
        select(GeoLocality.name_folded, GeoLocality.province_id, func.count())
        .where(or_(*clauses))
        .group_by(GeoLocality.name_folded, GeoLocality.province_id)
    )
    return {(name, province_id): count > 1 for name, province_id, count in counts}


def search_localities(session: Session, query: str) -> list[dict[str, str | bool]]:
    folded = fold_query(query)[:80]
    if len(folded) < MIN_QUERY:
        return []
    literal = _like_literal(folded)
    prefix = f"{literal}%"
    contains = f"%{literal}%"
    rows = list(
        session.scalars(
            select(GeoLocality)
            .where(GeoLocality.name_folded.like(contains, escape="\\"))
            .order_by(
                GeoLocality.name_folded.like(prefix, escape="\\").desc(),
                func.length(GeoLocality.name_folded),
                GeoLocality.name_folded,
                GeoLocality.province_name,
                GeoLocality.id,
            )
            .limit(SEARCH_LIMIT)
        )
    )
    flags = _department_flags(session, rows)
    return [
        _public(row, show_department=flags.get((row.name_folded, row.province_id), False))
        for row in rows
    ]


def reader_locality_payload(session: Session, reader: Reader) -> dict[str, str | bool] | None:
    if not reader.interest_locality_id:
        return None
    row = session.get(GeoLocality, reader.interest_locality_id)
    if row is None:
        return None
    flags = _department_flags(session, [row])
    return _public(row, show_department=flags.get((row.name_folded, row.province_id), False))
