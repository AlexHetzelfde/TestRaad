#!/usr/bin/env python3
"""
Bouwt gezicht-embeddings op van referentiefoto's in raadsleden/.
Bestandsnaam (zonder extensie) = naam van het raadslid, bv.
raadsleden/Jan_Jansen.jpg -> "Jan Jansen" (underscore wordt spatie).

Draai dit opnieuw elke keer dat er foto's bijkomen of wijzigen:
    python scripts/enroll_faces.py

Gebruikt insightface i.p.v. face_recognition/dlib: dlib compileren kost
in GitHub Actions elke keer een paar minuten extra en faalt daar soms;
insightface heeft kant-en-klare wheels en downloadt zijn eigen model
(buffalo_l, ~300 MB) bij de eerste keer gebruiken.
"""
import glob
import json
import os

import cv2

from config import ENCODINGS_PAD, RAADSLEDEN_DIR


def bouw_database():
    from insightface.app import FaceAnalysis  # pas hier importeren: kost tijd bij laden

    app = FaceAnalysis(name="buffalo_l")
    app.prepare(ctx_id=-1)  # -1 = CPU

    database = {}
    bestanden = sorted(
        glob.glob(f"{RAADSLEDEN_DIR}/*.jpg")
        + glob.glob(f"{RAADSLEDEN_DIR}/*.jpeg")
        + glob.glob(f"{RAADSLEDEN_DIR}/*.png")
    )

    if not bestanden:
        print(f"Geen foto's gevonden in {RAADSLEDEN_DIR}/ — niks te doen.")
        return

    for pad in bestanden:
        naam = os.path.splitext(os.path.basename(pad))[0].replace("_", " ")
        img = cv2.imread(pad)
        if img is None:
            print(f"  ⚠ kon {pad} niet lezen, overslaan")
            continue

        gezichten = app.get(img)
        if not gezichten:
            print(f"  ⚠ geen gezicht gevonden in {pad}, overslaan")
            continue
        if len(gezichten) > 1:
            print(f"  ⚠ meerdere gezichten in {pad} — grootste wordt gebruikt")
            gezichten.sort(key=lambda g: (g.bbox[2] - g.bbox[0]) * (g.bbox[3] - g.bbox[1]))

        database[naam] = gezichten[-1].normed_embedding.tolist()
        print(f"  ✓ {naam}")

    os.makedirs(os.path.dirname(ENCODINGS_PAD), exist_ok=True)
    with open(ENCODINGS_PAD, "w", encoding="utf-8") as f:
        json.dump(database, f, indent=2)

    print(f"\n{len(database)} raadslid/leden vastgelegd in {ENCODINGS_PAD}")


if __name__ == "__main__":
    bouw_database()
