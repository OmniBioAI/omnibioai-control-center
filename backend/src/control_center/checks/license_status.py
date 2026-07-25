from __future__ import annotations

import datetime
import os
from typing import Any, Optional

# Same MySQL instance /database uses (see docker-compose.yml's control-center
# environment block). Reads the licenses table directly rather than calling
# license-server's HTTP API -- that API requires ADMIN_KEY (a secret control-
# center doesn't otherwise need), and its only other read path
# (/api/license/validate) has a write side effect (binds machine_id on first
# call), so it's not safe to poll passively.
MYSQL_HOST = os.environ.get("MYSQL_HOST", "mysql")
MYSQL_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
MYSQL_USER = os.environ.get("MYSQL_USER", "root")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "omnibioai")
LICENSES_DATABASE = os.environ.get("LICENSES_DATABASE", "omnibioai_licenses")

_CONNECT_TIMEOUT_S = 3
_EXPIRING_SOON_DAYS = 30

_EMPTY: dict[str, Any] = {"seats_used": 0, "seats_total": 0, "licenses": []}


def get_license_status() -> dict[str, Any]:
    try:
        import pymysql

        conn = pymysql.connect(
            host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER, password=MYSQL_PASSWORD,
            database=LICENSES_DATABASE, connect_timeout=_CONNECT_TIMEOUT_S,
        )
    except Exception:
        return dict(_EMPTY)

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT email, tier, expiry, is_active FROM licenses")
            rows = cur.fetchall()
    except Exception:
        return dict(_EMPTY)
    finally:
        conn.close()

    today = datetime.date.today()
    licenses = []
    seats_used = 0
    for email, tier, expiry, is_active in rows:
        status = _derive_status(expiry, is_active, today)
        if status == "active":
            seats_used += 1
        licenses.append({"org": email, "expires_at": expiry, "status": status})

    return {"seats_used": seats_used, "seats_total": len(rows), "licenses": licenses}


def _derive_status(expiry: str, is_active: int, today: datetime.date) -> str:
    """expiry vs. today decides real validity -- is_active is stuck at 1 for
    rows that are well past their expiry date, so it's not trustworthy alone."""
    expiry_date = _parse_date(expiry)
    if expiry_date is None or not is_active or expiry_date < today:
        return "expired"
    if (expiry_date - today).days <= _EXPIRING_SOON_DAYS:
        return "expiring"
    return "active"


def _parse_date(value: str) -> Optional[datetime.date]:
    try:
        return datetime.date.fromisoformat(value)
    except (TypeError, ValueError):
        return None
