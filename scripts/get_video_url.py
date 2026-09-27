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

Nog niet bevestigd: of Playwright's eigen (gesimuleerde) klik/`play()`
dezelfde requests triggert als de handmatige muisklik die dit opleverde
— vandaar dat zowel een directe `video.play()`-aanroep (met verruimd
autoplay-beleid) als de oude knop-klik-fallback hieronder staan.
"""
import os
import time

from playwright.sync_api import sync_playwright

from config import DEBUG_DIR

# Kandidaat-selectors voor de play-knop, van specifiek naar generiek.
# De eerste die zichtbaar is (op de hoofdpagina óf in een iframe), wordt
# aangeklikt.
PLAY_KNOP_SELECTORS = [
    "button.vjs-big-play-button",   # video.js — veelgebruikte HLS-player
    ".plyr__control--overlaid",     # plyr.io
    "button[aria-label*='play' i]",
    "button[title*='afspelen' i]",
    "video",                        # laatste redmiddel: klik op het element zelf
]

# Grens om de kleine "master playlist" (~3 kB) te onderscheiden van de
# grote "media playlist" (~100-120 kB) — zie de instructie in app.js.
MIN_GROOTTE_MEDIA_PLAYLIST = 50_000


def _grootste_m3u8(gevonden):
    bruikbaar = [r for r in gevonden if r["grootte"] >= MIN_GROOTTE_MEDIA_PLAYLIST]
    kandidaten = bruikbaar or gevonden
    if not kandidaten:
        return None
    return max(kandidaten, key=lambda r: r["grootte"])["url"]


def haal_video_url_op(agenda_url, agenda_id, timeout_sec=30):
    gevonden = []

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

        page.on("response", on_response)

        try:
            page.goto(agenda_url, wait_until="networkidle", timeout=20000)
        except Exception as e:
            print(f"  ⚠ pagina laden mislukt: {e}")

        # Video proberen te starten — kan in een iframe zitten (bevestigd:
        # de CWC-player draait genest in eigen iframes). Eerst de robuuste
        # route (direct .play() aanroepen op het <video>-element, werkt
        # los van hoe de knop precies is opgebouwd), met de oude
        # knop-klik-aanpak als terugvaloptie.
        gestart = False
        for frame in [page] + page.frames:
            try:
                if frame.locator("video").first.count():
                    frame.evaluate("document.querySelector('video')?.play()")
                    gestart = True
                    break
            except Exception:
                continue

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
            os.makedirs(DEBUG_DIR, exist_ok=True)
            schermafbeelding = f"{DEBUG_DIR}/geen_video_{agenda_id}.png"
            try:
                page.screenshot(path=schermafbeelding, full_page=True)
            except Exception:
                pass
            print(f"  ⚠ geen m3u8 gevonden voor {agenda_id} — "
                  f"screenshot: {schermafbeelding}")

        browser.close()

    return _grootste_m3u8(gevonden)


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print("Gebruik: python get_video_url.py <agenda_url> <agenda_id>")
        sys.exit(1)
    print(haal_video_url_op(sys.argv[1], sys.argv[2]) or "GEEN URL GEVONDEN")
