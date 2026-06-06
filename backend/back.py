from flask import Flask, render_template, request, redirect, session, Response, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os, json, random, string, sqlite3
from datetime import datetime

app = Flask(__name__)
# Get secret key from environment or default to development secret
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-prod')

DB_PATH = 'data/attendance.db'

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Enable foreign keys
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    os.makedirs('data', exist_ok=True)
    db_exists = os.path.exists(DB_PATH)
    
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    
    # Create tables
    conn.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL,
        profile TEXT DEFAULT 'https://via.placeholder.com/70'
    );
    """)
    
    conn.execute("""
    CREATE TABLE IF NOT EXISTS rooms (
        code TEXT PRIMARY KEY,
        subject TEXT NOT NULL,
        teacher_id TEXT NOT NULL,
        FOREIGN KEY (teacher_id) REFERENCES users(user_id)
    );
    """)
    
    conn.execute("""
    CREATE TABLE IF NOT EXISTS student_rooms (
        student_id TEXT NOT NULL,
        room_code TEXT NOT NULL,
        PRIMARY KEY (student_id, room_code),
        FOREIGN KEY (student_id) REFERENCES users(user_id),
        FOREIGN KEY (room_code) REFERENCES rooms(code)
    );
    """)
    
    conn.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room_code TEXT NOT NULL,
        user_id TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        location TEXT NOT NULL,
        student_id TEXT,
        daily_file TEXT,
        FOREIGN KEY (room_code) REFERENCES rooms(code),
        FOREIGN KEY (user_id) REFERENCES users(user_id)
    );
    """)
    
    conn.commit()
    
    # Check if database users table is empty to execute migration
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    user_count = cursor.fetchone()[0]
    
    if user_count == 0:
        print("Database is empty. Checking for legacy JSON files to migrate...")
        
        # Create dummy 'unknown' user to satisfy foreign key constraints
        try:
            conn.execute(
                "INSERT OR IGNORE INTO users (user_id, name, password, role) VALUES (?, ?, ?, ?)",
                ("unknown", "Unknown System Account", generate_password_hash("password123"), "teacher")
            )
            conn.commit()
        except Exception as e:
            print(f"Error inserting dummy user: {e}")
        
        # 1. Load users from data/users.json
        legacy_users = {}
        if os.path.exists('data/users.json'):
            try:
                with open('data/users.json', 'r') as f:
                    legacy_users = json.load(f)
            except Exception as e:
                print(f"Error reading data/users.json: {e}")
                
        # 2. Load users from students.json (root or data/)
        students_json_users = {}
        for path in ['students.json', 'data/students.json']:
            if os.path.exists(path):
                try:
                    with open(path, 'r') as f:
                        students_json_users = json.load(f)
                    break
                except Exception as e:
                    print(f"Error reading {path}: {e}")
                    
        # Merge legacy user details
        all_users = {}
        
        # Add root students.json users
        for u_id, u_info in students_json_users.items():
            role = u_info.get('role', 'student')
            password = u_info.get('password', '')
            if not password.startswith(('pbkdf2:', 'scrypt:', 'bcrypt:')):
                password = generate_password_hash(password)
            all_users[u_id] = {
                'name': u_info.get('name', 'Student'),
                'password': password,
                'role': role,
                'profile': u_info.get('profile', 'https://via.placeholder.com/70'),
                'classes': u_info.get('classes', [])
            }
            
        # Merge/update with data/users.json (which may be more current)
        for u_id, u_info in legacy_users.items():
            password = u_info.get('password', '')
            if not password.startswith(('pbkdf2:', 'scrypt:', 'bcrypt:')):
                password = generate_password_hash(password)
            
            # Keep created rooms list if exists
            created = u_info.get('created', [])
            classes = u_info.get('classes', [])
            
            # Combine classes lists
            existing_classes = all_users.get(u_id, {}).get('classes', [])
            combined_classes = list(set(classes + existing_classes))
            
            all_users[u_id] = {
                'name': u_info.get('name', 'User'),
                'password': password,
                'role': u_info.get('role', 'student'),
                'profile': u_info.get('profile', 'https://via.placeholder.com/70'),
                'classes': combined_classes,
                'created': created
            }
            
        # Insert all users
        for u_id, u_info in all_users.items():
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO users (user_id, name, password, role, profile) VALUES (?, ?, ?, ?, ?)",
                    (u_id, u_info['name'], u_info['password'], u_info['role'], u_info['profile'])
                )
            except Exception as e:
                print(f"Error inserting user {u_id}: {e}")
                
        # 3. Load rooms from data/rooms.json or rooms.json
        legacy_rooms = {}
        if os.path.exists('data/rooms.json'):
            try:
                with open('data/rooms.json', 'r') as f:
                    legacy_rooms = json.load(f)
            except Exception as e:
                print(f"Error reading data/rooms.json: {e}")
                
        root_rooms = {}
        if os.path.exists('rooms.json'):
            try:
                with open('rooms.json', 'r') as f:
                    root_rooms = json.load(f)
            except Exception as e:
                print(f"Error reading rooms.json: {e}")
                
        all_rooms = {}
        for r_code, r_info in root_rooms.items():
            all_rooms[r_code.upper()] = {
                'subject': r_info.get('subject', 'Classroom'),
                'teacher': r_info.get('created_by') or r_info.get('teacher', 'unknown')
            }
        for r_code, r_info in legacy_rooms.items():
            all_rooms[r_code.upper()] = {
                'subject': r_info.get('subject', 'Classroom'),
                'teacher': r_info.get('teacher', 'unknown')
            }
            
        # Insert rooms into DB
        for r_code, r_info in all_rooms.items():
            teacher_id = r_info['teacher']
            teacher_exists = conn.execute("SELECT 1 FROM users WHERE user_id = ?", (teacher_id,)).fetchone()
            if not teacher_exists and teacher_id != 'unknown':
                # Create placeholder user
                conn.execute(
                    "INSERT OR IGNORE INTO users (user_id, name, password, role) VALUES (?, ?, ?, ?)",
                    (teacher_id, teacher_id.split('@')[0], generate_password_hash("password123"), "teacher")
                )
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO rooms (code, subject, teacher_id) VALUES (?, ?, ?)",
                    (r_code, r_info['subject'], teacher_id)
                )
            except Exception as e:
                print(f"Error inserting room {r_code}: {e}")
                
        # Insert student classrooms relation
        for u_id, u_info in all_users.items():
            if u_info['role'] == 'student':
                for r_code in u_info.get('classes', []):
                    r_code_upper = r_code.upper()
                    room_exists = conn.execute("SELECT 1 FROM rooms WHERE code = ?", (r_code_upper,)).fetchone()
                    if room_exists:
                        try:
                            conn.execute(
                                "INSERT OR IGNORE INTO student_rooms (student_id, room_code) VALUES (?, ?)",
                                (u_id, r_code_upper)
                            )
                        except Exception as e:
                            print(f"Error inserting student relation {u_id} in {r_code_upper}: {e}")
                            
        # 4. Load attendance logs from data/attendance.json or attendance.json
        legacy_attendance = {}
        if os.path.exists('data/attendance.json'):
            try:
                with open('data/attendance.json', 'r') as f:
                    legacy_attendance = json.load(f)
            except Exception as e:
                print(f"Error reading data/attendance.json: {e}")
                
        root_attendance = {}
        if os.path.exists('attendance.json'):
            try:
                with open('attendance.json', 'r') as f:
                    root_attendance = json.load(f)
            except Exception as e:
                print(f"Error reading attendance.json: {e}")
                
        # Combine attendance
        all_attendance = {}
        for r_code, entries in root_attendance.items():
            if isinstance(entries, list):
                all_attendance[r_code.upper()] = all_attendance.get(r_code.upper(), []) + entries
        for r_code, entries in legacy_attendance.items():
            if isinstance(entries, list):
                all_attendance[r_code.upper()] = all_attendance.get(r_code.upper(), []) + entries
                
        for r_code, entries in all_attendance.items():
            # Check if room exists, otherwise create it
            room_exists = conn.execute("SELECT 1 FROM rooms WHERE code = ?", (r_code,)).fetchone()
            if not room_exists:
                conn.execute(
                    "INSERT OR IGNORE INTO rooms (code, subject, teacher_id) VALUES (?, ?, ?)",
                    (r_code, "Migrated Class " + r_code, "unknown")
                )
            for entry in entries:
                u_id = entry.get('user_id')
                if not u_id:
                    continue
                
                # Ensure user exists
                user_exists = conn.execute("SELECT 1 FROM users WHERE user_id = ?", (u_id,)).fetchone()
                if not user_exists:
                    conn.execute(
                        "INSERT OR IGNORE INTO users (user_id, name, password, role) VALUES (?, ?, ?, ?)",
                        (u_id, u_id.split('@')[0], generate_password_hash("password123"), "student")
                    )
                # Ensure student relation is present
                conn.execute(
                    "INSERT OR IGNORE INTO student_rooms (student_id, room_code) VALUES (?, ?)",
                    (u_id, r_code)
                )
                
                try:
                    conn.execute(
                        """
                        INSERT INTO attendance (room_code, user_id, timestamp, location, student_id, daily_file)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            r_code,
                            u_id,
                            entry.get('timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                            entry.get('location', ''),
                            entry.get('student_id') or entry.get('fingerprint') or u_id,
                            entry.get('daily_file')
                        )
                    )
                except Exception as e:
                    print(f"Error inserting attendance: {e}")
                    
        conn.commit()
        print("Data migration from JSON completed successfully!")
    conn.close()

def generate_captcha():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=3))

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory('uploads', filename)

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user_id = request.form['user_id']
        password = request.form['password']
        captcha_input = request.form['captcha_input']
        correct_captcha = session.get("captcha", "")

        if captcha_input.lower() != correct_captcha.lower():
            session['captcha'] = generate_captcha()
            return render_template("index.html", error="Incorrect CAPTCHA.", captcha=session['captcha'])

        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        conn.close()

        if user and check_password_hash(user['password'], password):
            session['user_id'] = user_id
            return redirect("/dashboard")
        else:
            session['captcha'] = generate_captcha()
            return render_template("index.html", error="Invalid credentials.", captcha=session['captcha'])

    session['captcha'] = generate_captcha()
    return render_template("index.html", captcha=session['captcha'])

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form['name']
        user_id = request.form['user_id']
        password = request.form['password']
        role = request.form['role']

        conn = get_db()
        user = conn.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if user:
            conn.close()
            return render_template("register.html", error="User already exists.")

        hashed_password = generate_password_hash(password)
        conn.execute("INSERT INTO users (user_id, name, password, role, profile) VALUES (?, ?, ?, ?, ?)",
                     (user_id, name, hashed_password, role, "https://via.placeholder.com/70"))
        conn.commit()
        conn.close()
        return redirect("/")
    return render_template("register.html")

@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    if 'user_id' not in session:
        return redirect('/')

    user_id = session['user_id']
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    
    if not user:
        session.clear()
        conn.close()
        return redirect('/')

    name = user['name']
    role = user['role']
    email = user_id
    profile = user['profile']

    selected_class_code = ''
    created_code = ''
    marks = {}
    attendance_percent = {}

    if request.method == 'POST':
        action = request.form.get("action")
        if action == "create_class" and role == 'teacher':
            subject = request.form['subject']
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            while conn.execute("SELECT 1 FROM rooms WHERE code = ?", (code,)).fetchone():
                code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            
            conn.execute("INSERT INTO rooms (code, subject, teacher_id) VALUES (?, ?, ?)", (code, subject, user_id))
            conn.commit()
            created_code = code
        elif action == "join_class" and role == 'student':
            room_code = request.form.get("room_code").upper()
            room = conn.execute("SELECT 1 FROM rooms WHERE code = ?", (room_code,)).fetchone()
            if room:
                # Add relationship if not already joined
                joined = conn.execute("SELECT 1 FROM student_rooms WHERE student_id = ? AND room_code = ?", (user_id, room_code)).fetchone()
                if not joined:
                    conn.execute("INSERT INTO student_rooms (student_id, room_code) VALUES (?, ?)", (user_id, room_code))
                    conn.commit()
                selected_class_code = room_code

    # Fetch classrooms list
    if role == 'teacher':
        classes_rows = conn.execute("SELECT code FROM rooms WHERE teacher_id = ?", (user_id,)).fetchall()
        classes = [r['code'] for r in classes_rows]
    else:
        classes_rows = conn.execute("SELECT room_code FROM student_rooms WHERE student_id = ?", (user_id,)).fetchall()
        classes = [r['room_code'] for r in classes_rows]

    # Populate rooms lookup for frontend: rooms[class_code].subject
    rooms = {}
    if classes:
        placeholders = ','.join('?' for _ in classes)
        rooms_rows = conn.execute(f"SELECT code, subject, teacher_id FROM rooms WHERE code IN ({placeholders})", classes).fetchall()
        for r in rooms_rows:
            rooms[r['code']] = {'subject': r['subject'], 'teacher': r['teacher_id']}

    # Compute attendance counts and grades/marks
    for c_code in classes:
        if role == 'student':
            total_logs = conn.execute("SELECT COUNT(*) FROM attendance WHERE room_code = ? AND user_id = ?", (c_code, user_id)).fetchone()[0]
            attendance_percent[c_code] = min(100, total_logs * 10) # 10% per attended class
            marks[c_code] = total_logs * 5 # 5 points per attendance log
        else:
            # Teacher stats: count total students registered and total logs
            registered = conn.execute("SELECT COUNT(*) FROM student_rooms WHERE room_code = ?", (c_code,)).fetchone()[0]
            attendance_percent[c_code] = registered  # We'll display student count
            
    conn.close()

    return render_template('dashboard.html',
                           name=name,
                           role=role,
                           email=email,
                           profile=profile,
                           selected_class_code=selected_class_code,
                           classes=classes,
                           rooms=rooms,
                           attendance_percent=attendance_percent,
                           marks=marks,
                           created_code=created_code)

@app.route('/mark_attendance', methods=['POST'])
def mark_attendance():
    user_id = session.get('user_id')
    if not user_id:
        return redirect('/')

    room_code = request.form['room_code'].upper()
    location = request.form['location']
    student_id = request.form['student_id']
    file = request.files['daily_work']

    filename = None
    if file and file.filename:
        filename = secure_filename(file.filename)
        os.makedirs('uploads', exist_ok=True)
        file.save(os.path.join('uploads', filename))

    conn = get_db()
    # Check if student is enrolled in the room
    is_joined = conn.execute("SELECT 1 FROM student_rooms WHERE student_id = ? AND room_code = ?", (user_id, room_code)).fetchone()
    if not is_joined:
        # Auto-enroll student if class code exists
        class_exists = conn.execute("SELECT 1 FROM rooms WHERE code = ?", (room_code,)).fetchone()
        if class_exists:
            conn.execute("INSERT INTO student_rooms (student_id, room_code) VALUES (?, ?)", (user_id, room_code))
            conn.commit()

    conn.execute("INSERT INTO attendance (room_code, user_id, timestamp, location, student_id, daily_file) VALUES (?, ?, ?, ?, ?, ?)",
                 (room_code, user_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), location, student_id, filename))
    conn.commit()
    conn.close()

    return redirect('/dashboard')

@app.route("/view_attendance/<room_code>")
def view_attendance(room_code):
    user_id = session.get("user_id")
    if not user_id:
        return redirect("/")

    conn = get_db()
    room = conn.execute("SELECT * FROM rooms WHERE code = ?", (room_code.upper(),)).fetchone()
    if not room or room['teacher_id'] != user_id:
        conn.close()
        return "Access denied"

    logs = conn.execute("SELECT * FROM attendance WHERE room_code = ? ORDER BY timestamp DESC", (room_code.upper(),)).fetchall()
    
    data = []
    for entry in logs:
        data.append({
            "user_id": entry['user_id'],
            "student_id": entry['student_id'] if entry['student_id'] else entry['user_id'],
            "timestamp": entry['timestamp'],
            "location": entry['location'],
            "file": entry['daily_file']
        })
    conn.close()

    return render_template("attendance.html", room_code=room_code.upper(), data=data)

@app.route("/export/<room_code>")
def export_attendance(room_code):
    user_id = session.get("user_id")
    if not user_id:
        return redirect("/")

    conn = get_db()
    # Ensure authorization
    room = conn.execute("SELECT * FROM rooms WHERE code = ?", (room_code.upper(),)).fetchone()
    if not room or room['teacher_id'] != user_id:
        conn.close()
        return "Access denied"

    logs = conn.execute("SELECT * FROM attendance WHERE room_code = ? ORDER BY timestamp DESC", (room_code.upper(),)).fetchall()
    conn.close()

    rows = [['user_id', 'student_id', 'timestamp', 'location']]
    for entry in logs:
        rows.append([
            entry['user_id'],
            entry['student_id'] if entry['student_id'] else 'N/A',
            entry['timestamp'],
            entry['location']
        ])

    output = '\n'.join([','.join(row) for row in rows])
    return Response(output, mimetype='text/csv',
                    headers={"Content-Disposition": f"attachment;filename={room_code}.csv"})

@app.route("/student_class/<room_code>")
def student_class(room_code):
    user_id = session.get("user_id")
    if not user_id:
        return redirect("/")

    room_code = room_code.upper()
    conn = get_db()
    joined = conn.execute("SELECT 1 FROM student_rooms WHERE student_id = ? AND room_code = ?", (user_id, room_code)).fetchone()
    if not joined:
        conn.close()
        return "Access Denied"

    user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    logs = conn.execute("SELECT * FROM attendance WHERE room_code = ? AND user_id = ? ORDER BY timestamp DESC", (room_code, user_id)).fetchall()
    
    student_logs = []
    for entry in logs:
        student_logs.append({
            'timestamp': entry['timestamp'],
            'location': entry['location'],
            'daily_file': entry['daily_file']
        })
    conn.close()

    return render_template("student_class.html",
                           room_code=room_code,
                           student=user,
                           logs=student_logs,
                           student_id=user_id,
                           total=len(student_logs))

@app.route("/about")
def about():
    # Detect if user is logged in to change navigation links
    logged_in = 'user_id' in session
    return render_template("about.html", logged_in=logged_in)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
