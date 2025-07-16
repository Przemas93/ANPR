import os
import sys
import json
import cv2
import numpy as np
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, flash, Response, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import threading
import time
from datetime import datetime, timedelta
from ultralytics import YOLO
import easyocr
import pytesseract
from PIL import Image
import re

# ========== Lista poszukiwanych ==========
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

# ========== OCR, preprocessing, etc. ==========
def clean_plate_text(text):
    text = re.sub(r'[^A-Z0-9]', '', text)
    return text

def tesseract_ocr_plate(plate_img):
    if len(plate_img.shape) == 2:
        gray = plate_img
    elif plate_img.shape[2] == 4:
        gray = cv2.cvtColor(plate_img, cv2.COLOR_BGRA2GRAY)
    else:
        gray = cv2.cvtColor(plate_img, cv2.COLOR_BGR2GRAY)

    # Przycinanie górnej części tablicy, by uniknąć paska UE
    h = gray.shape[0]
    cropped = gray[:, int(0.1 * gray.shape[1]):int(0.9 * gray.shape[1])]  # obetnij boki
    cropped = cropped[int(0.1 * h):, :]  # obetnij górę (np. niebieski pasek)

    blur = cv2.GaussianBlur(cropped, (3,3), 0)
    _, thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    pil_img = Image.fromarray(thresh)
    custom_config = r'--oem 3 --psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
    text = pytesseract.image_to_string(pil_img, config=custom_config)
    text = text.strip().replace("\n", "")
    return text

def preprocess_plate(plate_img):
    gray = cv2.cvtColor(plate_img, cv2.COLOR_BGR2GRAY) if len(plate_img.shape) == 3 else plate_img
    blur = cv2.GaussianBlur(gray, (3,3), 0)
    return blur

# ========== MODEL INICJALIZACJA ==========
yolo_model = YOLO("license_plate_detector.pt")
ocr_reader = easyocr.Reader(['pl', 'en'])

# === RESZTA KODU BEZ ZMIAN === (pozostaje taka jak w Twojej wersji, nie trzeba jej modyfikować)


def load_detections():
    try:
        if not os.path.isfile("detections.json"):
            return []
        with open("detections.json", encoding="utf-8") as f:
            data = f.read().strip()
            if not data:
                return []
            return json.loads(data)
    except Exception as e:
        print("Błąd ładowania detections.json:", e)
        return []

def save_detection(detection):
    detections = load_detections()
    detections.append(detection)
    with open("detections.json", "w", encoding="utf-8") as f:
        json.dump(detections, f, indent=2, ensure_ascii=False)

# ========================== FLASK - setup ===========================
if getattr(sys, 'frozen', False):
    os.chdir(os.path.dirname(sys.executable))
else:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

app = Flask(__name__)
app.secret_key = 'tajnyklucz123'

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

def load_users():
    with open("users.json", encoding="utf-8") as f:
        return json.load(f)

