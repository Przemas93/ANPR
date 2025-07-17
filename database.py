# database.py
import json
import os
from datetime import datetime

DETECTIONS_PATH = "detections.json"

def load_detections():
    if not os.path.isfile(DETECTIONS_PATH):
        return []
    with open(DETECTIONS_PATH, encoding="utf-8") as f:
        return json.load(f)

def save_detections(data):
    with open(DETECTIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def add_plate(timestamp, camera, number, img_path, full_img_path):
    detections = load_detections()
    detections.append({
        "timestamp": timestamp,
        "camera": camera,
        "number": number,
        "img_path": img_path,
        "full_img_path": full_img_path
    })
    save_detections(detections)
