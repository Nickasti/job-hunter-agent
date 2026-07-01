"""
app/auth.py — Autenticazione utenti: email + password (bcrypt) e sessioni cookie.

Le sessioni usano lo Starlette SessionMiddleware (cookie firmato con
SESSION_SECRET). Nessuna password in chiaro: si salva solo l'hash bcrypt.
"""
from __future__ import annotations

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models_db import User, UserCriteria, UserTelegram
from app.telegram_bot import new_link_code


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email.lower().strip()))


def create_user(db: Session, email: str, password: str) -> User:
    """Crea utente + righe di default (criteri, link-code Telegram)."""
    user = User(email=email.lower().strip(), password_hash=hash_password(password))
    db.add(user)
    db.flush()  # ottiene user.id

    db.add(UserCriteria(user_id=user.id))  # default: soglia 55, resto indifferente
    db.add(UserTelegram(user_id=user.id, link_code=new_link_code()))
    db.commit()
    db.refresh(user)
    return user


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = get_user_by_email(db, email)
    if user and verify_password(password, user.password_hash):
        return user
    return None


# ---------------------------------------------------------------- dipendenze
def get_current_user(
    request: Request, db: Session = Depends(get_session)
) -> User | None:
    """Ritorna l'utente loggato (o None) leggendo la sessione cookie."""
    uid = request.session.get("user_id")
    if not uid:
        return None
    return db.get(User, uid)


def require_user(
    request: Request, db: Session = Depends(get_session)
) -> User:
    """Dependency che impone il login; altrimenti 401 (redirect gestito a monte)."""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Login richiesto",
            headers={"Location": "/login"},
        )
    return user


def login_session(request: Request, user: User) -> None:
    request.session["user_id"] = user.id


def logout_session(request: Request) -> None:
    request.session.clear()
