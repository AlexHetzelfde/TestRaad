#!/usr/bin/env python3
"""
Haalt recent afgeronde raadsvergaderingen op via de iBabs Calendar-API
(zelfde endpoint als AlexHetzelfde/IbabsLos2/scrape_vergaderingen.py
gebruikt) en filtert degene die nog niet verwerkt zijn.

We gebruiken hier alleen de agenda-lijst-endpoint (GetAgendasForCalendar).
Die geeft meteen id/titel/start/eind/url terug — geen headless browser
nodig om te weten wánneer er een vergadering was, alleen om er straks de
video van te pakken (zie get_video_url.py).
"""
import json
import os
import urllib.request
import urllib.parse
import http.cookiejar
from datetime import datetime, timedelta

from config import BASE_URL, CALENDAR_URL, RAAD_CLASS, VERWERKT_PAD, HEADERS


def _opener():
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    # Sessie/cookies ophalen, net als de bestaande scraper doet.
    opener.open(urllib.request.Request(CALENDAR_URL, headers=HEADERS), timeout=15)
    return opener


def _fetch_agenda_range(opener, start_dt, end_dt):
    start_str = urllib.parse.quote(start_dt.strftime("%Y-%m-%dT00:00:00+02:00"))
    end_str = urllib.parse.quote(end_dt.strftime("%Y-%m-%dT00:00:00+02:00"))
    url = f"{BASE_URL}/Calendar/GetAgendasForCalendar?start={start_str}&end={end_str}"
    req = urllib.request.Request(url, headers=HEADERS)
    with opener.open(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _laad_verwerkt():
    if not os.path.exists(VERWERKT_PAD):
        return set()
    with open(VERWERKT_PAD, encoding="utf-8") as f:
        return set(json.load(f))


def markeer_verwerkt(agenda_id):
    """Zet een vergadering-id in verwerkte_vergaderingen.json zodat hij
    niet nog eens gedownload/verwerkt wordt."""
    verwerkt = _laad_verwerkt()
    verwerkt.add(agenda_id)
    os.makedirs(os.path.dirname(VERWERKT_PAD), exist_ok=True)
    with open(VERWERKT_PAD, "w", encoding="utf-8") as f:
        json.dump(sorted(verwerkt), f, indent=2)


def nieuwe_afgeronde_vergaderingen(terugkijken_dagen=3, marge_minuten=30):
    """
    Geeft raadsvergaderingen terug die:
      - van het type 'Raadsvergadering' zijn (RAAD_CLASS)
      - al afgelopen zijn (eindtijd + marge ligt in het verleden — de
        opname staat er anders mogelijk nog niet online)
      - nog niet in verwerkte_vergaderingen.json staan
    """
    opener = _opener()
    nu = datetime.now()
    items = _fetch_agenda_range(
        opener, nu - timedelta(days=terugkijken_dagen), nu + timedelta(days=1)
    )
    verwerkt = _laad_verwerkt()

    resultaat = []
    for item in items:
        if RAAD_CLASS not in item.get("classNames", []):
            continue

        agenda_id = item["id"]
        if agenda_id in verwerkt:
            continue

        eind_str = item.get("end", "")
        if not eind_str:
            continue
        try:
            eind = datetime.fromisoformat(eind_str)
            eind = eind.replace(tzinfo=None)  # simpel vergelijken met nu()
        except ValueError:
            continue

        if eind + timedelta(minutes=marge_minuten) > nu:
            continue  # nog te vers, sla over tot een volgende run

        resultaat.append({
            "id": agenda_id,
            "titel": item.get("title", "").strip(),
            "start": item.get("start", ""),
            "eind": eind_str,
            "url": f"{BASE_URL}{item.get('url', '')}",
        })

    return resultaat


if __name__ == "__main__":
    for v in nieuwe_afgeronde_vergaderingen():
        print(v["id"], v["start"], v["titel"])
