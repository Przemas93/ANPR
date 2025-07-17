--import os
--import cv2
--import time
--import json
--from datetime import datetime
--from ultralytics import YOLO
--import easyocr
--from database import add_plate
-+import os
-+import cv2
-+import time
-+import json
-+from datetime import datetime
-+from ultralytics import YOLO
-+import easyocr
-+import pytesseract
-+from database import add_plate
- 
- CAMERAS_PATH = "cameras.json"
- SNAPSHOTS_DIR = "static/snapshots"
- CAPTURES_DIR = "static/captures"
- MODEL_PATH = "license_plate_detector.pt"
- 
- def load_cameras():
-     if not os.path.isfile(CAMERAS_PATH):
-         return []
-     with open(CAMERAS_PATH, encoding="utf-8") as f:
-         return json.load(f)
- 
--def ensure_dirs():
--    os.makedirs(SNAPSHOTS_DIR, exist_ok=True)
--    os.makedirs(CAPTURES_DIR, exist_ok=True)
-+def ensure_dirs():
-+    os.makedirs(SNAPSHOTS_DIR, exist_ok=True)
-+    os.makedirs(CAPTURES_DIR, exist_ok=True)
-+
-+def preprocess_plate(img):
-+    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
-+    # reduce noise while keeping edges
-+    gray = cv2.bilateralFilter(gray, 11, 17, 17)
-+    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
-+    return thresh
- 
- def ocr_image_easyocr(img):
-     reader = easyocr.Reader(['pl', 'en'], gpu=False)
-     # Konwersja do RGB dla easyocr
-     img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
-     result = reader.readtext(img_rgb, detail=0, allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')
-     if result:
-         return result[0]
-     return ""
- 
- def run_detection_on_camera(cam):
-     cap = cv2.VideoCapture(cam["rtsp_url"])
-     if not cap.isOpened():
-         print(f"[!] Nie można otworzyć kamery: {cam['name']} ({cam['rtsp_url']})")
-         return
- 
-     print(f"[*] Start detekcji dla kamery: {cam['name']}")
-     model = YOLO(MODEL_PATH)
-     reader = easyocr.Reader(['pl', 'en'], gpu=False)
- 
-     while True:
-         ret, frame = cap.read()
-         if not ret:
-             print(f"[!] Utracono obraz z kamery: {cam['name']}")
-             time.sleep(2)
-             continue
- 
-         results = model(frame)
--        for result in results:
--            for box in result.boxes:
--                x1, y1, x2, y2 = [int(coord) for coord in box.xyxy[0].tolist()]
--                plate_img = frame[y1:y2, x1:x2]
--                # OCR przez easyocr
--                img_rgb = cv2.cvtColor(plate_img, cv2.COLOR_BGR2RGB)
--                ocr_result = reader.readtext(img_rgb, detail=0, allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')
--                number = ocr_result[0] if ocr_result else ""
-+        for result in results:
-+            for box in result.boxes:
-+                x1, y1, x2, y2 = [int(coord) for coord in box.xyxy[0].tolist()]
-+                plate_img = frame[y1:y2, x1:x2]
-+
-+                proc = preprocess_plate(plate_img)
-+                img_rgb = cv2.cvtColor(proc, cv2.COLOR_GRAY2RGB)
-+                ocr_result = reader.readtext(img_rgb, detail=0,
-+                                           allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')
-+                number = ocr_result[0] if ocr_result else ""
-+                if not number:
-+                    # fallback to pytesseract when easyocr fails
-+                    tess = pytesseract.image_to_string(proc, config='--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')
-+                    number = tess.strip()
- 
-                 # Zapis obrazów
-                 timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
-                 filename = f"{cam['name']}_{timestamp}_{number.replace(' ','_')}"
-                 img_path = f"snapshots/{filename}.jpg"
-                 full_img_path = f"captures/{cam['name']}_{timestamp}.jpg"
-                 cv2.imwrite(os.path.join("static", img_path), plate_img)
-                 cv2.imwrite(os.path.join("static", full_img_path), frame)
- 
-                 # Zapisz detekcję do bazy (database.py)
-                 add_plate(
-                     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
-                     cam["name"],
-                     number,
-                     img_path,
-                     full_img_path
-                 )
- 
-                 print(f"[+] Detekcja: {cam['name']} | {number}")
- 
-         time.sleep(1)  # Dla bezpieczeństwa
- 
-     cap.release()
- 
- def main():
+import os
+import cv2
+import time
+import json
+from datetime import datetime
+from ultralytics import YOLO
+import easyocr
+import pytesseract
+from database import add_plate
+
+CAMERAS_PATH = "cameras.json"
+SNAPSHOTS_DIR = "static/snapshots"
+CAPTURES_DIR = "static/captures"
+MODEL_PATH = "license_plate_detector.pt"
+
+
+def load_cameras():
+    if not os.path.isfile(CAMERAS_PATH):
+        return []
+    with open(CAMERAS_PATH, encoding="utf-8") as f:
+        return json.load(f)
+
+
+def ensure_dirs():
+    os.makedirs(SNAPSHOTS_DIR, exist_ok=True)
+    os.makedirs(CAPTURES_DIR, exist_ok=True)
+
+
+def preprocess_plate(img):
+    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
+    gray = cv2.bilateralFilter(gray, 11, 17, 17)
+    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
+    return thresh
+
+
+def run_detection_on_camera(cam):
+    src = cam.get("file_path", cam["rtsp_url"])
+    if cam["rtsp_url"].startswith("/videos/"):
+        src = os.path.join(".", cam["rtsp_url"].lstrip("/"))
+    cap = cv2.VideoCapture(src)
+    if not cap.isOpened():
+        print(f"[!] Nie można otworzyć kamery: {cam['name']} ({src})")
+        return
+
+    print(f"[*] Start detekcji dla kamery: {cam['name']}")
+    model = YOLO(MODEL_PATH)
+    reader = easyocr.Reader(['pl', 'en'], gpu=False)
+
+    while True:
+        ret, frame = cap.read()
+        if not ret:
+            print(f"[!] Utracono obraz z kamery: {cam['name']}")
+            time.sleep(2)
+            continue
+
+        results = model(frame)
+        for result in results:
+            for box in result.boxes:
+                x1, y1, x2, y2 = [int(c) for c in box.xyxy[0].tolist()]
+                plate_img = frame[y1:y2, x1:x2]
+
+                proc = preprocess_plate(plate_img)
+                img_rgb = cv2.cvtColor(proc, cv2.COLOR_GRAY2RGB)
+                ocr_res = reader.readtext(
+                    img_rgb,
+                    detail=0,
+                    allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
+                )
+                number = ocr_res[0] if ocr_res else ""
+                if not number:
+                    tess = pytesseract.image_to_string(
+                        proc,
+                        config='--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
+                    )
+                    number = tess.strip()
+
+                timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
+                filename = f"{cam['name']}_{timestamp}_{number.replace(' ', '_')}"
+                img_path = f"snapshots/{filename}.jpg"
+                full_img_path = f"captures/{cam['name']}_{timestamp}.jpg"
+                cv2.imwrite(os.path.join("static", img_path), plate_img)
+                cv2.imwrite(os.path.join("static", full_img_path), frame)
+
+                add_plate(
+                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
+                    cam["name"],
+                    number,
+                    img_path,
+                    full_img_path
+                )
+                print(f"[+] Detekcja: {cam['name']} | {number}")
+
+        time.sleep(1)
+
+    cap.release()
+
+
+def main():
+    ensure_dirs()
+    cameras = load_cameras()
+    if not cameras:
+        print("[!] Brak skonfigurowanych kamer w cameras.json!")
+        return
+    for cam in cameras:
+        run_detection_on_camera(cam)
+
+
+if __name__ == "__main__":
+    main()
