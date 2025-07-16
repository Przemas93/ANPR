import sys
import os

# Naprawa katalogu uruchamiania dla EXE
if getattr(sys, 'frozen', False):
    # Aplikacja uruchomiona jako EXE
    os.chdir(os.path.dirname(sys.executable))
else:
    # Normalnie jako .py
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

import cv2
from ultralytics import YOLO
import easyocr
import time
import threading
import json
from datetime import datetime
from database import add_plate
import re

# Katalogi na snapshoty i detekcje
os.makedirs('snapshots', exist_ok=True)

# Inicjalizacja modeli
model = YOLO("license_plate_detector.pt")
reader = easyocr.Reader(['pl', 'en'])

def filter_plate(text):
    PLATE_REGEX = re.compile(r"[A-Z]{2,3}[A-Z0-9]{4,5}")
    text = text.upper().replace(" ", "")
    match = PLATE_REGEX.match(text)
    return match.group() if match else None

ACTIVE_THREADS = {}
RUNNING_FLAGS = {}

def process_camera(name, rtsp_url, stop_event, interval=5):
    cap = cv2.VideoCapture(rtsp_url)
    os.makedirs(f'captures/{name}', exist_ok=True)
    print(f"Start kamery: {name}")
    while not stop_event.is_set():
        ret, frame = cap.read()
        if not ret or frame is None:
            print(f"[{name}] Brak klatki, ponawiam za 2 sekundy...")
            time.sleep(2)
            continue

        # --- ZAPIS SNAPSHOTA KAŻDĄ KLATKĘ ---
        snapshot_path = f'snapshots/{name}.jpg'
        cv2.imwrite(snapshot_path, frame)

        # --- ROZPOZNAWANIE TABLIC ---
        results = model(frame)
        found_plate = False
        for r in results:
            for box in r.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                plate_img = frame[y1:y2, x1:x2]
                ocr_result = reader.readtext(plate_img)
                for bbox, text, prob in ocr_result:
                    number = filter_plate(text)
                    if number and prob > 0.5:
                        now = datetime.now().strftime("%Y%m%d_%H%M%S")
                        img_path = f'captures/{name}/{now}.jpg'
                        cv2.imwrite(img_path, frame)
                        add_plate(name, number, img_path)
                        print(f"[{name}] Zapisano: {number} ({img_path})")
                        found_plate = True
                        break
                if found_plate:
                    break
        time.sleep(interval)
    cap.release()
    print(f"[{name}] Zatrzymano kamerę!")

def reload_cameras():
    while True:
        try:
            with open('cameras.json') as f:
                cameras = json.load(f)
        except Exception as e:
            print("Błąd odczytu cameras.json:", e)
            cameras = []

        new_names = set(c['name'] for c in cameras)
        old_names = set(ACTIVE_THREADS.keys())

        # Dodaj nowe kamery
        for cam in cameras:
            if cam['name'] not in ACTIVE_THREADS:
                stop_event = threading.Event()
                RUNNING_FLAGS[cam['name']] = stop_event
                t = threading.Thread(target=process_camera, args=(cam['name'], cam['rtsp_url'], stop_event))
                t.start()
                ACTIVE_THREADS[cam['name']] = t
                print(f"Uruchomiono kamerę {cam['name']}")

        # Zatrzymaj usunięte kamery
        for name in list(old_names - new_names):
            RUNNING_FLAGS[name].set()
            ACTIVE_THREADS[name].join()
            del ACTIVE_THREADS[name]
            del RUNNING_FLAGS[name]
            print(f"Zatrzymano kamerę {name}")

        time.sleep(10)  # co 10 sekund sprawdź cameras.json

if __name__ == '__main__':
    reload_cameras()
