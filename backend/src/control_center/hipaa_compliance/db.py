"""SQLite persistence for the Admin Console's HIPAA Compliance history.

control-center has no database of its own anywhere else in this repo --
confirmed by reading every api/routes_*_proxy.py (each one is a pure
HTTP relay to another service, e.g. routes_audit_proxy.py's own module
docstring) and core/settings.py directly. This package is the first
ORM/database code this service has ever owned. pymysql (backend/
pyproject.toml) is already a dependency, but only for raw, ad-hoc health-
check connections to *other* services' databases (checks/database_status.
py, checks/license_status.py, checks/usage_status.py) -- never an ORM,
never this service's own data.

Given control-center's own isolation constraint for this feature (no
other repository may be modified to ship it), a new MySQL database is
not an option -- provisioning one means compose/credential wiring that
lives in omnibioai-studio, a different repo. SQLite via SQLAlchemy is a
real, durable, queryable persistence layer that needs zero deploy-time
changes anywhere else: the file lives inside this service's own
container/volume. A future migration to a shared MySQL instance (the
same one omnibioai-security-audit or omnibioai-auth already use) is a
reasonable follow-up once that compose wiring is in scope, not a
blocker for V1 -- see this package's own top-level docstring.

No Alembic here (unlike omnibioai-security-audit/omnibioai-auth, which
both already have their own migration history) -- this is the first
table this repo has ever needed, so `Base.metadata.create_all()`
(idempotent, CREATE TABLE IF NOT EXISTS semantics) is the right amount
of machinery, not a second migration framework's worth of ceremony for
one table. If this table's schema needs to evolve later, that's the
natural point to introduce Alembic here, the same way
omnibioai-security-audit did the day it needed its first real schema
change (0002_integrity_status.py).
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


def _default_database_url() -> str:
    # A bare relative filename -- deliberately no directory is created
    # here. SQLite creates the file itself lazily, on first real
    # connection (see this module's own docstring on why _ensure_
    # initialized below, not import time, is when that first happens),
    # so this module never has to assume a writable /data volume exists
    # or pre-create one.
    return os.environ.get("HIPAA_COMPLIANCE_DB_URL", "sqlite:///hipaa_compliance.db")


DATABASE_URL = _default_database_url()

# check_same_thread=False: FastAPI/Starlette may serve a request on a
# different thread than the one that created the engine (the same reason
# every StaticPool-based SQLite test engine in this ecosystem sets it,
# e.g. omnibioai-security-audit's tests/conftest.py::audit_events_client)
# -- irrelevant for a non-SQLite DATABASE_URL, so only set for sqlite.
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

_initialized = False


def init_db() -> None:
    """Create every table registered on Base.metadata against the real
    module-level `engine` above. Idempotent (create_all's own
    checkfirst=True default) -- safe to call on every process start.
    Imports models.py for its side effect of registering
    HipaaComplianceChange on Base.metadata, the same
    "import db.models # noqa: F401" convention
    omnibioai-security-audit's alembic/env.py already uses for the same
    reason.
    """
    from control_center.hipaa_compliance import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def _ensure_initialized() -> None:
    """Lazy, memoized init -- runs at most once per process, on the
    first real request that actually needs the database (not at module
    import time, and not tied to FastAPI's startup event, whose
    execution timing under TestClient(app) without a `with` block is
    inconsistent across this repo's own existing tests -- see
    test_main.py's bare `client = TestClient(app)`). Tests never reach
    this at all: they override the `get_db` dependency outright (see
    tests/test_hipaa_compliance_routes.py), so this function's real
    module-level `engine`/`SessionLocal` -- and the on-disk file behind
    them -- is never touched by the test suite.
    """
    global _initialized
    if not _initialized:
        init_db()
        from control_center.hipaa_compliance.seed import seed_initial_data

        db = SessionLocal()
        try:
            seed_initial_data(db)
        finally:
            db.close()
        _initialized = True


def get_db():
    """FastAPI dependency -- yields a Session bound to the real engine.
    Same generator-yield-close shape every other `get_db` in this
    ecosystem uses (e.g. omnibioai-security-audit's db/session.py)."""
    _ensure_initialized()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
