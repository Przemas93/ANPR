import os
import sys
import json
import cv2
import numpy as np
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, flash, Response, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import threading
import time
from datetime import datetime
from ultralytics import YOLO
import easyocr
import re

# --- Helpers ---
def clean_plate_text(text):
    return re.sub(r'[^A-Z0-9]', '', text)

def easyocr_plate(plate_img):
    scale = 2
    h, w = plate_img.shape[:2]
    if h == 0 or w == 0:
        return ""
    plate_img = cv2.resize(plate_img, (w*scale, h*scale), interpolation=cv2.INTER_CUBIC)
    reader = easyocr.Reader(['pl', 'en'], gpu=False)
    img_rgb = cv2.cvtColor(plate_img, cv2.COLOR_BGR2RGB)
    result = reader.readtext(img_rgb, detail=0, allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')
    if result:
        return clean_plate_text(result[0])
    return ""

def load_users():
    if not os.path.isfile("users.json"):
        return {}
    with open("users.json", encoding="utf-8") as f:
        return json.load(f)

def save_users(users):
    with open("users.json", "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2, ensure_ascii=False)

def load_cameras():
    if not os.path.isfile("cameras.json"):
        return []
    with open("cameras.json", encoding="utf-8") as f:
        return json.load(f)

def save_cameras(cameras):
    with open("cameras.json", "w", encoding="utf-8") as f:
        json.dump(cameras, f, indent=2, ensure_ascii=False)

def load_detections():
    if not os.path.isfile("detections.json"):
        return []
    with open("detections.json", encoding="utf-8") as f:
        return json.load(f)

def save_detection(detection):
    detections = load_detections()
    detections.append(detection)
    with open("detections.json", "w", encoding="utf-8") as f:
        json.dump(detections, f, indent=2, ensure_ascii=False)

def load_wanted():
    if not os.path.isfile("wanted.json"):
        return []
    with open("wanted.json", encoding="utf-8") as f:
        try:
            return json.load(f)
        except:
            return []
def save_wanted(wanted):
    with open("wanted.json", "w", encoding="utf-8") as f:
        json.dump(wanted, f, indent=2, ensure_ascii=False)

# --- Flask Setup ---
app = Flask(__name__)
app.secret_key = 'tajnyklucz123'
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
USERS = load_users()

class User(UserMixin):
    def __init__(self, username, role):
        self.id = username
        self.role = role

@login_manager.user_loader
def load_user(user_id):
    user = USERS.get(user_id)
    if user:
        return User(user_id, user["role"])
    return None

@app.context_processor
def inject_user():
    from flask_login import current_user
    return dict(user=current_user)

# --- YOLO model ---
yolo_model = YOLO("license_plate_detector.pt")

# --- Background Worker: detekcja tablic ---
def background_snapshot_worker(interval=5):
    while True:
        try:
            cameras = load_cameras()
            for cam in cameras:
                rtsp_url = cam["rtsp_url"]
                name = cam["name"]
                roi = cam.get("roi")
                cap = cv2.VideoCapture(rtsp_url)
                ret, frame = cap.read()
                cap.release()
                if not ret:
                    continue
                os.makedirs("snapshots", exist_ok=True)
                path = f"snapshots/{name}.jpg"
                cv2.imwrite(path, frame)
                # ROI
                frame_roi = frame
                if roi:
                    img_h, img_w = frame.shape[:2]
                    scale_x = img_w / 320
                    scale_y = img_h / 180
                    x1 = int(roi['x1'] * scale_x)
                    y1 = int(roi['y1'] * scale_y)
                    x2 = int(roi['x2'] * scale_x)
                    y2 = int(roi['y2'] * scale_y)
                    x1, y1 = max(0, x1), max(0, y1)
                    x2, y2 = min(img_w-1, x2), min(img_h-1, y2)
                    frame_roi = frame[y1:y2, x1:x2].copy()
                results = yolo_model(frame_roi)
                for box in results[0].boxes.xyxy.cpu().numpy():
                    x1_box, y1_box, x2_box, y2_box = map(int, box)
                    # Przesuń do oryginału jeśli roi
                    if roi:
                        img_h, img_w = frame.shape[:2]
                        scale_x = img_w / 320
                        scale_y = img_h / 180
                        dx = int(roi['x1'] * scale_x)
                        dy = int(roi['y1'] * scale_y)
                        x1_box += dx
                        x2_box += dx
                        y1_box += dy
                        y2_box += dy
                    plate_img = frame[y1_box:y2_box, x1_box:x2_box]
                    try:
                        plate_number = easyocr_plate(plate_img)
                    except Exception as e:
                        print("OCR error:", e)
                        plate_number = ""
                    print(f"[{name}] Wykryta tablica: {plate_number}")

                    # --- Zapis detekcji ---
                    plate_name = f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_plate.jpg"
                    plate_path = os.path.join("captures", plate_name)
                    os.makedirs("captures", exist_ok=True)
                    cv2.imwrite(plate_path, plate_img)
                    full_name = f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_full.jpg"
                    full_path = os.path.join("captures", full_name)
                    cv2.imwrite(full_path, frame)
                    save_detection({
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "camera": name,
                        "number": plate_number,
                        "img_path": plate_path.replace("\\", "/"),
                        "full_img_path": full_path.replace("\\", "/")
                    })
        except Exception as e:
            print("Błąd w workerze snapshotów:", e)
        time.sleep(interval)

# --- ROI endpoint ---
@app.route('/set_roi', methods=['POST'])
@login_required
def set_roi():
    if current_user.role != "admin":
        return jsonify({"status":"error", "msg":"Brak uprawnień"})
    data = request.get_json()
    camera = data.get('camera')
    roi = data.get('roi')
    cameras = load_cameras()
    for cam in cameras:
        if cam["name"] == camera:
            cam["roi"] = roi
    save_cameras(cameras)
    return jsonify({"status":"ok"})

# --- Reszta tras: login, logout, panel, users, etc. (jak poprzednio) ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = USERS.get(username)
        if user and user['password'] == password:
            user_obj = User(username, user["role"])
            login_user(user_obj)
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error="Błędny login lub hasło")
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route("/", methods=["GET"])
@login_required
def index():
    detections = load_detections()
    return render_template("index.html", detections=detections, user=current_user)

@app.route('/live')
@login_required
def live():
    cameras = load_cameras()
    return render_template('live.html', cameras=cameras, user=current_user)

# ... i reszta Twoich tras (users, cameras, wanted, export, etc.)

if __name__ == "__main__":
    t = threading.Thread(target=background_snapshot_worker, daemon=True)
    t.start()
    app.run(debug=True)
