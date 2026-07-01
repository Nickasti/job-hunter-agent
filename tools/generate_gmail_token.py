"""
tools/generate_gmail_token.py — Genera il GMAIL_REFRESH_TOKEN (una sola volta).

Esegui QUESTO script in LOCALE (apre il browser per il consenso OAuth). Poi
copia i valori stampati nei tuoi Secret di GitHub. In CI non serve più alcun
file: l'agente ricostruisce le credenziali da CLIENT_ID/SECRET/REFRESH_TOKEN.

Prerequisito: un file `credentials.json` (OAuth Client "Desktop app") scaricato
dalla Google Cloud Console nella cartella del progetto.

Uso:
    python tools/generate_gmail_token.py
"""
from __future__ import annotations

import os
import sys

# Permetti l'import di config dalla root del progetto.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: E402

import config  # noqa: E402

CREDENTIALS_FILE = os.environ.get("GMAIL_CREDENTIALS_PATH", "credentials.json")


def main() -> int:
    if not os.path.exists(CREDENTIALS_FILE):
        print(f"[X] File '{CREDENTIALS_FILE}' non trovato.")
        print("   Scaricalo dalla Google Cloud Console (OAuth Client -> Desktop app).")
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, config.GMAIL_SCOPES)
    # access_type=offline + prompt=consent garantiscono il refresh_token.
    creds = flow.run_local_server(
        port=0, access_type="offline", prompt="consent"
    )

    lines = [
        f"GMAIL_CLIENT_ID={creds.client_id}",
        f"GMAIL_CLIENT_SECRET={creds.client_secret}",
        f"GMAIL_REFRESH_TOKEN={creds.refresh_token}",
    ]

    # Salva su file per sicurezza (evita problemi di stampa in console Windows).
    out_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gmail_token_output.txt"
    )
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    print("\n[OK] Autorizzazione completata. Valori (anche salvati in gmail_token_output.txt):\n")
    for line in lines:
        print(line)
    print("\n(Copiali nei GitHub Secrets e/o nel file .env)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
