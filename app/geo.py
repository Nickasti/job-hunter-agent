"""
app/geo.py — Elenchi controllati per i criteri (lingue + Stati/città europei).

Servono per i menù a tendina a scelta multipla dell'onboarding/dashboard, con
cascata Stato → Città. Ogni voce ha dei "sinonimi" di match (inglese/italiano/
locale) usati per lo scoring: così un annuncio scritto "Lisbon" o "Lisboa" o
"Lisbona" viene comunque riconosciuto.

Struttura _COUNTRIES: code -> (label_it, [sinonimi_paese], {citta_label: [sinonimi]})
"""
from __future__ import annotations

# Lingue selezionabili (il valore salvato è la label stessa, usata nel prompt).
LANGUAGES = [
    "Italiano", "Inglese", "Portoghese", "Spagnolo", "Francese",
    "Tedesco", "Olandese", "Catalano",
]

_COUNTRIES: dict[str, tuple[str, list[str], dict[str, list[str]]]] = {
    "PT": ("Portogallo", ["Portugal", "Portogallo"], {
        "Lisbona": ["Lisbon", "Lisboa", "Lisbona"],
        "Porto": ["Porto", "Oporto"],
        "Braga": ["Braga"],
        "Coimbra": ["Coimbra"],
        "Aveiro": ["Aveiro"],
        "Faro": ["Faro"],
    }),
    "IT": ("Italia", ["Italy", "Italia"], {
        "Milano": ["Milan", "Milano"],
        "Roma": ["Rome", "Roma"],
        "Torino": ["Turin", "Torino"],
        "Bologna": ["Bologna"],
        "Firenze": ["Florence", "Firenze"],
        "Napoli": ["Naples", "Napoli"],
        "Padova": ["Padua", "Padova"],
    }),
    "ES": ("Spagna", ["Spain", "Spagna", "España"], {
        "Madrid": ["Madrid"],
        "Barcellona": ["Barcelona", "Barcellona"],
        "Valencia": ["Valencia", "València"],
        "Siviglia": ["Seville", "Sevilla", "Siviglia"],
        "Malaga": ["Malaga", "Málaga"],
        "Bilbao": ["Bilbao"],
    }),
    "FR": ("Francia", ["France", "Francia"], {
        "Parigi": ["Paris", "Parigi"],
        "Lione": ["Lyon", "Lione"],
        "Marsiglia": ["Marseille", "Marsiglia"],
        "Tolosa": ["Toulouse", "Tolosa"],
        "Nizza": ["Nice", "Nizza"],
        "Bordeaux": ["Bordeaux"],
    }),
    "DE": ("Germania", ["Germany", "Germania", "Deutschland"], {
        "Berlino": ["Berlin", "Berlino"],
        "Monaco": ["Munich", "München", "Monaco di Baviera"],
        "Amburgo": ["Hamburg", "Amburgo"],
        "Francoforte": ["Frankfurt", "Francoforte"],
        "Colonia": ["Cologne", "Köln", "Colonia"],
        "Monaco di Baviera": ["Munich", "München"],
    }),
    "NL": ("Paesi Bassi", ["Netherlands", "Paesi Bassi", "Holland"], {
        "Amsterdam": ["Amsterdam"],
        "Rotterdam": ["Rotterdam"],
        "L'Aia": ["The Hague", "Den Haag", "L'Aia"],
        "Utrecht": ["Utrecht"],
        "Eindhoven": ["Eindhoven"],
    }),
    "IE": ("Irlanda", ["Ireland", "Irlanda"], {
        "Dublino": ["Dublin", "Dublino"],
        "Cork": ["Cork"],
        "Galway": ["Galway"],
    }),
    "GB": ("Regno Unito", ["United Kingdom", "UK", "Regno Unito", "England"], {
        "Londra": ["London", "Londra"],
        "Manchester": ["Manchester"],
        "Birmingham": ["Birmingham"],
        "Edimburgo": ["Edinburgh", "Edimburgo"],
        "Cambridge": ["Cambridge"],
    }),
    "BE": ("Belgio", ["Belgium", "Belgio"], {
        "Bruxelles": ["Brussels", "Bruxelles", "Brussel"],
        "Anversa": ["Antwerp", "Antwerpen", "Anversa"],
        "Gand": ["Ghent", "Gent", "Gand"],
    }),
    "LU": ("Lussemburgo", ["Luxembourg", "Lussemburgo"], {
        "Lussemburgo": ["Luxembourg", "Lussemburgo"],
    }),
    "CH": ("Svizzera", ["Switzerland", "Svizzera"], {
        "Zurigo": ["Zurich", "Zürich", "Zurigo"],
        "Ginevra": ["Geneva", "Genève", "Ginevra"],
        "Basilea": ["Basel", "Basilea"],
        "Losanna": ["Lausanne", "Losanna"],
    }),
    "AT": ("Austria", ["Austria", "Österreich"], {
        "Vienna": ["Vienna", "Wien"],
        "Graz": ["Graz"],
        "Salisburgo": ["Salzburg", "Salisburgo"],
    }),
    "PL": ("Polonia", ["Poland", "Polonia", "Polska"], {
        "Varsavia": ["Warsaw", "Warszawa", "Varsavia"],
        "Cracovia": ["Krakow", "Kraków", "Cracovia"],
        "Breslavia": ["Wroclaw", "Wrocław", "Breslavia"],
        "Danzica": ["Gdansk", "Gdańsk", "Danzica"],
    }),
    "CZ": ("Repubblica Ceca", ["Czech Republic", "Czechia", "Repubblica Ceca"], {
        "Praga": ["Prague", "Praha", "Praga"],
        "Brno": ["Brno"],
    }),
    "DK": ("Danimarca", ["Denmark", "Danimarca"], {
        "Copenaghen": ["Copenhagen", "København", "Copenaghen"],
        "Aarhus": ["Aarhus", "Århus"],
    }),
    "SE": ("Svezia", ["Sweden", "Svezia", "Sverige"], {
        "Stoccolma": ["Stockholm", "Stoccolma"],
        "Goteborg": ["Gothenburg", "Göteborg", "Goteborg"],
        "Malmo": ["Malmo", "Malmö"],
    }),
    "NO": ("Norvegia", ["Norway", "Norvegia", "Norge"], {
        "Oslo": ["Oslo"],
        "Bergen": ["Bergen"],
    }),
    "FI": ("Finlandia", ["Finland", "Finlandia", "Suomi"], {
        "Helsinki": ["Helsinki"],
        "Tampere": ["Tampere"],
        "Espoo": ["Espoo"],
    }),
    "GR": ("Grecia", ["Greece", "Grecia"], {
        "Atene": ["Athens", "Athina", "Atene"],
        "Salonicco": ["Thessaloniki", "Salonicco"],
    }),
    "RO": ("Romania", ["Romania"], {
        "Bucarest": ["Bucharest", "București", "Bucarest"],
        "Cluj-Napoca": ["Cluj-Napoca", "Cluj"],
        "Timisoara": ["Timisoara", "Timișoara"],
    }),
    "HU": ("Ungheria", ["Hungary", "Ungheria", "Magyarország"], {
        "Budapest": ["Budapest"],
    }),
    "BG": ("Bulgaria", ["Bulgaria"], {
        "Sofia": ["Sofia"],
        "Plovdiv": ["Plovdiv"],
    }),
    "HR": ("Croazia", ["Croatia", "Croazia", "Hrvatska"], {
        "Zagabria": ["Zagreb", "Zagabria"],
        "Spalato": ["Split", "Spalato"],
    }),
    "SI": ("Slovenia", ["Slovenia"], {
        "Lubiana": ["Ljubljana", "Lubiana"],
    }),
    "SK": ("Slovacchia", ["Slovakia", "Slovacchia"], {
        "Bratislava": ["Bratislava"],
    }),
    "EE": ("Estonia", ["Estonia"], {
        "Tallinn": ["Tallinn"],
    }),
    "LV": ("Lettonia", ["Latvia", "Lettonia"], {
        "Riga": ["Riga"],
    }),
    "LT": ("Lituania", ["Lithuania", "Lituania"], {
        "Vilnius": ["Vilnius"],
        "Kaunas": ["Kaunas"],
    }),
    "MT": ("Malta", ["Malta"], {
        "La Valletta": ["Valletta", "La Valletta"],
    }),
    "CY": ("Cipro", ["Cyprus", "Cipro"], {
        "Nicosia": ["Nicosia"],
        "Limassol": ["Limassol"],
    }),
    "IS": ("Islanda", ["Iceland", "Islanda"], {
        "Reykjavik": ["Reykjavik", "Reykjavík"],
    }),
    "RS": ("Serbia", ["Serbia"], {
        "Belgrado": ["Belgrade", "Beograd", "Belgrado"],
        "Novi Sad": ["Novi Sad"],
    }),
    "UA": ("Ucraina", ["Ukraine", "Ucraina"], {
        "Kiev": ["Kyiv", "Kiev"],
        "Leopoli": ["Lviv", "Leopoli"],
    }),
}

