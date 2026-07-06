"""
app/db.py — Setup SQLAlchemy (engine + sessione) indipendente dal provider.

DATABASE_URL decide il backend:
  - locale:      sqlite:///.../data/app.db   (file su volume, gitignored)
  - produzione:  postgresql+psycopg://...    (Neon/Supabase, tier free)
"""
from __future__ import annotations

import os
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app import config_web


class Base(DeclarativeBase):
    pass


def _make_engine():
    url = config_web.DATABASE_URL
    kwargs = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        # SQLite: crea la cartella e permetti l'uso cross-thread.
        path = url.replace("sqlite:///", "")
        if path and path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def init_db() -> None:
    """Crea le tabelle se non esistono e applica micro-migrazioni idempotenti."""
    from app import models_db  # noqa: F401 — registra i modelli su Base.metadata

    Base.metadata.create_all(bind=engine)
    _ensure_columns()


def _ensure_columns() -> None:
    """
    Aggiunge colonne mancanti a tabelle già esistenti (create_all NON altera le
    tabelle esistenti). Compatibile SQLite e Postgres: aggiunge solo se assenti.
    """
    from sqlalchemy import inspect

    wanted = {
        "user_criteria": {
            "countries": "TEXT DEFAULT ''",
            "cities": "TEXT DEFAULT ''",
        },
    }
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, cols in wanted.items():
            if not insp.has_table(table):
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            for col, ddl in cols.items():
                if col not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")


@contextmanager
def session_scope():
    """Context manager per una sessione con commit/rollback automatici."""
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_session():
    """Dependency FastAPI: fornisce una sessione e la chiude a fine request."""
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
