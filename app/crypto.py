"""
app/crypto.py — Cifratura simmetrica dei segreti at-rest (Fernet).

I refresh token Google e qualsiasi credenziale utente vengono cifrati prima di
essere salvati nel DB. La master key vive solo come variabile d'ambiente
(MASTER_KEY), mai nel codice né nel repository.
"""
from __future__ import annotations

from cryptography.fernet import Fernet

from app import config_web

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        if not config_web.MASTER_KEY:
            raise RuntimeError(
                "MASTER_KEY mancante. Generane una con: "
                "python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\""
            )
        _fernet = Fernet(config_web.MASTER_KEY.encode())
    return _fernet


def encrypt(plaintext: str) -> str:
    """Cifra una stringa e ritorna il token cifrato (str, salvabile nel DB)."""
    if plaintext is None:
        raise ValueError("Niente da cifrare.")
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(token: str) -> str:
    """Decifra un token prodotto da encrypt()."""
    return _get_fernet().decrypt(token.encode("utf-8")).decode("utf-8")
