"""
app/oauth_google.py — OAuth Google CONDIVISO (un solo client per la piattaforma).

L'utente non crea alcun progetto Google Cloud: usa il client OAuth della
piattaforma. Al callback otteniamo il suo refresh token, che viene cifrato e
salvato. Per il fetch email ricostruiamo le credenziali da quel refresh token.
"""
from __future__ import annotations

from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from app import config_web


def _client_config() -> dict:
    return {
        "web": {
            "client_id": config_web.GOOGLE_CLIENT_ID,
            "client_secret": config_web.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [config_web.PUBLIC_BASE_URL + config_web.GOOGLE_REDIRECT_PATH],
        }
    }


def _flow(state: str | None = None) -> Flow:
    return Flow.from_client_config(
        _client_config(),
        scopes=config_web.GOOGLE_SCOPES,
        redirect_uri=config_web.PUBLIC_BASE_URL + config_web.GOOGLE_REDIRECT_PATH,
        state=state,
    )


def authorization_url(state: str) -> str:
    """URL della consent screen. `state` lega il callback all'utente/sessione."""
    flow = _flow(state=state)
    url, _ = flow.authorization_url(
        access_type="offline",       # necessario per ottenere il refresh_token
        include_granted_scopes="true",
        prompt="consent",            # forza il rilascio del refresh_token
    )
    return url


def exchange_code(code: str, state: str | None = None) -> Credentials:
    """Scambia il code del callback per le credenziali (con refresh_token)."""
    flow = _flow(state=state)
    flow.fetch_token(code=code)
    return flow.credentials


def credentials_from_refresh(refresh_token: str) -> Credentials:
    """Ricostruisce credenziali valide (access token fresco) dal refresh token."""
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=config_web.GOOGLE_CLIENT_ID,
        client_secret=config_web.GOOGLE_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=config_web.GOOGLE_SCOPES,
    )
    creds.refresh(GoogleRequest())
    return creds
