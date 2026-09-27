#!/usr/bin/env python3
"""
Download een vergadering-opname via de (tijdelijke!) HLS-url met yt-dlp.
Moet meteen na get_video_url.py aangeroepen worden — de link verloopt
na ongeveer 2 uur (zie IbabsLos2/app.js).
"""
import os
import subprocess

from config import DOWNLOADS_DIR


def download(hls_url, agenda_id):
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)
    pad = f"{DOWNLOADS_DIR}/vergadering_{agenda_id}.ts"

    resultaat = subprocess.run(
        ["yt-dlp", hls_url, "-o", pad],
        capture_output=True, text=True,
    )
    if resultaat.returncode != 0:
        print("  ⚠ yt-dlp-fout:")
        print("  " + resultaat.stderr[-1500:].replace("\n", "\n  "))
        return None

    return pad if os.path.exists(pad) else None
