"""Gedeelde instellingen voor de hele pipeline.

Paden zijn relatief aan de repo-root — alle scripts worden dan ook
vanuit de repo-root gedraaid (bv. `python scripts/run_pipeline.py`),
niet vanuit de scripts/-map zelf.
"""

BASE_URL = "https://zaanstad.bestuurlijkeinformatie.nl"
CALENDAR_URL = f"{BASE_URL}/Calendar"

# Zelfde class-id als in AlexHetzelfde/IbabsLos2 (scrape_vergaderingen.py),
# gebruikt om raadsvergaderingen te filteren van andere vergadertypes.
RAAD_CLASS = "agendatype-100491844"

DATA_DIR = "data"
VERWERKT_PAD = f"{DATA_DIR}/verwerkte_vergaderingen.json"
RESULTATEN_PAD = f"{DATA_DIR}/resultaten.json"
ENCODINGS_PAD = f"{DATA_DIR}/face_encodings.json"
CLIPS_DIR = f"{DATA_DIR}/clips"

DOWNLOADS_DIR = "downloads"
DEBUG_DIR = "debug"
RAADSLEDEN_DIR = "raadsleden"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Referer": CALENDAR_URL,
}
