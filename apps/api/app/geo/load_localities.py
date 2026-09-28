"""Load Argentine localities from the official GeoRef CSV.

Verified resource (2026-09-28):
https://www.argentina.gob.ar/georef/descarga-de-la-base-completa
https://apis.datos.gob.ar/georef/api/v2.0/localidades.csv

The file is CSV. Ids, province ids and department ids are text (leading zeros
matter). The command upserts by id, so running it again does not duplicate rows.

    python -m app.geo.load_localities
    python -m app.geo.load_localities --file localidades.csv

From Compose, with the API image that contains this code:

    docker compose exec api python -m app.geo.load_localities
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

from app.core.db import SessionLocal
from app.services.geo_localities import OFFICIAL_LOCALITIES_URL, parse_localities_csv, upsert_localities


def load_csv_text(*, file: Path | None, url: str) -> str:
    if file is not None:
        return file.read_text(encoding="utf-8-sig")
    response = httpx.get(url, timeout=120.0, follow_redirects=True)
    response.raise_for_status()
    response.encoding = "utf-8"
    return response.text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Carga localidades de Argentina desde GeoRef.")
    parser.add_argument("--file", type=Path, help="CSV local en lugar de descargar el recurso oficial.")
    parser.add_argument("--url", default=OFFICIAL_LOCALITIES_URL, help="URL del CSV oficial.")
    args = parser.parse_args(argv)
    try:
        payload = load_csv_text(file=args.file, url=args.url)
    except (OSError, httpx.HTTPError) as exc:
        print(f"No se pudo leer el catálogo: {exc}", file=sys.stderr)
        return 1
    rows = parse_localities_csv(payload)
    if not rows:
        print("El CSV no tiene localidades.", file=sys.stderr)
        return 1
    session = SessionLocal()
    try:
        count = upsert_localities(session, rows)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    print(f"Localidades cargadas: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
