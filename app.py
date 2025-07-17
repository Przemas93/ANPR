import os
import json
from flask import Flask, render_template, request, redirect, url_for, session, flash, Response, send_from_directory

# Ścieżki i stałe
CAMERAS_PATH = "cameras.json"
USERS_PATH = "users.json"
DETECTIONS_PATH = "detections.json"
WANTED_PATH = "wanted.json"
UPLOAD_FOLDER = "videos"
CAPTURES_FOLDER = "captures"
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'webm'}

app = Flask(__name__)
@app.template_filter('split')
def split_filter(s, sep='/'):
    return s.split(sep)
app.secret_key = "super_secret_key"
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Helpers
def allowed_video_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_VIDEO_EXTENSIONS

def load_json(path, default):
    if not os.path.isfile(path):
        return default
    with open(path, encoding="utf-8") as f:
        try:
            return json.load(f)
        except:
            return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def current_user():
    if "user" in session:
        return session["user"]
    return None

# ====== Serwowanie obrazów z "captures/" ======
@app.route('/captures/<filename>')
def get_capture(filename):
    return send_from_directory(CAPTURES_FOLDER, filename)

# ===== Login/out =====
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == "POST":
        users = load_json(USERS_PATH, {})
        username = request.form["username"]
        password = request.form["password"]
        user = users.get(username)
        if user and user["password"] == password:
            session["user"] = {"id": username, "role": user["role"]}
            return redirect(url_for("index"))
        else:
            return render_template("login.html", msg="Błędny login lub hasło")
    return render_template("login.html", msg=None)

@app.route('/logout')
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))

# ===== Panel główny =====
@app.route("/")
def index():
    if not current_user():
        return redirect(url_for("login"))
    detections = load_json(DETECTIONS_PATH, [])
    return render_template("index.html", detections=detections, user=current_user())

# ===== Kamery =====
@app.route('/admin_cameras', methods=['GET', 'POST'])
def admin_cameras():
    if not current_user() or current_user()["role"] != "admin":
        return redirect(url_for("login"))
    cameras = load_json(CAMERAS_PATH, [])
    msg = None

    # Dodanie kamery (RTSP)
    if request.method == 'POST' and 'add_camera' in request.form:
        cam_name = request.form['cam_name'].strip()
        cam_url = request.form['cam_url'].strip()
        if cam_name and cam_url:
            cameras.append({
                "name": cam_name,
                "rtsp_url": cam_url,
                "roi": {}
            })
            save_json(CAMERAS_PATH, cameras)
            msg = "Dodano kamerę!"
        else:
            msg = "Podaj nazwę i URL kamery!"

    # Dodanie pliku wideo jako kamery
    if request.method == 'POST' and 'add_video' in request.form:
        video_name = request.form['video_name'].strip()
        file = request.files.get('video_file')
        if not video_name or not file or file.filename == '':
            msg = "Podaj nazwę i wybierz plik!"
        elif not allowed_video_file(file.filename):
            msg = "Dozwolone pliki: MP4, AVI, MOV, MKV, WEBM."
        else:
            if not os.path.isdir(app.config['UPLOAD_FOLDER']):
                os.makedirs(app.config['UPLOAD_FOLDER'])
            filename = file.filename
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            i = 1
            while os.path.exists(save_path):
                filename = f"{os.path.splitext(file.filename)[0]}_{i}{os.path.splitext(file.filename)[1]}"
                save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                i += 1
            file.save(save_path)
            cameras.append({
                "name": video_name,
                "rtsp_url": f"/videos/{filename}",
                "roi": {}
            })
            save_json(CAMERAS_PATH, cameras)
            msg = "Dodano plik wideo jako kamerę!"

    # Edycja
    if request.method == 'POST' and 'edit_camera' in request.form:
        edit_name = request.form['edit_name'].strip()
        edit_url = request.form['edit_url'].strip()
        idx = next((i for i, cam in enumerate(cameras) if cam['name'] == request.form['edit_camera']), None)
        if idx is not None and edit_name and edit_url:
            cameras[idx]['name'] = edit_name
            cameras[idx]['rtsp_url'] = edit_url
            save_json(CAMERAS_PATH, cameras)
            msg = "Zapisano zmiany kamery!"

    # Usuwanie kamery/pliku
    if request.method == 'POST' and 'delete_camera' in request.form:
        name = request.form['delete_camera']
        cameras = [cam for cam in cameras if cam['name'] != name]
        save_json(CAMERAS_PATH, cameras)
        msg = "Usunięto kamerę!"

    cameras = load_json(CAMERAS_PATH, [])
    return render_template("admin_cameras.html", cameras=cameras, msg=msg, user=current_user())

@app.route('/videos/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ===== Panel użytkowników =====
@app.route('/users', methods=['GET', 'POST'])
def manage_users():
    if not current_user() or current_user()["role"] != "admin":
        return redirect(url_for("login"))
    users = load_json(USERS_PATH, {})
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
                save_json(USERS_PATH, users)
                msg = "Dodano użytkownika!"
        if 'change_pass' in request.form:
            username = request.form["change_pass"]
            password = request.form["new_pass2"].strip()
            if username in users:
                users[username]["password"] = password
                save_json(USERS_PATH, users)
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
                    save_json(USERS_PATH, users)
                    msg = f"Usunięto użytkownika {username}!"
            else:
                msg = "Nie znaleziono takiego użytkownika."
    return render_template("users.html", users=users, msg=msg, user=current_user())

# ===== Panel "wanted" =====
@app.route('/wanted', methods=["GET", "POST"])
def manage_wanted():
    if not current_user():
        return redirect(url_for("login"))
    msg = ""
    wanted = load_json(WANTED_PATH, [])
    if request.method == "POST":
        if "new_number" in request.form:
            num = request.form["new_number"].strip().upper()
            num = ''.join(c for c in num if c.isalnum())
            if num and num not in wanted:
                wanted.append(num)
                save_json(WANTED_PATH, wanted)
                msg = f"Dodano: {num}"
            else:
                msg = "Numer już istnieje lub jest pusty."
        if "delete_number" in request.form:
            num = request.form["delete_number"]
            if num in wanted:
                wanted.remove(num)
                save_json(WANTED_PATH, wanted)
                msg = f"Usunięto: {num}"
    return render_template("wanted.html", wanted=wanted, msg=msg, user=current_user())

# ===== Eksport CSV =====
@app.route('/export_csv')
def export_csv():
    if not current_user() or current_user()["role"] != "admin":
        return redirect(url_for("login"))
    detections = load_json(DETECTIONS_PATH, [])
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

# ===== Podgląd kamer na żywo =====
@app.route('/live')
def live():
    if not current_user():
        return redirect(url_for("login"))
    cameras = load_json(CAMERAS_PATH, [])
    return render_template('live.html', cameras=cameras, user=current_user())

# ===== Usuwanie wielu detekcji =====
@app.route("/delete_multiple", methods=["POST"])
def delete_multiple():
    if not current_user() or current_user()["role"] != "admin":
        return redirect(url_for("login"))
    uids = request.form.getlist("uids")
    detections = load_json(DETECTIONS_PATH, [])
    def uid_for(det):
        return f"{det['timestamp']}-{det['camera']}-{det['number']}"
    detections = [d for d in detections if uid_for(d) not in uids]
    save_json(DETECTIONS_PATH, detections)
    return redirect(url_for("index"))

if __name__ == '__main__':
    app.run(debug=True)