CITY_SEP = "|"  # separatore nell'id città: "<code>|<label>"


def frontend() -> dict:
    """Struttura leggera per il JavaScript della cascata (senza sinonimi)."""
    out = {}
    for code, (label, _match, cities) in sorted(_COUNTRIES.items(), key=lambda kv: kv[1][0]):
        out[code] = {
            "label": label,
            "cities": [
                {"id": f"{code}{CITY_SEP}{city}", "label": city} for city in cities
            ],
        }
    return out


def country_choices() -> list[tuple[str, str]]:
    """(code, label) ordinati per label, per il <select> degli Stati."""
    return sorted(((c, v[0]) for c, v in _COUNTRIES.items()), key=lambda t: t[1])


def valid_country_codes() -> set[str]:
    return set(_COUNTRIES.keys())


def valid_city_ids() -> set[str]:
    return {
        f"{code}{CITY_SEP}{city}"
        for code, (_l, _m, cities) in _COUNTRIES.items()
        for city in cities
    }


def expand(country_codes: list[str], city_ids: list[str]) -> list[str]:
    """
    Espande le scelte (codici paese + id città) nella lista di sinonimi usata
    per lo scoring/pre-filtro. Dedup preservando l'ordine.
    """
    seen: list[str] = []

    def add(values: list[str]):
        for v in values:
            if v and v not in seen:
                seen.append(v)

    for code in country_codes:
        entry = _COUNTRIES.get(code)
        if entry:
            add(entry[1])
    for cid in city_ids:
        code, _, city = cid.partition(CITY_SEP)
        entry = _COUNTRIES.get(code)
        if entry and city in entry[2]:
            add(entry[2][city])
    return seen
