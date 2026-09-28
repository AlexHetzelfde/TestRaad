#!/usr/bin/env python3
"""
Haalt de getekende .m3u8-videolink op voor één vergadering, door de
vergaderpagina in een headless browser te openen en het netwerkverkeer
af te luisteren op m3u8-requests.

Dit automatiseert precies de handmatige DevTools-stap die in
AlexHetzelfde/IbabsLos2 (app.js, "Toon download-instructie") aan de
gebruiker wordt uitgelegd: pagina openen, video starten, filteren op
"m3u8", de grote request (~100-120 kB) pakken i.p.v. de kleine (~3 kB).

STATUS: de kern is bevestigd tegen een echte Zaanstad-vergaderpagina
(27-09-2026, via handmatig Network-tab-onderzoek): het laden van de
pagina triggert vanzelf een accessrules/token-uitwisseling, en na het
starten van de video verschijnen precies twee "sdk-ssl.m3u8"-requests —
een kleine master-playlist (~3-4 kB) en de echte media-playlist
(~100-120 kB, bevestigd 119 kB bij een vergadering van 4u22). De
grootte-drempel hieronder (50 kB) zit daar precies tussen in.

De video wordt geladen via een losse widget van CompanyWebcast
("cwc", <script src="//sdk.companywebcast.com/sdk/player/client.js">
+ een lege <div class="cwc" data-video-id="...">, zie de paginabron).
Server-side staat daar dus niks — pas die SDK bouwt client-side de
speler (incl. een "Start nu"-knop op een posterscherm) op.

Tweede echte run (8 sept 2026, dagen=27): nog steeds geen video
gevonden — máár nu bleek uit het eigen debug-logbestand dat er op
geen enkel moment een iframe ontstond en er geen enkel
consolebericht viel, vóór én ná alle klikpogingen. Dat wijst niet op
een verkeerde knop-selector, maar op de SDK zelf die nooit iets
opbouwt in deze headless sessie. Het probleem: `page.on("console")`
vangt alleen expliciete console.log/warn/error-aanroepen — een
mislukte resource-load (geblokkeerd, DNS-fout, timeout) of een
onafgevangen JS-exception komt daar niet in terecht. Daarom luistert
dit script nu ook naar "requestfailed" (mislukte requests) en
"pageerror" (onafgevangen JS-fouten), en logt het apart de
status van elke request naar companywebcast/agendavideo, zodat een
stille blokkade dit keer wél zichtbaar wordt.

Derde versie (28 sept 2026): de browsercontext kreeg tot nu toe geen
eigen User-Agent mee, dus Playwright stuurde er een met "HeadlessChrome"
erin (config.HEADERS werd alleen door get_meetings.py gebruikt). Een
widget die bots weert kan daarop stilletjes weigeren iets op te bouwen,
precies het symptoom uit de tweede run. Nu krijgt de context dezelfde
gewone Chrome-User-Agent als de agenda-aanvraag, plus nl-NL/Amsterdam en
een verborgen navigator.webdriver. Daarnaast schrijft het script een
"sonde" naar het logbestand: welke User-Agent en webdriver-waarde de
pagina echt ziet, en welke status de SDK-scripts krijgen bij een directe
aanvraag vanaf de GitHub-runner. Zo is te zien of het aan de
User-Agent of aan het IP-adres ligt.

Vierde versie (28 sept 2026), op basis van cURL-opnames uit een gewone
browser: de speler draait NIET in de vergaderpagina zelf maar op
    https://sdk.companywebcast.com/sdk/player/?id=<data-video-id>&display=126&customBtnColor=006a81
(bv. id=zaanstad_20260908_2), en doet daar zelf de token-uitwisseling
(accessrules/<guid> met een X-Authorization-header, plus /token). Er
zijn geen cookies voor nodig, en de teruggegeven CloudFront-policies
zijn niet aan een IP-adres gebonden (AWS:SourceIp 0.0.0.0/0). Het
GitHub-IP is dus geen reden dat het niet werkt. Het loader-script op de
vergaderpagina (client.js) bouwde in de headless run nooit een iframe.
Daarom leest dit script nu het data-video-id uit de vergaderpagina en
opent het de speler-url rechtstreeks, met de vergaderpagina als Referer.
Lukt dat niet, dan valt het terug op de oude route via de vergaderpagina.
Startvolgorde is omgedraaid: eerst een echte klik op "Start nu" (dat is
de handeling waarvan bewezen is dat ze de m3u8-requests triggert), en
pas daarna video.play() als terugvaloptie.
"""
import os
import re
import time
from urllib.parse import quote

