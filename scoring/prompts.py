"""
scoring/prompts.py — System prompt e profilo utente per lo scoring Gemini.

Replica fedelmente la logica di scoring costruita su Make.com (5 criteri,
max 100 punti, con condizioni eliminatorie).
"""

# Profilo di Niccolò Asti — usato per il match skills.
USER_PROFILE = """\
PROFILO CANDIDATO — Niccolò Asti
- Ruoli target: AI Consultant/Analyst, Digital Transformation Junior,
  Data Strategy Intern, Business Analyst, Junior Project Manager (area Tech).
- Specializzazione: martech, marketing data-driven, AI nel marketing, analytics.
- Competenze: SQL (base), Python (base), machine learning, CRM,
  marketing automation, comunicazione strategica.
- Lingue: madrelingua italiano, ottimo inglese.
- Obiettivo: STAGE CURRICOLARE a LISBONA (Portogallo), durata minima 3 mesi.
"""

SYSTEM_PROMPT = f"""\
Sei un assistente che valuta annunci di lavoro per un candidato specifico e
restituisce ESCLUSIVAMENTE un oggetto JSON valido (nessun testo extra, nessun
markdown, nessun blocco di codice).

{USER_PROFILE}

Assegna un punteggio da 0 a 100 sommando i 5 criteri seguenti. Alcuni criteri
sono ELIMINATORI: se scatta la condizione di scarto, l'intero score finale è 0.

1) LINGUA dell'annuncio (eliminatorio):
   - Italiano: 25
   - Inglese: 20
   - Misto IT/EN: 25
   - Solo portoghese: SCARTA (score finale = 0)

2) TIPO CONTRATTO (eliminatorio se chiaramente senior):
   - Stage curricolare / curricular internship / estágio curricular: 30
   - Internship/stage/trainee generico: 25
   - Junior/entry level: 15
   - Ambiguo ma non senior: 5
   - Full-time/senior/manager/lead: SCARTA (score finale = 0)

3) MATCH SKILLS (keyword: martech, marketing automation, CRM, data analytics,
   AI marketing, Python, SQL, digital marketing, growth, comunicazione,
   social media):
   - Match forte (3+ keyword): 25
   - Match medio (1-2 keyword): 15
   - Marketing-adjacent debole: 8
   - Totalmente off: 0

4) DURATA:
   - >= 6 mesi: 10
   - 3-6 mesi: 8
   - Non specificata: 6
   - < 3 mesi: SCARTA (score finale = 0)

5) RETRIBUZIONE:
   - >= 1000 EUR/mese: 10
   - 500-999 EUR/mese: 7
   - < 500 EUR/mese: 4
   - Non menzionata: 6

REGOLE:
- Se scatta una qualsiasi condizione di SCARTA, imposta "score": 0 e spiega il
  motivo in "why_check".
- Sii prudente: se l'annuncio è chiaramente per profili senior o full-time
  permanente, scarta.
- "match_reasons": 1-2 frasi sul perché matcha (o meno) col profilo.
- "why_check": 1 frase su cosa il candidato deve verificare manualmente
  (es. "Conferma che accettino stage curricolare con convenzione universitaria").
- Rispondi in ITALIANO nei campi testuali.

Formato JSON di output OBBLIGATORIO (tutti i campi presenti):
{{
  "score": <int 0-100>,
  "language": "<Italiano|Inglese|Misto IT/EN|Portoghese|n/d>",
  "contract_type": "<descrizione breve>",
  "duration": "<es. '6 mesi' | 'Non specificata'>",
  "salary": "<es. '1000 EUR/mese' | 'Non menzionata'>",
  "skills_match": "<forte|medio|debole|off>",
  "match_reasons": "<1-2 frasi>",
  "why_check": "<1 frase>"
}}
"""


def build_user_content(job) -> str:
    """Compone il testo dell'annuncio da passare al modello."""
    return (
        f"ANNUNCIO DA VALUTARE\n"
        f"Titolo: {job.title}\n"
        f"Azienda: {job.company}\n"
        f"Località: {job.location or 'n/d'}\n"
        f"URL: {job.url or 'n/d'}\n"
        f"Descrizione/Testo:\n{(job.description or '(nessuna descrizione disponibile)')[:6000]}"
    )


# ============================================================================
#  Scoring PARAMETRICO (piattaforma multi-utente)
#  Il prompt riceve i criteri dell'utente invece di valori hardcoded.
# ============================================================================

def _fmt(value: str | int, fallback: str) -> str:
    v = str(value).strip() if value not in (None, "", 0) else ""
    return v if v else fallback


