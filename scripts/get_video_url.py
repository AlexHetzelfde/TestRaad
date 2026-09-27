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

Eerste echte run (vergadering 8 sept 2026, via GitHub Actions) vond
geen <video>-element en geen play-knop. Een screenshot van dezelfde
pagina in een gewone browser (27-09-2026) liet zien waarom: er staat
een posterscherm met titel/datum/duur en een knop met de tekst
"Start nu" — pas ná die klik ontstaat er een <video>-element. Geen
van de bestaande PLAY_KNOP_SELECTORS matchte die tekst, dus is
"text=Start nu" nu als eerste optie toegevoegd. Nog te bevestigen:
of die klik ook echt de twee sdk-ssl.m3u8-requests triggert zoals bij
de handmatige muisklik.

Ter plekke blijft dit script ook screenshots + een logbestand
(browserconsole + gevonden iframe-urls) wegschrijven naar debug/
zodra er alsnog geen video wordt gevonden, zodat een volgende
mismatch net zo snel te diagnosticeren is als deze.
"""
import os
import time

from playwright.sync_api import sync_playwright

from config import DEBUG_DIR

# Kandidaat-selectors voor de play-knop, van specifiek naar generiek.
# De eerste die zichtbaar is (op de hoofdpagina óf in een iframe), wordt
# aangeklikt.
PLAY_KNOP_SELECTORS = [
    "text=Start nu",                 # bevestigd op de echte pagina (screenshot 27-09-2026): posterscherm met titel/datum/duur en deze knop, vóór er een <video> bestaat
    "button.vjs-big-play-button",   # video.js — veelgebruikte HLS-player
    ".plyr__control--overlaid",     # plyr.io
    "button[aria-label*='play' i]",
    "button[title*='afspelen' i]",
    "video",                        # laatste redmiddel: klik op het element zelf
]

# Grens om de kleine "master playlist" (~3 kB) te onderscheiden van de
# grote "media playlist" (~100-120 kB) — zie de instructie in app.js.
MIN_GROOTTE_MEDIA_PLAYLIST = 50_000

# Hoe lang we blijven pollen op een <video>-element voordat we opgeven
# — losstaand van de m3u8-wachttijd hieronder. Vangt het geval op waarin
# de speler pas ná "networkidle" door een eigen JS-timer verschijnt.
MAX_WACHTTIJD_OP_VIDEO_SEC = 10


def _grootste_m3u8(gevonden):
    bruikbaar = [r for r in gevonden if r["grootte"] >= MIN_GROOTTE_MEDIA_PLAYLIST]
    kandidaten = bruikbaar or gevonden
    if not kandidaten:
        return None
    return max(kandidaten, key=lambda r: r["grootte"])["url"]


def _vind_video_element(page):
    """Geeft het frame terug waarin een <video>-element zit, of None."""
    for frame in [page] + page.frames:
        try:
            if frame.locator("video").first.count():
                return frame
        except Exception:
            continue
    return None


def _schrijf_debug(page, console_log, agenda_id, label):
    """Schermafbeelding + logbestand (console + iframe-urls) wegschrijven."""
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
            f.write(f"screenshot: {schermafbeelding}\n")
            f.write("iframes op de pagina:\n")
            for frame in page.frames:
                if frame != page.main_frame:
                    f.write(f"  - {frame.url}\n")
            f.write("browserconsole (alles sinds page laden):\n")
            for regel in console_log:
                f.write(f"  {regel}\n")
    except Exception as e:
        print(f"  ⚠ kon debug-logbestand niet wegschrijven: {e}")

    return schermafbeelding


def haal_video_url_op(agenda_url, agenda_id, timeout_sec=30):
    gevonden = []
    console_log = []

    with sync_playwright() as p:
        # Autoplay-beleid verruimen: Chrome blokkeert normaal gesproken
        # geluid+video afspelen zonder "echte" gebruikersinteractie. Dit
        # maakt de video.play()-aanroep hieronder betrouwbaar, ook
        # headless op een server.
        browser = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
        page = browser.new_context().new_page()

        def on_response(response):
            if ".m3u8" in response.url:
                try:
                    lengte = int(response.headers.get("content-length", "0"))
                except ValueError:
                    lengte = 0
                gevonden.append({"url": response.url, "grootte": lengte})

        def on_console(msg):
            console_log.append(f"[{msg.type}] {msg.text}")

        page.on("response", on_response)
        page.on("console", on_console)

        try:
            page.goto(agenda_url, wait_until="networkidle", timeout=20000)
        except Exception as e:
            print(f"  ⚠ pagina laden mislukt: {e}")

        # Screenshot vóór elke klikpoging — laat zien wat er al dan niet
        # vanzelf (zonder interactie) op de pagina staat.
        _schrijf_debug(page, console_log, agenda_id, "voor_klik")

        # Even pollen op een <video>-element: soms verschijnt de speler
        # pas een fractie na "networkidle", via een eigen JS-timer die
        # geen netwerkverkeer genereert.
        frame_met_video = _vind_video_element(page)
        gewacht_op_video = 0
        while frame_met_video is None and gewacht_op_video < MAX_WACHTTIJD_OP_VIDEO_SEC:
            time.sleep(1)
            gewacht_op_video += 1
            frame_met_video = _vind_video_element(page)

        # Video proberen te starten — kan in een iframe zitten (bevestigd:
        # de CWC-player draait genest in eigen iframes). Eerst de robuuste
        # route (direct .play() aanroepen op het <video>-element, werkt
        # los van hoe de knop precies is opgebouwd), met de oude
        # knop-klik-aanpak als terugvaloptie.
        gestart = False
        if frame_met_video is not None:
            try:
                frame_met_video.evaluate("document.querySelector('video')?.play()")
                gestart = True
            except Exception:
                pass

        if not gestart:
            for frame in [page] + page.frames:
                for selector in PLAY_KNOP_SELECTORS:
                    try:
                        el = frame.locator(selector).first
                        if el.count() and el.is_visible(timeout=1000):
                            el.click(timeout=2000)
                            gestart = True
                            break
                    except Exception:
                        continue
                if gestart:
                    break

        if not gestart:
            print("  ⚠ geen <video> gevonden en geen play-knop geklikt "
                  "(zie PLAY_KNOP_SELECTORS)")

        # Wachten tot de grote media-playlist binnenkomt (of timeout).
        gewacht = 0
        while gewacht < timeout_sec and not any(
            r["grootte"] >= MIN_GROOTTE_MEDIA_PLAYLIST for r in gevonden
        ):
            time.sleep(1)
            gewacht += 1

        if not gevonden:
            schermafbeelding = _schrijf_debug(page, console_log, agenda_id, "geen_video")
            print(f"  ⚠ geen m3u8 gevonden voor {agenda_id} — "
                  f"screenshot: {schermafbeelding} — log: {DEBUG_DIR}/log_{agenda_id}.txt")

        browser.close()

    return _grootste_m3u8(gevonden)


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print("Gebruik: python get_video_url.py <agenda_url> <agenda_id>")
        sys.exit(1)
    print(haal_video_url_op(sys.argv[1], sys.argv[2]) or "GEEN URL GEVONDEN")