from playwright.sync_api import sync_playwright

from config import DEBUG_DIR, HEADERS

# De speler zelf, zoals gezien in de Network-tab (Referer-header van de
# accessrules- en token-requests). {video_id} komt uit het data-video-id
# van de <div class="cwc"> op de vergaderpagina.
SPELER_URL = (
    "https://sdk.companywebcast.com/sdk/player/"
    "?id={video_id}&display=126&customBtnColor=006a81"
)

# Kandidaat-selectors voor de play-knop, van specifiek naar generiek.
# De eerste die zichtbaar is (op de hoofdpagina óf in een iframe), wordt
# aangeklikt.
PLAY_KNOP_SELECTORS = [
    "text=Start nu",                 # bevestigd op de echte pagina (screenshot 27-09-2026): posterscherm met titel/datum/duur en deze knop, vóór er een <video> bestaat
    "button.vjs-big-play-button",   # video.js
    ".plyr__control--overlaid",     # plyr.io
    "button[aria-label*='play' i]",
    "button[title*='afspelen' i]",
    "video",                        # laatste redmiddel: klik op het element zelf
]

# Grens om de kleine "master playlist" (~3 kB) te onderscheiden van de
# grote "media playlist" (~100-120 kB), zie de instructie in app.js.
MIN_GROOTTE_MEDIA_PLAYLIST = 50_000

# Hoe lang we wachten op een play-knop of <video>-element.
MAX_WACHTTIJD_OP_SPELER_SEC = 12

# Na de klik: hoe lang wachten we op de m3u8 voordat we video.play() proberen.
WACHT_NA_KLIK_SEC = 8

# Url-fragmenten die altijd gelogd worden (welke status ze ook teruggeven).
INTERESSANTE_URL_FRAGMENTEN = ("companywebcast", "agendavideo")

# Directe controle vanaf de runner: komen we bij de SDK zelf?
SONDE_URLS = (
    "https://sdk.companywebcast.com/sdk/player/client.js",
)

# Verbergt de meest voor de hand liggende automatiseringsvlag.
INIT_SCRIPT = "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"


def _grootste_m3u8(gevonden):
    bruikbaar = [r for r in gevonden if r["grootte"] >= MIN_GROOTTE_MEDIA_PLAYLIST]
    kandidaten = bruikbaar or gevonden
    if not kandidaten:
        return None
    return max(kandidaten, key=lambda r: r["grootte"])["url"]


def _media_playlist_binnen(gevonden):
    return any(r["grootte"] >= MIN_GROOTTE_MEDIA_PLAYLIST for r in gevonden)


def _vind_video_element(page):
    """Geeft het frame terug waarin een <video>-element zit, of None."""
    for frame in page.frames:
        try:
            if frame.locator("video").first.count():
                return frame
        except Exception:
            continue
    return None


def _koppel_listeners(page, gevonden, events):
    """Hangt alle logging en de m3u8-detectie aan een pagina."""

    def on_response(response):
        if ".m3u8" in response.url:
            try:
                lengte = int(response.headers.get("content-length", "0"))
            except ValueError:
                lengte = 0
            if lengte == 0:
                # Geen content-length (bv. chunked/gzip): dan de echte
                # lengte van de body meten, anders lijken ze allemaal 0 kB.
                try:
                    lengte = len(response.body())
                except Exception:
                    lengte = 0
            gevonden.append({"url": response.url, "grootte": lengte})
        if any(fragment in response.url for fragment in INTERESSANTE_URL_FRAGMENTEN):
            events["relevante_responses"].append(f"{response.status} — {response.url}")

    def on_console(msg):
        events["console_log"].append(f"[{msg.type}] {msg.text}")

    def on_requestfailed(request):
        events["mislukte_requests"].append(f"{request.url} — {request.failure}")

    def on_pageerror(exc):
        events["js_fouten"].append(str(exc))

    page.on("response", on_response)
    page.on("console", on_console)
    page.on("requestfailed", on_requestfailed)
    page.on("pageerror", on_pageerror)


