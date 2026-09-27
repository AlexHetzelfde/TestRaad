# ZaanseScrollers

Detecteert automatisch telefoongebruik door raadsleden tijdens
Zaanstad-raadsvergaderingen, en herkent wie het is via gezichtsherkenning.
Draait volledig via GitHub Actions — geen eigen server nodig.

Geïnspireerd op *The Flemish Scrollers* en gebouwd bovenop wat
[AlexHetzelfde/IbabsLos2](https://github.com/AlexHetzelfde/IbabsLos2) al
had opgelost voor de Zaanstad-iBabs-omgeving (agenda-API, sessie-opzet).
Deze versie voegt de ontbrekende schakel toe: automatisch aan een geldige
videolink komen, plus de telefoon-/gezichtsdetectie zelf.

## ⚠️ Eerlijk over wat wel en niet getest is

- **Wel getest — écht, met bewijs:** de agenda-API in `get_meetings.py`
  (1-op-1 overgenomen van het werkende `scrape_vergaderingen.py` uit
  IbabsLos2), en het hele video-mechanisme is via handmatig
  Network-tab-onderzoek op een echte Zaanstad-vergadering bevestigd:
  pagina laden → automatische accessrules/token-uitwisseling → video
  starten → twee `sdk-ssl.m3u8`-requests (klein = master-playlist,
  groot = media-playlist). De grootte-drempel in `get_video_url.py`
  (50 kB) is precies afgestemd op de echte gemeten waarden (3,6 kB vs
  119 kB). Ook alle packages (playwright, yt-dlp, ultralytics,
  insightface) zijn echt geïnstalleerd, en de enroll→match-logica voor
  gezichtsherkenning is end-to-end getest.
- **Nog niet bevestigd:** of Playwright's eigen `video.play()`-aanroep
  (met verruimd autoplay-beleid) dezelfde requests triggert als de
  handmatige muisklik die dit bewijs opleverde. Dat is de enige stap die
  nog een eerste echte run nodig heeft om zeker te weten. Bij falen
  schrijft het script een screenshot naar `debug/` (en de workflow
  uploadt die als Actions-artifact), zodat meteen zichtbaar is wat er
  op dat moment op het scherm stond.

Kortom: het fundament is nu met echt bewijs onderbouwd, niet met
aannames — alleen de allerlaatste trigger-stap verdient nog één
geslaagde proefrun voordat je het blind vertrouwt.

## Hoe het werkt

1. **`get_meetings.py`** — vraagt de iBabs Calendar-API
   (`/Calendar/GetAgendasForCalendar`) naar raadsvergaderingen die
   recent zijn afgelopen en nog niet verwerkt zijn.
2. **`get_video_url.py`** — opent de vergaderpagina headless, start de
   video, en luistert het netwerkverkeer af op de getekende `.m3u8`-link
   (automatisering van de handmatige DevTools-stap uit IbabsLos2).
3. **`download_video.py`** — geeft die url (verloopt na ~2 uur) meteen
   door aan `yt-dlp` om de opname te downloaden.
4. **`detect.py`** — loopt door de video heen (elke paar seconden een
   frame), herkent telefoons met YOLOv8n (pretrained, geen training
   nodig — "cell phone" zit al in de COCO-klassen), en probeert bij een
   treffer het gezicht te matchen met `data/face_encodings.json`.
5. **`run_pipeline.py`** — knoopt dit alles aan elkaar en ruimt de ruwe
   video na afloop weer op.

Alles draait binnen één GitHub Actions-run: een tijdelijke VM die start,
het werk doet, de resultaten commit, en weer verdwijnt. Er staat dus
nooit iets 24/7 "aan".

## Aan de slag

1. **Foto's toevoegen** in `raadsleden/` — één foto per raadslid,
   bestandsnaam = naam (zie `raadsleden/README.md`).
2. **Lokaal proberen** (aanrader vóór je 'm op GitHub zet) — altijd
   vanuit de repo-root, **nooit** met `cd scripts` ervoor (dan kloppen
   de relatieve paden naar `data/` niet meer — dit tikte ik er zelf
   tijdens het testen ook nog per ongeluk in):
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   python scripts/enroll_faces.py
   python scripts/run_pipeline.py
   ```
3. **Naar GitHub pushen** — maak een nieuwe (gerust publieke) lege repo
   op GitHub, en dan vanuit deze map:
   ```bash
   git init
   git add .
   git commit -m "eerste versie"
   git branch -M main
   git remote add origin <jouw-nieuwe-repo-url>
   git push -u origin main
   ```
4. De workflow in `.github/workflows/pipeline.yml` draait vanaf dan
   automatisch (elke 2 uur, aan te passen), en is ook handmatig te
   starten via het tabblad **Actions** → **Run workflow**.

## Waarom deze keuzes

- **Publieke repo**: GitHub Actions-minuten zijn dan vrijwel onbeperkt
  gratis. Bij een private repo geldt een maandelijkse gratis limiet.
- **insightface i.p.v. face_recognition/dlib**: dlib compileren kost in
  Actions elke run een paar minuten extra en faalt daar soms; insightface
  heeft kant-en-klare wheels (downloadt wel eenmalig een ~300 MB model).
- **YOLOv8n (nano)**: kleinste variant, haalbaar op de CPU-only
  Actions-runner. Grotere meetings (uren lang) laten de pipeline
  overeenkomstig langer draaien — dit is bewust niet geoptimaliseerd
  voor snelheid, wel voor eenvoud.
- **Geen posting-stap**: op verzoek weggelaten. Resultaten (`data/resultaten.json`)
  en korte clips (`data/clips/`) worden alleen opgeslagen, niet gepost.

## Privacy/juridisch

Gezichtsherkenning van identificeerbare personen en het bewaren van
clips daarvan valt onder de AVG (bijzondere/biometrische
persoonsgegevens), ook zonder dat je iets post. De moeite waard om even
bij stil te staan voor je dit op een echte raad loslaat.
