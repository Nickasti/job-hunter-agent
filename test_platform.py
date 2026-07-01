"""
test_platform.py — Test end-to-end della piattaforma multi-utente (offline).

Mocka Gemini e l'invio Telegram. Verifica:
  - boot app + creazione tabelle
  - registrazione / login via HTTP (TestClient)
  - salvataggio criteri
  - ciclo di scoring: due utenti con criteri diversi ottengono match diversi
    sullo stesso annuncio, e la notifica parte solo sopra la soglia personale.

Esegui:  python test_platform.py
"""
from __future__ import annotations

import os
import sys
import tempfile

# DB temporaneo isolato PRIMA di importare l'app.
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmp, 'test.db')}"
os.environ.setdefault("MASTER_KEY", "6qUJ_d0HNDquhaNoUV5Ae9HNzdF9WGc0ydwW-UWimQU=")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

from fastapi.testclient import TestClient  # noqa: E402

from app import cycle, scoring_engine  # noqa: E402
from app.db import init_db, session_scope  # noqa: E402
from app.main import app  # noqa: E402
from app.models_db import User, UserCriteria, UserJob, UserMatch, UserTelegram  # noqa: E402


def main() -> int:
    print("== test_platform ==\n")
    init_db()
    client = TestClient(app)

    # --- 1) Registrazione via HTTP ---
    r = client.post(
        "/register",
        data={"email": "a@example.com", "password": "password123"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), r.status_code
    print("[ok] registrazione utente A → redirect onboarding")

    # Dashboard raggiungibile (loggati via cookie di sessione).
    assert client.get("/dashboard").status_code == 200
    print("[ok] dashboard accessibile dopo login")

    # --- 2) Salva criteri utente A (soglia bassa) ---
    r = client.post(
        "/dashboard/criteria",
        data={
            "location_filter": "Lisbon, Portugal",
            "lingua_pref": "Italiano, Inglese",
            "contratto_pref": "stage, internship",
            "skills_keywords": "python, sql, crm, marketing",
            "salario_minimo": 0,
            "durata_minima": 3,
            "soglia_notifica": 50,
        },
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)
    print("[ok] criteri utente A salvati (soglia 50)")

    # --- 3) Secondo utente B con soglia ALTA, stesso annuncio ---
    with session_scope() as db:
        ua = db.query(User).filter_by(email="a@example.com").one()
        # Collega Telegram fittizio a A
        ta = db.query(UserTelegram).filter_by(user_id=ua.id).one()
        ta.chat_id = "1111"

        ub = User(email="b@example.com", password_hash="x", is_active=True)
        db.add(ub)
        db.flush()
        db.add(UserCriteria(
            user_id=ub.id, location_filter="Lisbon, Portugal",
            skills_keywords="python, sql", soglia_notifica=95, durata_minima=3,
        ))
        db.add(UserTelegram(user_id=ub.id, link_code="codeB", chat_id="2222"))

        # Stesso annuncio per entrambi
        for uid in (ua.id, ub.id):
            db.add(UserJob(
                user_id=uid, fonte="gmail",
                url="https://www.linkedin.com/jobs/view/999",
                titolo="Marketing Data Analyst Intern",
                azienda="Talkdesk", location="Lisbon, Portugal",
                testo_grezzo="Curricular internship 6 months. Python, SQL, CRM, marketing.",
                fingerprint=f"fp-{uid}",
            ))
        ua.is_active = True

    # --- 4) Mock Gemini (score 80) e Telegram send ---
    def fake_evaluate(self, job, criteria):
        return scoring_engine._finalize(job, {
            "score": 80, "language": "Inglese", "contract_type": "Curricular internship",
            "duration": "6 mesi", "salary": "Non menzionata", "skills_match": "forte",
            "location_ok": True, "match_reasons": "Ottimo match martech.",
            "why_check": "Verifica convenzione stage.",
        })

    sent = []
    scoring_engine.CycleScorer.evaluate = fake_evaluate
    cycle.send_match = lambda chat_id, result: (sent.append((chat_id, result["score"])) or True)

    stats = cycle.run_cycle()
    print("[ok] run_cycle stats:", stats)

    # --- 5) Verifiche ---
    with session_scope() as db:
        matches = db.query(UserMatch).all()
        assert len(matches) == 2, f"attesi 2 match, trovati {len(matches)}"
        by_user = {m.user_id: m for m in matches}
        # Entrambi score 80, ma solo A (soglia 50) notificato; B (soglia 95) no.
        assert all(m.score == 80 for m in matches)
        notified_users = {m.user_id for m in matches if m.notificato_at}

    a_id = [u for (u, s) in sent]
    print(f"[ok] notifiche inviate a chat: {a_id} (atteso solo 1111, non 2222)")
    assert sent == [("1111", 80)], sent
    assert len(notified_users) == 1
    print("[ok] due utenti, stessa offerta, notifica solo a chi ha soglia <= score")

    print("\n✅ TEST PIATTAFORMA PASSATO.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
