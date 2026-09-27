#!/usr/bin/env python3
"""
Doorzoekt een gedownloade vergadering-video op frames met een telefoon,
en probeert bij zo'n frame te herkennen welk raadslid het is.

Telefoon-detectie: pretrained YOLOv8n (COCO-klasse "cell phone" zit er
al standaard in — geen eigen training nodig).
Gezichtsherkenning: insightface, vergeleken met data/face_encodings.json
(gebouwd door enroll_faces.py).
"""
import json
import os
import subprocess

import cv2
import numpy as np

from config import ENCODINGS_PAD, RESULTATEN_PAD, CLIPS_DIR

FRAME_INTERVAL_SEC = 2         # niet elk frame checken, om tijd te besparen
PHONE_CONF_DREMPEL = 0.4
GEZICHT_AFSTAND_DREMPEL = 0.9   # lager = strenger matchen
CLIP_LENGTE_SEC = 10

_yolo = None
_face_app = None


def _laad_modellen():
    global _yolo, _face_app
    if _yolo is None:
        from ultralytics import YOLO
        _yolo = YOLO("yolov8n.pt")
    if _face_app is None:
        from insightface.app import FaceAnalysis
        _face_app = FaceAnalysis(name="buffalo_l")
        _face_app.prepare(ctx_id=-1)


def _laad_bekende_gezichten():
    if not os.path.exists(ENCODINGS_PAD):
        return {}
    with open(ENCODINGS_PAD, encoding="utf-8") as f:
        return {naam: np.array(emb) for naam, emb in json.load(f).items()}


def _match_gezicht(embedding, bekend):
    beste_naam, beste_afstand = "onbekend", GEZICHT_AFSTAND_DREMPEL
    for naam, ref in bekend.items():
        afstand = float(np.linalg.norm(embedding - ref))
        if afstand < beste_afstand:
            beste_naam, beste_afstand = naam, afstand
    return beste_naam


def _knip_clip(pad_video, tijdstip_sec, agenda_id, index):
    os.makedirs(CLIPS_DIR, exist_ok=True)
    start = max(0, tijdstip_sec - CLIP_LENGTE_SEC / 2)
    clip_pad = f"{CLIPS_DIR}/{agenda_id}_{index}.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(start), "-i", pad_video,
         "-t", str(CLIP_LENGTE_SEC), "-c", "copy", clip_pad],
        capture_output=True,
    )
    return clip_pad if os.path.exists(clip_pad) else None


def _bewaar_resultaten(nieuwe_hits):
    bestaand = []
    if os.path.exists(RESULTATEN_PAD):
        with open(RESULTATEN_PAD, encoding="utf-8") as f:
            bestaand = json.load(f)
    bestaand.extend(nieuwe_hits)
    os.makedirs(os.path.dirname(RESULTATEN_PAD), exist_ok=True)
    with open(RESULTATEN_PAD, "w", encoding="utf-8") as f:
        json.dump(bestaand, f, ensure_ascii=False, indent=2)


def verwerk_video(pad_video, agenda_id, titel):
    _laad_modellen()
    bekend = _laad_bekende_gezichten()

    cap = cv2.VideoCapture(pad_video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    stap = max(1, int(fps * FRAME_INTERVAL_SEC))

    hits = []
    frame_nr = 0
    while True:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_nr)
        ok, frame = cap.read()
        if not ok:
            break

        resultaten = _yolo.predict(frame, verbose=False)
        telefoon_gevonden = any(
            _yolo.names[int(box.cls)] == "cell phone" and float(box.conf) > PHONE_CONF_DREMPEL
            for r in resultaten for box in r.boxes
        )

        if telefoon_gevonden:
            tijdstip_sec = frame_nr / fps
            for gezicht in _face_app.get(frame):
                naam = _match_gezicht(gezicht.normed_embedding, bekend)
                clip_pad = _knip_clip(pad_video, tijdstip_sec, agenda_id, len(hits))
                hits.append({
                    "vergadering_id": agenda_id,
                    "titel": titel,
                    "tijdstip_sec": round(tijdstip_sec, 1),
                    "raadslid": naam,
                    "clip": clip_pad,
                })
                print(f"  📱 {naam} bij {tijdstip_sec:.0f}s")

        frame_nr += stap

    cap.release()
    _bewaar_resultaten(hits)
    return hits
