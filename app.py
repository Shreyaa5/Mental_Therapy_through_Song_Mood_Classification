from flask import Flask, render_template, request, redirect, url_for, flash, session
import base64
import os
import numpy as np
import mysql.connector
import re
import razorpay
import razorpay.errors
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import timedelta, datetime
from werkzeug.utils import secure_filename
import cv2
import random
import string
from io import BytesIO
from flask import send_file
from PIL import Image, ImageDraw, ImageFont


# Initialize Flask app
app = Flask(__name__)
app.secret_key = 'secret_key'

CAPTURE_FOLDER = os.path.join('static', 'captured_images')
os.makedirs(CAPTURE_FOLDER, exist_ok=True)

user_answers = {}

# Database setup
sql_connection = mysql.connector.connect(
    host="115.187.17.57",
    user="debanjan",
    password="debanjan",
    database="flask_ml_db",
    port="3316"
)

RAZORPAY_KEY_ID = "rzp_test_iXumXBu7UMOLEf"
RAZORPAY_KEY_SECRET = "DbnMUMaSxdlLkTNCZ0ruZb7R"

razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

# Helper: generate simple captcha
def generate_simple_captcha():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))

# Landing page
@app.route('/')
def home():
    if 'loggedin' in session:
        return render_template('landing.html')
    else:
        session['captcha'] = generate_simple_captcha()
        return redirect(url_for('login'))

# Diagnosis page
@app.route('/diagnosis')
def diagnosis():
    if 'loggedin' in session:
        return render_template('diagnosis.html')
    else:
        return redirect(url_for('login'))

# Capture page
@app.route('/capture')
def capture():
    return render_template('capture.html')

# Save captured image
@app.route('/save_captured_image', methods=['POST'])
def save_captured_image():
    try:
        data = request.json['image']
        if ',' in data:
            _, data = data.split(',', 1)
        
        img_bytes = base64.b64decode(data)
        img_np_arr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(img_np_arr, cv2.IMREAD_COLOR)

        if img is not None:
            height, width, channels = img.shape
            print(f"[INFO] Captured image dimensions: {width}x{height}, Channels: {channels}")
        else:
            raise ValueError("Image decoding failed.")

        filename = f"capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        filepath = os.path.join(CAPTURE_FOLDER, filename)
        cv2.imwrite(filepath, img)

        session['captured_image'] = filepath
        return render_template('questions.html')

    except Exception as e:
        return {'status': 'error', 'message': str(e)}

# Mood-related questions
@app.route('/questions', methods=['GET', 'POST'])
def questions():
    if request.method == 'POST':
        image_path = session.get('captured_image')
        return render_template('questions.html', image_path=image_path)
    return redirect(url_for('capture'))

@app.route('/submit', methods=['POST'])
def submit():
    if request.method == 'POST':
        try:
            q1 = request.form.get("question1")
            q2 = request.form.get("question2")
            q3 = request.form.get("question3")
        except:
            flash("Something went wrong while processing the form.", "message")
            return render_template('questions.html')
    return render_template("Result2.html", q1=q1, q2=q2, q3=q3)

# ✅ Register with text captcha
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        firstName = request.form['firstName']
        lastName = request.form['lastName']
        phoneNumber = request.form['phoneNumber']
        emailId = request.form['emailId']
        entered_captcha = request.form.get('captcha')
        actual_captcha = session.get('captcha', '')

        # Validate captcha (case-sensitive)
        if not entered_captcha or entered_captcha != actual_captcha:
            flash('Invalid CAPTCHA. Please try again.', 'error')
            session['captcha'] = generate_simple_captcha()
            return render_template('register.html', captcha_text=session['captcha'])

        password_regex = r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,30}$'
        if not re.match(password_regex, password):
            flash("Password must be at least 8 characters, have uppercase, lowercase, digit, special character.", "error")
            session['captcha'] = generate_simple_captcha()
            return render_template('register.html', captcha_text=session['captcha'])
        
        if not re.match(r'^[6-9]\d{9}$', phoneNumber):
            flash("Invalid phone number.", "error")
            session['captcha'] = generate_simple_captcha()
            return render_template('register.html', captcha_text=session['captcha'])

        if emailId.startswith('_'):
            flash("Email cannot start with underscore.", "error")
            session['captcha'] = generate_simple_captcha()
            return render_template('register.html', captcha_text=session['captcha'])

        if re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', emailId):
            if sql_connection:
                cur = sql_connection.cursor()
                cur.execute('INSERT INTO users (username, password, firstName, lastName, phoneNumber, emailId) VALUES (%s, %s, %s, %s, %s, %s)', 
                            (username, password, firstName, lastName, phoneNumber, emailId))
                sql_connection.commit()
                flash('You have successfully registered!', 'success')
                return redirect(url_for('login'))
            else:
                print("SQL connection is null")
        else:
            flash("Invalid Email format.", "error")
            session['captcha'] = generate_simple_captcha()
            return render_template('register.html', captcha_text=session['captcha'])

    # If GET method (fresh page load)
    session['captcha'] = generate_simple_captcha()
    return render_template('register.html', captcha_text=session['captcha'])