def _lees_video_id(page):
    """Haalt het data-video-id uit de <div class="cwc"> op de vergaderpagina."""
    try:
        html = page.content()
    except Exception:
        return None
    m = re.search(r"data-video-id\s*=\s*[\"']([^\"']+)[\"']", html)
    return m.group(1).replace("/", "_") if m else None


def _sonde(page, events):
    """Wat ziet de pagina zelf, en bereikt de runner de SDK?"""
    try:
        events["sonde"].append(
            "pagina ziet: " + page.evaluate(
                "() => `UA=${navigator.userAgent} | webdriver=${navigator.webdriver}`"
            )
        )
    except Exception as e:
        events["sonde"].append(f"pagina-sonde mislukt: {e}")
    for sonde_url in SONDE_URLS:
        try:
            antwoord = page.request.get(sonde_url, timeout=10000)
            events["sonde"].append(f"GET {sonde_url} -> {antwoord.status}")
        except Exception as e:
            events["sonde"].append(f"GET {sonde_url} -> mislukt: {e}")


def _schrijf_debug(page, events, agenda_id, label):
    """Schermafbeelding + logbestand (sonde, console, netwerkfouten,
    JS-fouten, relevante request-statussen, iframe-urls) wegschrijven."""
    os.makedirs(DEBUG_DIR, exist_ok=True)
    schermafbeelding = f"{DEBUG_DIR}/{label}_{agenda_id}.png"
    try:
        page.screenshot(path=schermafbeelding, full_page=True)
    except Exception as e:
        schermafbeelding = f"(mislukt: {e})"

    logpad = f"{DEBUG_DIR}/log_{agenda_id}.txt"
    try:
        with open(logpad, "a", encoding="utf-8") as f:
            f.write(f"\n=== {label} ===\n")
            f.write(f"pagina-url: {page.url}\n")
            f.write(f"screenshot: {schermafbeelding}\n")

            f.write("iframes op de pagina:\n")
            for frame in page.frames:
                if frame != page.main_frame:
                    f.write(f"  - {frame.url}\n")

            f.write("sonde (wat ziet de pagina / de SDK vanaf deze runner):\n")
            for regel in events["sonde"]:
                f.write(f"  {regel}\n")

            f.write("relevante requests (companywebcast/agendavideo), status:\n")
            for regel in events["relevante_responses"]:
                f.write(f"  {regel}\n")

            f.write("mislukte requests (netwerkfouten):\n")
            for regel in events["mislukte_requests"]:
                f.write(f"  {regel}\n")

            f.write("onafgevangen JS-fouten (pageerror):\n")
            for regel in events["js_fouten"]:
                f.write(f"  {regel}\n")

            f.write("browserconsole (alles sinds page laden):\n")
            for regel in events["console_log"]:
                f.write(f"  {regel}\n")
    except Exception as e:
        print(f"  ⚠ kon debug-logbestand niet wegschrijven: {e}")

    return schermafbeelding


def _klik_play(page):
    """Klikt op de eerste zichtbare play-knop (hoofdpagina of iframe).
    Geeft de gebruikte selector terug, of None."""
    for frame in page.frames:
        for selector in PLAY_KNOP_SELECTORS:
            try:
                el = frame.locator(selector).first
                if el.count() and el.is_visible(timeout=1000):
                    el.click(timeout=2000)
                    return selector
            except Exception:
                continue
    return None


