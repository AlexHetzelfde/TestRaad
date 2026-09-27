#!/usr/bin/env python3
"""
Draait de volledige pipeline: nieuwe afgeronde vergaderingen zoeken,
videolink ophalen, downloaden, controleren op telefoongebruik.

Draai dit vanuit de repo-root:
    python scripts/run_pipeline.py
"""
import os

from get_meetings import nieuwe_afgeronde_vergaderingen, markeer_verwerkt
from get_video_url import haal_video_url_op
from download_video import download
from detect import verwerk_video


def main():
    vergaderingen = nieuwe_afgeronde_vergaderingen()
    print(f"{len(vergaderingen)} nieuwe afgeronde vergadering(en) gevonden")

    for v in vergaderingen:
        print(f"\n=== {v['titel']} ({v['id']}) ===")

        url = haal_video_url_op(v["url"], v["id"])
        if not url:
            print("  overslaan: geen videolink gevonden")
            continue

        pad_video = download(url, v["id"])
        if not pad_video:
            print("  overslaan: download mislukt")
            continue

        verwerk_video(pad_video, v["id"], v["titel"])

        os.remove(pad_video)  # ruwe opname niet bewaren, alleen de resultaten/clips
        markeer_verwerkt(v["id"])


if __name__ == "__main__":
    main()