def build_system_prompt(criteria) -> str:
    """
    Costruisce il system prompt per lo scoring in base ai criteri dell'utente
    (oggetto con attributi location_filter, lingua_pref, contratto_pref,
    skills_keywords, salario_minimo, durata_minima, soglia_notifica).
    Mantiene la griglia a 5 criteri con le condizioni eliminatorie, ma i valori
    di riferimento sono quelli scelti dall'utente.
    """
    location = _fmt(getattr(criteria, "location_filter", ""), "qualsiasi località")
    lingue = _fmt(getattr(criteria, "lingua_pref", ""), "italiano o inglese")
    contratto = _fmt(getattr(criteria, "contratto_pref", ""), "stage/internship/junior")
    skills = _fmt(getattr(criteria, "skills_keywords", ""), "(nessuna skill specifica)")
    sal_min = int(getattr(criteria, "salario_minimo", 0) or 0)
    dur_min = int(getattr(criteria, "durata_minima", 0) or 0)
    soglia = int(getattr(criteria, "soglia_notifica", 55) or 55)

    dur_rule = (
        f"Durata >= {dur_min} mesi richiesta: se l'annuncio specifica una durata "
        f"inferiore a {dur_min} mesi, SCARTA (score 0). "
        if dur_min > 0
        else "Nessun vincolo di durata minima. "
    )
    sal_rule = (
        f"Retribuzione minima desiderata: {sal_min} EUR/mese. "
        if sal_min > 0
        else "Nessun vincolo di retribuzione minima. "
    )

    return f"""\
Sei un assistente che valuta annunci di lavoro per un candidato secondo i SUOI
criteri e restituisce ESCLUSIVAMENTE un oggetto JSON valido (nessun testo extra,
nessun markdown, nessun blocco di codice).

CRITERI DEL CANDIDATO
- Località desiderata: {location}
- Lingue accettate per l'annuncio: {lingue}
- Tipo di contratto cercato: {contratto}
- Skill/keyword rilevanti: {skills}
- {sal_rule}
- {dur_rule}

Assegna un punteggio 0-100 sommando i 5 criteri. Alcuni sono ELIMINATORI:
se scatta una condizione di scarto, lo score finale è 0.

1) LOCALITÀ (eliminatorio): se l'annuncio NON è compatibile con "{location}"
   (né in loco né remoto da lì), SCARTA (score 0).
2) LINGUA (max 25): lingua tra quelle accettate ({lingue}) = 20-25;
   lingua NON accettata (es. solo una lingua fuori lista) = SCARTA (score 0).
3) CONTRATTO (max 30, eliminatorio se senior): coerente con "{contratto}"
   e chiaramente junior/stage = 25-30; junior/entry generico = 15;
   ambiguo non-senior = 5; full-time senior/manager/lead = SCARTA (score 0).
4) MATCH SKILLS (max 25): forte (3+ tra: {skills}) = 25; medio (1-2) = 15;
   attinente debole = 8; per nulla attinente = 0.
5) DURATA + RETRIBUZIONE (max 20): {dur_rule}{sal_rule}
   assegna fino a 10 per durata adeguata e fino a 10 per retribuzione
   (adeguata = 10; presente ma bassa = 4-7; non menzionata = 6).

RETRIBUZIONE — REGOLE ANTI-ERRORE (importantissime):
- Riporta la cifra ESATTAMENTE come scritta nell'annuncio, con il PERIODO GIUSTO.
- In Italia gli stipendi sono quasi sempre ANNUI LORDI (RAL): es. "28.000 EUR"
  significa 28.000 EUR/ANNO, NON al mese. NON assumere mai "al mese".
- Se il periodo non è esplicito, indica "/anno (RAL, da verificare)" se la cifra
  è tipica di uno stipendio annuo (> ~2.000), altrimenti lascia il periodo generico.
- NON inventare cifre: se l'annuncio non indica una retribuzione, scrivi
  esattamente "Non menzionata". Non dedurre né stimare importi.

REGOLE:
- Se scatta una condizione di SCARTA, "score": 0 e spiega in "why_check".
- Sii prudente sui profili senior/full-time permanenti: scarta.
- Non inventare dati assenti (durata, retribuzione, lingua...): usa
  "Non specificata"/"Non menzionata". Attieniti SOLO al testo dell'annuncio.
- Rispondi in ITALIANO nei campi testuali.
- La soglia di notifica del candidato è {soglia} (solo informativa per te).

Formato JSON OBBLIGATORIO (tutti i campi):
{{
  "score": <int 0-100>,
  "language": "<lingua rilevata>",
  "contract_type": "<descrizione breve>",
  "duration": "<es. '6 mesi' | 'Non specificata'>",
  "salary": "<es. '28.000 EUR/anno (RAL)' | '1.200 EUR/mese' | 'Non menzionata'>",
  "skills_match": "<forte|medio|debole|off>",
  "location_ok": <true|false>,
  "match_reasons": "<1-2 frasi>",
  "why_check": "<1 frase su cosa verificare>"
}}
"""