def _probeer_te_starten(page, gevonden, timeout_sec):
    """Start de video op deze pagina en wacht op de grote media-playlist.
    Geeft True terug als die binnenkwam."""
    # 1. Klikken zodra de knop (of het video-element) er is.
    selector = None
    gewacht = 0
    while selector is None and gewacht < MAX_WACHTTIJD_OP_SPELER_SEC:
        selector = _klik_play(page)
        if selector is None:
            time.sleep(1)
            gewacht += 1
    if selector:
        print(f"  ▶ geklikt op {selector!r} na {gewacht}s wachten")
    else:
        print(f"  ⚠ geen play-knop gevonden op {page.url}")

    # 2. Even wachten op de m3u8-requests.
    gewacht = 0
    while gewacht < WACHT_NA_KLIK_SEC and not _media_playlist_binnen(gevonden):
        time.sleep(1)
        gewacht += 1

    # 3. Terugvaloptie: direct .play() aanroepen op het <video>-element.
    if not _media_playlist_binnen(gevonden):
        frame = _vind_video_element(page)
        if frame is not None:
            try:
                frame.evaluate("document.querySelector('video')?.play()")
                print("  ▶ video.play() aangeroepen als terugvaloptie")
            except Exception as e:
                print(f"  ⚠ video.play() mislukt: {e}")

    # 4. Wachten tot de grote media-playlist binnenkomt (of timeout).
    gewacht = 0
    while gewacht < timeout_sec and not _media_playlist_binnen(gevonden):
        time.sleep(1)
        gewacht += 1

    return _media_playlist_binnen(gevonden)


def haal_video_url_op(agenda_url, agenda_id, timeout_sec=30):
    gevonden = []
    events = {
        "console_log": [],
        "mislukte_requests": [],
        "js_fouten": [],
        "relevante_responses": [],
        "sonde": [],
    }

    with sync_playwright() as p:
        # Autoplay-beleid verruimen: Chrome blokkeert normaal gesproken
        # geluid+video afspelen zonder "echte" gebruikersinteractie.
        browser = p.chromium.launch(args=[
            "--autoplay-policy=no-user-gesture-required",
            "--disable-blink-features=AutomationControlled",
        ])
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            locale="nl-NL",
            timezone_id="Europe/Amsterdam",
            viewport={"width": 1366, "height": 900},
        )
        context.add_init_script(INIT_SCRIPT)

        # 1. De vergaderpagina: alleen nodig om het video-id te lezen
        #    (en als terugvaloptie als de speler los niet wil).
        vergaderpagina = context.new_page()
        _koppel_listeners(vergaderpagina, gevonden, events)
        try:
            vergaderpagina.goto(agenda_url, wait_until="networkidle", timeout=20000)
        except Exception as e:
            print(f"  ⚠ pagina laden mislukt: {e}")

        _sonde(vergaderpagina, events)
        video_id = _lees_video_id(vergaderpagina)
        events["sonde"].append(f"data-video-id op vergaderpagina: {video_id}")
        _schrijf_debug(vergaderpagina, events, agenda_id, "voor_klik")

        # 2. De speler rechtstreeks openen, met de vergaderpagina als Referer.
        kandidaten = []
        if video_id:
            speler = context.new_page()
            _koppel_listeners(speler, gevonden, events)
            speler_url = SPELER_URL.format(video_id=quote(video_id, safe=""))
            events["sonde"].append(f"directe speler-url: {speler_url}")
            print(f"  speler rechtstreeks openen: {speler_url}")
            try:
                speler.goto(
                    speler_url,
                    referer=agenda_url,
                    wait_until="domcontentloaded",
                    timeout=20000,
                )
            except Exception as e:
                print(f"  ⚠ speler laden mislukt: {e}")
            kandidaten.append(("speler", speler))
        else:
            print("  ⚠ geen data-video-id gevonden op de vergaderpagina")
        kandidaten.append(("vergaderpagina", vergaderpagina))

        # 3. Video starten: eerst de speler, dan pas de oude route.
        for naam, pagina in kandidaten:
            if _probeer_te_starten(pagina, gevonden, timeout_sec):
                print(f"  ✓ media-playlist gevonden via {naam}")
                break

        if not _media_playlist_binnen(gevonden):
            for naam, pagina in kandidaten:
                _schrijf_debug(pagina, events, agenda_id, f"geen_video_{naam}")
            print(f"  ⚠ geen (grote) m3u8 gevonden voor {agenda_id} — "
                  f"screenshots en log: {DEBUG_DIR}/ (log_{agenda_id}.txt)")

        browser.close()

    return _grootste_m3u8(gevonden)


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print("Gebruik: python get_video_url.py <agenda_url> <agenda_id>")
        sys.exit(1)
    print(haal_video_url_op(sys.argv[1], sys.argv[2]) or "GEEN URL GEVONDEN")