# ✅ Login with captcha
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        entered_captcha = request.form.get('captcha')
        actual_captcha = session.get('captcha', '')

        # ✅ CASE-SENSITIVE captcha check
        if not entered_captcha or entered_captcha != actual_captcha:
            flash('Invalid CAPTCHA. Please try again.', 'error')
            session['captcha'] = generate_simple_captcha()
            return render_template('login.html', captcha_text=session['captcha'])

        # ✅ Username and Password check
        if sql_connection:
            cur = sql_connection.cursor()
            cur.execute('SELECT * FROM users WHERE username = %s AND password = %s', (username, password))
            user = cur.fetchone()
            if user:
                session['loggedin'] = True
                session['username'] = username
                session['user_id'] = user[0]
                session['firstname'] = user[3]
                session['membership'] = user[7]
                return redirect(url_for('home'))
            else:
                flash("Invalid login credentials", "error")
        else:
            flash("Server Error, Please Try Later", "error")

        session['captcha'] = generate_simple_captcha()
        return render_template('login.html', captcha_text=session['captcha'])

    # 👇 Handling GET request (when page loads)
    session['captcha'] = generate_simple_captcha()
    return render_template('login.html', captcha_text=session['captcha'])



@app.route('/captcha_image')
def captcha_image():
    captcha_text = session.get('captcha', 'ERROR')
    
    # Create an image (size: 150x60 pixels)
    image = Image.new('RGB', (150, 60), color=(255, 255, 255))
    draw = ImageDraw.Draw(image)

    # Use a truetype font (adjust path if necessary)
    try:
        font = ImageFont.truetype("arial.ttf", 36)  # Windows
    except:
        font = ImageFont.load_default()  # Fallback if font missing

    # Draw each letter in random color
    for i, letter in enumerate(captcha_text):
        x = 10 + i * 25
        y = 10
        color = (random.randint(0,150), random.randint(0,150), random.randint(0,150))  # Random soft colors
        draw.text((x, y), letter, font=font, fill=color)

    buffer = BytesIO()
    image.save(buffer, 'PNG')
    buffer.seek(0)

    return send_file(buffer, mimetype='image/png')

#refresh captcha
@app.route('/refresh_captcha')
def refresh_captcha():
    session['captcha'] = generate_simple_captcha()
    return '', 204  # No Content



#admin login page
def get_google_form_responses():
    scope = ['https://www.googleapis.com/auth/spreadsheets.readonly']
    creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
    client = gspread.authorize(creds)
    
    # Open the Google Sheet
    sheet = client.open_by_key('1wk1YHybbJMZl7iDLeukzgpEL2DLd2IDcWDwU8AjMH50').sheet1
    feedback_data = sheet.get_all_records()  # Get all form responses
    return feedback_data

@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    return render_template('admin_login.html')


@app.route('/admin', methods=['POST'])
def admin():
    admin_user = request.form['admin_username']
    admin_pass = request.form['admin_password']

    if(admin_user != "admin" or admin_pass != "admin12345"):
        return redirect(url_for('login'))
    session['admin_logged_in'] = True
    if 'admin_logged_in' not in session:
        return redirect(url_for('login'))
    
    # Fetch current users from the database
    cursor = sql_connection.cursor(dictionary=True)
    cursor.execute("SELECT users.id, users.firstname, users.lastname, users.emailId, users.phoneNumber, users.membership, responses.disorder FROM users JOIN responses ON users.id = responses.user_id")  # Update query as per your database schema
    users = cursor.fetchall()
    
    # Fetch feedback data from Google Forms
    feedback_data = get_google_form_responses()
    
    return render_template('admin.html', users=users, feedback_data=feedback_data)







# Logout
@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    flash("Logged out successfully!", "logout")
    return redirect(url_for('login'))

# (Other diagnosis, membership, admin routes same as your original file)

if __name__ == '__main__':
    app.run(debug=True)
