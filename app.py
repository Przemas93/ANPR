@@ -93,68 +93,73 @@ def admin_cameras():
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
-            cameras.append({
-                "name": video_name,
-                "rtsp_url": f"/videos/{filename}",
-                "roi": {}
-            })
-            save_json(CAMERAS_PATH, cameras)
-            msg = "Dodano plik wideo jako kamerę!"
+            cameras.append({
+                "name": video_name,
+                "rtsp_url": f"/videos/{filename}",
+                "file_path": os.path.join(app.config['UPLOAD_FOLDER'], filename),
+                "roi": {}
+            })
+            save_json(CAMERAS_PATH, cameras)
+            msg = "Dodano plik wideo jako kamerę!"
 
     # Edycja
     if request.method == 'POST' and 'edit_camera' in request.form:
         edit_name = request.form['edit_name'].strip()
         edit_url = request.form['edit_url'].strip()
         idx = next((i for i, cam in enumerate(cameras) if cam['name'] == request.form['edit_camera']), None)
-        if idx is not None and edit_name and edit_url:
-            cameras[idx]['name'] = edit_name
-            cameras[idx]['rtsp_url'] = edit_url
-            save_json(CAMERAS_PATH, cameras)
-            msg = "Zapisano zmiany kamery!"
+        if idx is not None and edit_name and edit_url:
+            cameras[idx]['name'] = edit_name
+            cameras[idx]['rtsp_url'] = edit_url
+            if edit_url.startswith('/videos/'):
+                cameras[idx]['file_path'] = os.path.join(app.config['UPLOAD_FOLDER'], edit_url.split('/')[-1])
+            elif 'file_path' in cameras[idx]:
+                cameras[idx].pop('file_path')
+            save_json(CAMERAS_PATH, cameras)
+            msg = "Zapisano zmiany kamery!"
 
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

