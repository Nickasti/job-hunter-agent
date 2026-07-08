"""
app/models_db.py — Modelli ORM (schema multi-utente).

Tabelle:
  users               credenziali di accesso alla piattaforma
  user_google_tokens  refresh token Google cifrato + watermark fetch Gmail
  user_telegram       collegamento chat Telegram via link-code
  user_criteria       criteri di scoring personalizzati
  user_jobs           annunci estratti dalla Gmail dell'utente
  user_matches        risultato scoring per (utente, job) + dedup notifiche

NB: `jobs_global` (fonte condivisa da scraping) NON è presente: va aggiunta
quando si reintrodurrà lo scraping delle career page (ora fuori scope).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)  # notifiche on/off
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    google: Mapped["UserGoogleToken"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    telegram: Mapped["UserTelegram"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    criteria: Mapped["UserCriteria"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class UserGoogleToken(Base):
    __tablename__ = "user_google_tokens"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    refresh_token_enc: Mapped[str] = mapped_column(Text, nullable=False)  # cifrato (Fernet)
    scopes: Mapped[str] = mapped_column(Text, default="")
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    # Watermark: epoch dell'ultima email Gmail processata per questo utente.
    last_gmail_epoch: Mapped[int] = mapped_column(Integer, default=0)

    user: Mapped[User] = relationship(back_populates="google")


class UserTelegram(Base):
    __tablename__ = "user_telegram"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    link_code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    chat_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # None finché non collega
    linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="telegram")


class UserCriteria(Base):
    __tablename__ = "user_criteria"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    location_filter: Mapped[str] = mapped_column(Text, default="")     # sinonimi espansi per lo scoring
    # Selezioni "grezze" dai menù a tendina (per ri-renderizzare il form):
    countries: Mapped[str] = mapped_column(Text, default="")           # CSV di codici paese, es. "PT,ES"
    cities: Mapped[str] = mapped_column(Text, default="")              # CSV di id città, es. "PT|Lisbona"
    cities_custom: Mapped[str] = mapped_column(Text, default="")       # città scritte a mano, CSV libero
    lingua_pref: Mapped[str] = mapped_column(String(255), default="")  # CSV lingue, es. "Italiano,Inglese"
    contratto_pref: Mapped[str] = mapped_column(String(128), default="")  # es. "stage, internship, junior"
    skills_keywords: Mapped[str] = mapped_column(Text, default="")     # CSV di keyword
    salario_minimo: Mapped[int] = mapped_column(Integer, default=0)    # EUR/mese, 0 = indifferente
    durata_minima: Mapped[int] = mapped_column(Integer, default=0)     # mesi, 0 = indifferente
    soglia_notifica: Mapped[int] = mapped_column(Integer, default=55)
    pesi_custom: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON opzionale

    user: Mapped[User] = relationship(back_populates="criteria")


class UserJob(Base):
    __tablename__ = "user_jobs"
    __table_args__ = (UniqueConstraint("user_id", "fingerprint", name="uq_userjob_fp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    fonte: Mapped[str] = mapped_column(String(32), default="gmail")
    url: Mapped[str] = mapped_column(Text, default="")
    titolo: Mapped[str] = mapped_column(Text, default="")
    azienda: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str] = mapped_column(Text, default="")
    testo_grezzo: Mapped[str] = mapped_column(Text, default="")
    fingerprint: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class UserMatch(Base):
    __tablename__ = "user_matches"
    __table_args__ = (UniqueConstraint("user_id", "job_id", name="uq_usermatch"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    job_id: Mapped[int] = mapped_column(ForeignKey("user_jobs.id"), index=True, nullable=False)
    score: Mapped[int] = mapped_column(Integer, default=0)
    dettaglio_score: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON breakdown
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    notificato_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PasswordReset(Base):
    """Token monouso per il recupero password (hash sha256, mai il token in chiaro)."""

    __tablename__ = "password_resets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RunLog(Base):
    """Log sintetico delle esecuzioni del ciclo (mostrato in dashboard)."""

    __tablename__ = "run_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    users_processed: Mapped[int] = mapped_column(Integer, default=0)
    jobs_fetched: Mapped[int] = mapped_column(Integer, default=0)
    jobs_scored: Mapped[int] = mapped_column(Integer, default=0)
    notified: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