def save_users(users):
    with open("users.json", "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2, ensure_ascii=False)

USERS = load_users()

def load_cameras():
    with open("cameras.json", encoding="utf-8") as f:
        return json.load(f)

def save_cameras(cameras):
    with open("cameras.json", "w", encoding="utf-8") as f:
        json.dump(cameras, f, indent=2, ensure_ascii=False)

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

# ========================== GŁÓWNY WORKER ===========================
latest_wanted_alarm = {}

def background_snapshot_worker(interval=5):
    global latest_wanted_alarm
    while True:
        try:
            wanted = set([n.upper() for n in load_wanted()])
            cameras = load_cameras()
            for cam in cameras:
                rtsp_url = cam["rtsp_url"]
                name = cam["name"]
                roi = cam.get("roi")
                cap = cv2.VideoCapture(rtsp_url)
                ret, frame = cap.read()
                cap.release()
                if ret:
                    os.makedirs("snapshots", exist_ok=True)
                    path = f"snapshots/{name}.jpg"
                    cv2.imwrite(path, frame)
                    # ---- ROI zastosowanie ----
                    frame_roi = frame
                    if roi:
                        h, w = frame.shape[:2]
                        x1 = int(roi['x1'] * w / 320)
                        y1 = int(roi['y1'] * h / 180)
                        x2 = int(roi['x2'] * w / 320)
                        y2 = int(roi['y2'] * h / 180)
                        x1, y1 = max(0, x1), max(0, y1)
                        x2, y2 = min(w-1, x2), min(h-1, y2)
                        frame_roi = frame[y1:y2, x1:x2].copy()
                    results = yolo_model(frame_roi)
                    for box in results[0].boxes.xyxy.cpu().numpy():
                        x1_box, y1_box, x2_box, y2_box = map(int, box)
                        # Jeśli roi: przesunięcie współrzędnych do oryginału
                        if roi:
                            dx = int(roi['x1'] * frame.shape[1] / 320)
                            dy = int(roi['y1'] * frame.shape[0] / 180)
                            x1_box += dx
                            x2_box += dx
                            y1_box += dy
                            y2_box += dy
                        plate_img = frame[y1_box:y2_box, x1_box:x2_box]
                        try:
                            proc_img = preprocess_plate(plate_img)
                        except Exception as e:
                            print("Błąd preprocessingu:", e)
                            proc_img = plate_img
                        plate_number = ""
                        try:
                            plate_number = tesseract_ocr_plate(proc_img)
                            plate_number = clean_plate_text(plate_number)
                            if len(plate_number) < 4:
                                raise ValueError("Tesseract fail")
                        except Exception as e:
                            ocr_result = ocr_reader.readtext(proc_img)
                            if ocr_result:
                                plate_number = clean_plate_text(ocr_result[0][1])
                            else:
                                plate_number = ""
                        print(f"[{name}] Wykryta tablica: {plate_number}")

                        # ---- ALARM, jeśli numer na liście poszukiwanych! ----
                        if plate_number and plate_number.upper() in wanted:
                            alarm_img = f"captures/{name}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_plate.jpg"
                            alarm_full = f"captures/{name}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_full.jpg"
                            latest_wanted_alarm = {
                                "number": plate_number,
                                "camera": name,
                                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "img_path": alarm_img,
                                "full_img_path": alarm_full
                            }
                            os.makedirs("captures", exist_ok=True)
                            cv2.imwrite(alarm_img, plate_img)
                            cv2.imwrite(alarm_full, frame)

                        # --- Zwykła detekcja ---
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

# --- API do sprawdzania alarmu przez przeglądarkę (AJAX) ---
@app.route('/wanted_alarm')
@login_required
def wanted_alarm():
    global latest_wanted_alarm
    if latest_wanted_alarm and (datetime.now() - datetime.strptime(latest_wanted_alarm['timestamp'], "%Y-%m-%d %H:%M:%S")).total_seconds() < 60:
        return jsonify(latest_wanted_alarm)
    else:
        return jsonify({})

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

@app.route('/delete/<uid>', methods=['POST'])
@login_required
def delete_plate(uid):
    detections = load_detections()
    try:
        ts, cam, num = uid.split('-', 2)
    except:
        flash("Nieprawidłowy UID!", "danger")
        return redirect(url_for('index'))
    new_detections = []
    found = False
    for d in detections:
        if d["timestamp"] == ts and d["camera"] == cam and d["number"] == num:
            found = True
            continue
        new_detections.append(d)
    if found:
        with open("detections.json", "w", encoding="utf-8") as f:
            json.dump(new_detections, f, indent=2, ensure_ascii=False)
        flash("Wpis usunięty!", "success")
    else:
        flash("Nie znaleziono wpisu do usunięcia!", "danger")
    return redirect(url_for('index',
        number=request.args.get('number',''),
        camera=request.args.get('camera',''),
        from_=request.args.get('from_',''),
        to=request.args.get('to','')))

@app.route('/live')
@login_required
def live():
    cameras = load_cameras()
    for cam in cameras:
        if 'roi' not in cam:
            cam['roi'] = None
    return render_template('live.html', cameras=cameras)

@app.route('/admin')
@login_required
def admin():
    if current_user.role != "admin":
        return "Brak dostępu! Tylko administrator."
    return "To jest panel administratora!"

@app.route('/users', methods=['GET', 'POST'])
@login_required
def manage_users():
    if current_user.role != "admin":
        return "Brak dostępu!"
    users = load_users()
    msg = ""
    if request.method == "POST":
        if 'new_user' in request.form:
            username = request.form["new_user"].strip()
            password = request.form["new_pass"].strip()
            role = request.form["new_role"]
            if not username or not password:
                msg = "Uzupełnij wszystkie pola."
            elif username in users:
                msg = "Taki użytkownik już istnieje!"
            else:
                users[username] = {"password": password, "role": role}
                save_users(users)
                msg = "Dodano użytkownika!"
        if 'change_pass' in request.form:
            username = request.form["change_pass"]
            password = request.form["new_pass2"].strip()
            if username in users:
                users[username]["password"] = password
                save_users(users)
                msg = "Hasło zmienione!"
            else:
                msg = "Nie ma takiego użytkownika!"
        if 'delete_user' in request.form:
            username = request.form["delete_user"]
            if username in users:
                if username == "admin":
                    msg = "Nie można usunąć konta admin!"
                else:
                    users.pop(username)
                    save_users(users)
                    msg = f"Usunięto użytkownika {username}!"
            else:
                msg = "Nie znaleziono takiego użytkownika."
    return render_template("users.html", users=users, msg=msg)

@app.route('/admin/cameras', methods=['GET', 'POST'])
@login_required
def admin_cameras():
    if current_user.role != "admin":
        return "Brak dostępu!"
    cameras = load_cameras()
    msg = ""
    if request.method == "POST":
        if 'add_camera' in request.form:
            name = request.form["cam_name"].strip()
            rtsp_url = request.form["cam_url"].strip()
            if name and rtsp_url:
                for c in cameras:
                    if c["name"] == name:
                        msg = "Kamera o tej nazwie już istnieje!"
                        break
                else:
                    cameras.append({"name": name, "rtsp_url": rtsp_url})
                    save_cameras(cameras)
                    msg = "Dodano kamerę!"
            else:
                msg = "Uzupełnij wszystkie pola."
        if 'delete_camera' in request.form:
            name = request.form["delete_camera"]
            cameras = [c for c in cameras if c["name"] != name]
            save_cameras(cameras)
            msg = f"Usunięto kamerę {name}!"
        if 'edit_camera' in request.form:
            old_name = request.form["edit_camera"]
            new_name = request.form["edit_name"].strip()
            new_url = request.form["edit_url"].strip()
            if not new_name or not new_url:
                msg = "Uzupełnij wszystkie pola."
            else:
                for c in cameras:
                    if c["name"] == old_name:
                        c["name"] = new_name
                        c["rtsp_url"] = new_url
                        save_cameras(cameras)
                        msg = f"Zmieniono kamerę {old_name}!"
                        break
    return render_template("admin_cameras.html", cameras=cameras, msg=msg)

@app.route('/export_csv')
@login_required
def export_csv():
    detections = load_detections()
    def generate():
        data = [["Data", "Kamera", "Numer", "Zdjęcie"]]
        for d in detections:
            data.append([
                d.get("timestamp", ""),
                d.get("camera", ""),
                d.get("number", ""),
                d.get("img_path", "")
            ])
        output = []
        for row in data:
            output.append(";".join(map(str, row)))
        return "\n".join(output)
    return Response(
        generate(),
        mimetype='text/csv',
        headers={"Content-Disposition": "attachment;filename=detekcje.csv"}
    )

@app.route('/wanted', methods=["GET", "POST"])
@login_required
def manage_wanted():
    msg = ""
    wanted = load_wanted()
    if request.method == "POST":
        if "new_number" in request.form:
            num = clean_plate_text(request.form["new_number"].strip().upper())
            if num and num not in wanted:
                wanted.append(num)
                save_wanted(wanted)
                msg = f"Dodano: {num}"
            else:
                msg = "Numer już istnieje lub jest pusty."
        if "delete_number" in request.form:
            num = request.form["delete_number"]
            if num in wanted:
                wanted.remove(num)
                save_wanted(wanted)
                msg = f"Usunięto: {num}"
    return render_template("wanted.html", wanted=wanted, msg=msg)

@app.route('/captures/<path:filename>')
@login_required
def get_capture(filename):
    return send_from_directory("captures", filename)

@app.route('/snapshot/<camera>')
@login_required
def snapshot(camera):
    path = f"snapshots/{camera}.jpg"
    if os.path.isfile(path):
        return send_from_directory("snapshots", f"{camera}.jpg")
    else:
        return "Brak obrazu", 404

@app.route('/stream/<camera>')
@login_required
def stream(camera):
    cameras = load_cameras()
    cam = next((c for c in cameras if c["name"] == camera), None)
    if not cam:
        return "Brak takiej kamery", 404
    def gen_mjpeg(rtsp_url):
        cap = cv2.VideoCapture(rtsp_url)
        if not cap.isOpened():
            placeholder = np.zeros((360, 640, 3), dtype=np.uint8)
            _, jpeg = cv2.imencode('.jpg', placeholder)
            while True:
                yield (b'--frame\r\n'
                    b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
        while True:
            ret, frame = cap.read()
            if not ret:
                continue
            ret, jpeg = cv2.imencode('.jpg', frame)
            if not ret:
                continue
            yield (b'--frame\r\n'
                b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
        cap.release()
    return Response(gen_mjpeg(cam["rtsp_url"]), mimetype='multipart/x-mixed-replace; boundary=frame')

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
    number = request.args.get("number", "").strip()
    camera = request.args.get("camera", "").strip()
    from_date = request.args.get("from_", "")
    to_date = request.args.get("to", "")

    results = []
    for d in detections:
        if number and number.lower() not in d["number"].lower():
            continue
        if camera and camera.lower() not in d["camera"].lower():
            continue
        if from_date and d["timestamp"][:10] < from_date:
            continue
        if to_date and d["timestamp"][:10] > to_date:
            continue
        results.append(d)
    return render_template("index.html", plates=results)

@app.route("/delete_multiple", methods=["POST"])
@login_required
def delete_multiple():
    if current_user.role != "admin":
        flash("Brak uprawnień!", "danger")
        return redirect(url_for("index"))
    indices = request.form.getlist("delete_idx")
    if not indices:
        flash("Nie wybrano żadnych wpisów do usunięcia.", "warning")
        return redirect(url_for("index"))

    try:
        indices = sorted([int(i) for i in indices], reverse=True)
        detections = load_detections()
        for idx in indices:
            if 0 <= idx < len(detections):
                detections.pop(idx)
        with open("detections.json", "w", encoding="utf-8") as f:
            json.dump(detections, f, indent=2, ensure_ascii=False)
        flash(f"Usunięto {len(indices)} wpisów.", "success")
    except Exception as e:
        flash("Błąd podczas usuwania wpisów!", "danger")
    return redirect(url_for("index"))
# === ONVIF Scan - dodaj na górze importy, jeśli nie masz:
from flask import jsonify
from wsdiscovery.discovery import ThreadedWSDiscovery as WSDiscovery
from onvif import ONVIFCamera

@app.route('/onvif_scan')
@login_required
def onvif_scan():
    if current_user.role != "admin":
        return jsonify({"status": "error", "msg": "Brak uprawnień"})

    login = request.args.get("login", "admin")
    password = request.args.get("password", "admin")

    from wsdiscovery import WSDiscovery
    from onvif import ONVIFCamera

    wsd = WSDiscovery()
    wsd.start()
    services = wsd.searchServices()
    cameras = []
    for service in services:
        xaddrs = service.getXAddrs()
        if xaddrs:
            url = xaddrs[0]
            ip = url.split('/')[2].split(':')[0]
            cameras.append({"ip": ip, "xaddr": url})
    wsd.stop()

    found = []
    for cam in cameras:
        try:
            mycam = ONVIFCamera(cam["ip"], 80, login, password)
            media_service = mycam.create_media_service()
            profiles = media_service.GetProfiles()
            profile = profiles[0]
            stream_setup = {
                'StreamSetup': {
                    'Stream': 'RTP-Unicast',
                    'Transport': {'Protocol': 'RTSP'}
                },
                'ProfileToken': profile.token
            }
            # Najważniejsze! Nie używamy **
            uri = media_service.GetStreamUri(stream_setup)
            found.append({
                "ip": cam["ip"],
                "rtsp": uri.Uri
            })
        except Exception as e:
            found.append({
                "ip": cam["ip"],
                "error": str(e)
            })
    return jsonify({"status": "ok", "cameras": found})



if __name__ == "__main__":
    t = threading.Thread(target=background_snapshot_worker, daemon=True)
    t.start()
    app.run(debug=True)
