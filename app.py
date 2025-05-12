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
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from googleapiclient.discovery import build
from google.oauth2 import service_account
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from bson.objectid import ObjectId
from flask import Flask, jsonify
from bson import ObjectId
from bson.errors import InvalidId
from flask_pymongo import PyMongo
from flask_pymongo import PyMongo
from flask_pymongo import PyMongo
import tensorflow as tf
from tensorflow import keras
from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline
from flask_wtf import FlaskForm
from wtforms import RadioField, IntegerField
from wtforms.validators import DataRequired, NumberRange



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


# MongoDB connection (added from ChronoTunes)
key = "6Kto5LxwDqchjAc0"
uri = "mongodb+srv://abhirajbanerjee02:6Kto5LxwDqchjAc0@cluster-chronotunes.pkxxz.mongodb.net/?retryWrites=true&w=majority&appName=Cluster-ChronoTunes"
mongoClient = MongoClient(uri, server_api=ServerApi('1'))
collection = mongoClient['users']['chronoTunes']
song_db = mongoClient['songs']
playlist_collection = mongoClient['mood_detection_playlist_data']['user_playlists']


# Spotify Credentials
sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
    client_id="9e1b5aca31eb4ec78abccccb05846c40",
    client_secret="c502b9cb165c476db22e415dbce3b886"
))


#profile page
@app.route('/profile')
def profile():
    if 'user_id' not in session:
        flash('Please log in to view your profile.', 'error')
        return redirect(url_for('login'))

    try:
        cur = sql_connection.cursor()
        cur.execute('SELECT * FROM users WHERE id = %s', (session['user_id'],))
        user = cur.fetchone()
        if not user:
            flash('No user data found.', 'error')
            return redirect(url_for('login'))
    except Exception as e:
        flash('Error loading profile.', 'error')
        return redirect(url_for('login'))
    if request.method == 'POST':
        current_password = request.form['currentPassword']
        new_password = request.form['newPassword']
        confirm_password = request.form['confirmPassword']

        # Password verification
        if new_password != confirm_password:
            flash("New passwords do not match!", "error")
        elif current_password != user[4]:  # Assuming index 4 is the password column
            flash("Current password is incorrect!", "error")
        else:
            try:
                cur.execute('UPDATE users SET password = %s WHERE id = %s', (new_password, session['user_id']))
                sql_connection.commit()
                flash("Password updated successfully!", "success")
                return redirect(url_for('profile'))
            except Exception as e:
                flash("Error updating password.", "error")

    return render_template('profile.html', user=user)


# Google Drive API for audio streaming
def create_drive_service():
    SERVICE_ACCOUNT_FILE = 'credentials.json'
    SCOPES = ['https://www.googleapis.com/auth/drive']
    creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

service = create_drive_service()

# Folder IDs for genres
def get_folder_id(genre):
    mapping = {
        'bengali': '1gifXb2IjlJoIYs9mCZW1-0XITQ6qr1J4',
        'classical': '11gCZK8C4lWcAX77tCuYRbi5jC8cbMhnW',
        'hindi-retro': '1VAV9M8cYo9ZMAkBoMZrJpe4Kupx8Jst3',
        'hindi-modern': '1Ai-dpQ6s2_E_ShWifMHLoOvypZoBzymR'
    }
    return mapping.get(genre.lower(), '')

class PlaylistForm(FlaskForm):
    genre = RadioField('Select your preferred genre:', choices=[
        ('Hindi-Retro', 'Hindi-Retro'),
        ('Hindi-Modern', 'Hindi-Modern'),
        ('Classical', 'Classical'),
        ('Bengali', 'Bengali')
    ], validators=[DataRequired()])
    
    playlist_length = IntegerField('Length of Playlist (1-30 songs):', 
                                   validators=[DataRequired(), NumberRange(1, 30)])


#playlist generation
@app.route('/generate_playlist', methods=['GET', 'POST'])
def generate_playlist():
    if 'loggedin' not in session:
        flash('Please log in to continue.', 'error')
        return redirect(url_for('login'))

    if request.method == 'POST':
        genre = request.form.get('genre')
        playlist_length = request.form.get('playlist_length')
        mood = request.form.get('mood')
        playlist_name = request.form.get('playlist_name')
    else:
        genre = request.args.get('genre')
        playlist_length = request.args.get('playlist_length')
        mood = request.args.get('mood')
        playlist_name = request.args.get('playlist_name')

    if not all([genre, playlist_length, mood, playlist_name]):
        flash("Missing input values. Please fill all fields.", "error")
        return redirect(url_for('home'))

    try:
        playlist_length = int(playlist_length)
    except ValueError:
        flash("Invalid playlist length.", "error")
        return redirect(url_for('home'))

    # Step 1: Fetch songs from MongoDB
    #Mood-specific Thaat mapping
    mood_thaats = {
        'happy': ['Bilaval', 'Kalyan', 'Khamaj', 'Kafi', 'Asavari', 'Bhairav', 'Marva', 'Poorvi', 'Todi', 'Bhairavi'],
        'sad': ['Bilaval', 'Kafi', 'Bhairav', 'Todi'],
        'neutral': ['Bilaval', 'Kafi', 'Bhairav', 'Todi', 'Khamaj', 'Poorvi'],
        'angry': ['Bilaval' , 'Kalyan' , 'Khambaj' , ' Kafi', 'Asavari']
    }

    selected_thaats = mood_thaats.get(mood.lower(), [])
    print(f"[DEBUG] MOOD_THAAT - {mood.upper()} → {selected_thaats}")
    if not selected_thaats:
        flash("Invalid mood or no Thaat mapping found.", "error")
        return render_template('playlist.html', playlist_name=playlist_name, audio_files=[])

    songs = song_db[genre.lower()].find({"thaat": {"$in": selected_thaats}}, {'filename': 1})
    filenames = [song['filename'] for song in songs if 'filename' in song]

    if not filenames:
        flash("No songs found for the selected mood and genre.", "error")
        return render_template('playlist.html', playlist_name=playlist_name, audio_files=[], is_premium=False)

    selected = random.sample(filenames, min(playlist_length, len(filenames)))

    # Step 2: Fetch corresponding Spotify links
    folder_id = get_folder_id(genre)
    query = f"'{folder_id}' in parents and mimeType='audio/mpeg'"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    items = results.get('files', [])

    audio_files = []
    for file in items:
        song_name = file['name'].replace('.mp3', '').replace('_', ' ')
        if file['name'].replace('.mp3', '.pickle') in selected:
            try:
                result = sp.search(q=song_name, type='track', limit=1)
                if result['tracks']['items']:
                    track_url = result['tracks']['items'][0]['external_urls']['spotify']
                    audio_files.append({'name': song_name, 'url': track_url})
            except Exception as e:
                print(f"[Spotify ERROR] {song_name}: {e}")

    user_id = session.get('user_id')
    username = session.get('username')
    is_premium = session.get('membership') == 'active'

    # Check for duplicate playlist name
    existing = playlist_collection.find_one({'user_id': user_id, 'playlist_name': playlist_name})
    if existing:
        return '''
            <script>
                alert("You already have a playlist with this name. Please choose another name.");
                window.history.back();
            </script>
        '''

    # Free users can only create 3 playlists
    playlist_count = playlist_collection.count_documents({'user_id': user_id})
    if not is_premium and playlist_count >= 3:
        flash("Free users can only create 3 playlists. Upgrade to Premium to create more.", "error")
        return redirect(url_for('membership'))

    # Save playlist
    if user_id and playlist_name and audio_files:
        playlist_doc = {
            'user_id': user_id,
            'username': username,
            'playlist_name': playlist_name,
            'mood': mood,
            'genre': genre,
            'created_at': datetime.utcnow(),
            'songs': audio_files,
            'membership': 'Premium' if is_premium else 'Free'
        }

        try:
            result = playlist_collection.insert_one(playlist_doc)
            print(f"[MongoDB] Playlist saved with ID: {result.inserted_id}")
        except Exception as e:
            print(f"[MongoDB ERROR] Could not insert playlist: {e}")
            flash("An error occurred while saving your playlist.", "error")
            return redirect(url_for('home'))

    # Return with flag to indicate membership
    return render_template(
        'playlist.html',
        playlist_name=playlist_name,
        audio_files=audio_files,
        is_premium=is_premium
    )



#users can see their previous playlists
@app.route('/my_playlists')
def my_playlists():
    if 'loggedin' not in session:
        flash('Please log in to view your playlists.', 'error')
        return redirect(url_for('login'))

    try:
        playlist_db = mongoClient['mood_detection_playlist_data']['user_playlists']
        user_id = session.get('user_id')
        playlists = list(playlist_db.find({"user_id": user_id}))
        return render_template('my_playlists.html', playlists=playlists)
    except Exception as e:
        flash(f"Error fetching playlists: {e}", 'error')
        return render_template('my_playlists.html', playlists=[])




#On clicking a particular playlist name,user can view the entire playlist
@app.route('/playlist/<playlist_id>')
def view_playlist(playlist_id):
    if 'loggedin' not in session:
        flash('Please log in to view playlists.', 'error')
        return redirect(url_for('login'))

    try:
        playlist = playlist_collection.find_one({"_id": ObjectId(playlist_id)})
        if not playlist:
            flash("Playlist not found.", "error")
            return redirect(url_for('my_playlists'))
        return render_template('view_playlist.html', playlist=playlist)
    except Exception as e:
        flash(f"Error loading playlist: {e}", 'error')
        return redirect(url_for('my_playlists'))



@app.route('/test_insert')
def test_insert():
    doc = {
        'user_id': 123,
        'playlist_name': 'Test Playlist',
        'mood': 'happy',
        'genre': 'classical',
        'created_at': datetime.utcnow(),
        'songs': [{'name': 'Test Song', 'url': 'http://example.com'}]
    }
    result = playlist_collection.insert_one(doc)
    return f"Inserted test playlist with ID: {result.inserted_id}"


def getMoodUsingML(text_ans, filePath):
    filePath = str(filePath)
    
    try:
        model_NLP = AutoModelForSequenceClassification.from_pretrained("NLPModel")
        tokenizer = AutoTokenizer.from_pretrained("NLP_tokenizer")
        nlp_pipeline = pipeline("text-classification", model=model_NLP, tokenizer=tokenizer, return_all_scores=True)
        nlp_result = nlp_pipeline(text_ans)
        print(nlp_result)
        frame = cv2.imread(filePath.replace("\\", "/" ))

        if frame is None:
            print("Frame is returning None")
            return "Frame returning None"
        else:
            print("Frame Found")
        
        faceCascacde = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        grayImg = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = faceCascacde.detectMultiScale(grayImg, 1.1, 4)
        print("Number of faces detected = ", len(faces))
        if(len(faces) == 0 or len(faces) == None):
            return "No Face"
        
        
        for (x, y, w, h) in faces:
            face_roi = frame[y:y+h, x:x+w]
            print("Trying FACE_ROI")
            break
        
        final_image = cv2.resize(face_roi, (224, 224))
        final_image = np.expand_dims(final_image, axis=0)
        final_image = final_image/255.0
        
        imgModel = tf.keras.models.load_model('imageModel3.h5')
        image_result = imgModel.predict(final_image)
        
        print(image_result)
        # Ensure that we are processing the outputs correctly
        final_probability_list = [0, 0, 0, 0]
        
        for i in range(len(nlp_result[0])):
            final_probability_list[i] = (0.75 * nlp_result[0][i]['score']) + (0.25 * image_result[0][i])
        print(final_probability_list)
        
        dominant_index = np.argmax(final_probability_list)
        
        if dominant_index == 0:
            return "Angry"
        elif dominant_index == 1:
            return "Happy"
        elif dominant_index == 2:
            return "Neutral"
        elif dominant_index == 3:
            return "Sad"
    except:
        flash("Something went wrong, try again", category="error")
        render_template("capture.html")


# Processing of mood
#FILE PATH NEEDS TO BE EDITED GET /static/static\\captured_images\\capture_20250504_205610.jpg HTTP/1.1
@app.route('/process_mood', methods=['POST'])
def process_mood():
    if request.method == 'POST':
        try:
            q1 = request.form.get("question1")
            # q2 = request.form.get("question2")
            # q3 = request.form.get("question3")

            print(q1)
            #score = q1 + q2 + q3
            #session['score'] = score
            image_path = str(session.get('captured_image'))
            final_img_path = image_path.replace("\\", "/")
            print(final_img_path)
            # Only considering Q1 for NLP evaluation
            mood = getMoodUsingML(q1, final_img_path)  # Returns a string
            if(mood == "No Face"):
                flash("No Face Found", category="error")
                return render_template("capture.html")
            if(mood == "No Face"):
                flash("No Face Found", category="error")
                return render_template("capture.html")
            print(f"Detected mood: {mood}")  # This line prints the mood to the console
            session['mood_playlist'] = mood

            # Store the mood and question responses for display in result template
            return render_template("Result2.html", mood=mood, q1=q1)

        except Exception as e:
            flash(f"Error processing form: {str(e)}", "message")
            return render_template('questions.html', image_path=final_img_path)


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


#Questionnaire1
@app.route('/startDiagnosis', methods=['POST'])
def startDiagnosis():
    if 'loggedin' in session:
        try:
            return(render_template('Questionnaire1.html',user=session['firstname']))
        except:
            flash("Some Error Occured","message")
            return redirect(url_for('login'))

    else:
        flash("Please login before diagnosis.","message")
        return(render_template('landing.html'))
    


#Questionnaire2  
@app.route('/questionnaire2', methods=['POST'])
def questionnaire2():
    try:
        answer1=[
                request.form['question1'],
                request.form['question2'],
                request.form['question3'],
                request.form['question4'],
                request.form['question5'],
                request.form['question6'],
                request.form['question7']]
    except:
        flash("Please fill every field","message")
        return(render_template('Questionnaire1.html',user=session['firstname']))
    session['answer']= answer1
    return(render_template('Questionnaire2.html',user=session['firstname']))

@app.route('/predict', methods=['POST'])
def predict():
    if request.method == 'POST':
        # Get user form input (Yes/No answers)
        try:
            answers2 = [
                request.form['question8'],
                request.form['question9'],
                request.form['question10'],
                request.form['question11'],
                request.form['question12'],
                request.form['question13'],
                request.form['question14']]
        except:
            flash("Please fill every field","message")
            return(render_template('Questionnaire2.html',user=session['username']))

        answers=[]
        answers.extend(session['answer']) 
        answers.extend(answers2)

        # Convert answers to numerical values (e.g., Yes = 1, No = 0)
        answers = [1 if answer == 'Yes' else 0 for answer in answers]

       
        user = {
            'is_member': True if session['membership'] == "active" else False
        }

        # Logic to calculate disorder scores

        disorder_scores = {
            "Anxiety Disorder": answers[0] + answers[9] + answers[13],
            "Depression": answers[1] + answers[8] + answers[12] ,
            "Bipolar Disorder": answers[2] + answers[10],
            "Obsessive Compulsive Disorder": answers[3] + answers[11],
            "Post-Traumatic Stress Disorder": answers[4] + answers[5],
            "Schizophrenia":  answers[6] + answers[12]
        }

        # Determine the most likely disorder
        if disorder_scores[max(disorder_scores, key=disorder_scores.get)] !=0:
            most_likely_disorder = max(disorder_scores, key=disorder_scores.get)  
        else:
            most_likely_disorder = "Healthy"

        cur = sql_connection.cursor()
        cur.execute('SELECT * FROM responses WHERE user_id = %s', (session['user_id'],))
        if(cur.fetchone()):
            cur.execute('UPDATE responses SET disorder = %s WHERE user_id = %s',(most_likely_disorder,session['user_id']))
            sql_connection.commit()
        else:
            cur.execute('INSERT INTO responses (user_id, disorder) VALUES (%s, %s)', (session['user_id'],most_likely_disorder))
            sql_connection.commit()

        if(most_likely_disorder == "Healthy"):
            return render_template('healthy.html',name=session['firstname'])

        

        if(most_likely_disorder == "Anxiety Disorder"):
            raag = "Bilawal"
            TOD = "morning, during sunrise"

            song1 = "Mayur Pangkhi Louka Amar"
            link1 = "https://open.spotify.com/track/1QUefoT4WXG8tNR92ilCgE"

            song2 = "Manush Hoye"
            link2 = "https://open.spotify.com/track/1t715y57YZCksMYtNdtbIJ"

            song3 = "Bhatiganger Majhi Ami"
            link3 = "https://open.spotify.com/track/1APcdHREzjUAaqnJnlAIMG"

            desc = "Bilawal is a Shuddha raaga (all natural notes) that creates a cheerful, tranquil, and harmonious mood. Its simplicity makes it ideal for grounding the mind and alleviating anxious thoughts."

            firstAction = "Exercise: Regular physical activity releases endorphins and reduces stress hormones like cortisol. Activities like brisk walking, jogging, yoga, or swimming are especially beneficial."
            secondAction = "Deep Breathing Exercises: Practice diaphragmatic or box breathing to reduce anxiety symptoms immediately. For example, inhale for 4 seconds, hold for 4 seconds, exhale for 4 seconds, and repeat."
            thirdAction = "Progressive Muscle Relaxation (PMR): Tensing and then relaxing muscle groups can help reduce physical tension caused by anxiety."
            forthAction = "Watch Comedy: Laughter reduces stress hormones and boosts mood."
        elif(most_likely_disorder == "Depression"):
            raag = "Kafi"
            TOD = "evening"

            song1 = "Chikan Goalini"
            link1 = "https://open.spotify.com/track/6PKlzTQ4eA2N3Hrm8wPWIy"

            song2 = "Gyaner Gyanda"
            link2 = "https://open.spotify.com/track/1gj3lFcZW8vZkg9gW5c8Pl"

            song3 = "Vadu Amar Garobini"
            link3 = "https://open.spotify.com/track/4SSfCXsyYHGunfSUryzE1U"

            desc = "Raaga Kafi is soft and soothing, it creates a relaxed and pleasant atmosphere. It helps ease emotional pain, creating a sense of comfort and calm."

            firstAction = "Daily Exercise: Even light physical activity like walking, stretching, or yoga can release endorphins and improve mood. Aim for 20-30 minutes most days."
            secondAction = "Spending Time Outdoors: Activities like gardening or hiking expose you to sunlight, increasing Vitamin D and improving mood."
            thirdAction = "Gratitude Journaling: List 3 things you are grateful for each day to shift focus toward the positive aspects of life."
            forthAction = "Create a Sleep Routine: Go to bed and wake up at the same time daily, aiming for 7-9 hours of quality sleep."
        elif(most_likely_disorder == "Bipolar Disorder"):
            raag = "Poorvi"
            TOD = "twilight, i.e around dusk"

            song1 = "O Sundar"
            link1 = "https://open.spotify.com/track/3VdsY4zZweY9ijNOPIab09"

            song2 = "Khat Palanke"
            link2 = "https://open.spotify.com/track/6SB6rcD1j0F5mDdII2u2Y2"

            song3 = "Emon Manob Somaj"
            link3 = "https://open.spotify.com/track/1XDM4SFKl1dgK3vy6u2sb5"

            desc = "Poorvi is a Sandhi Prakash Raaga (suitable for twilight) and has a mystical quality that induces balance and emotional tranquility. It uses a mix of komal (flat) and shuddha (natural) notes, creating a meditative and grounding effect."

            firstAction = "Daily Schedule: Maintain a consistent routine for sleeping, eating, and activities to reduce mood swings triggered by irregularities."
            secondAction = "Positive Affirmations: Practice self-compassion with affirmations like, “I am in control of my thoughts,” or “This phase will pass.”"
            thirdAction = "Grounding with Nature: Touching the earth (e.g., gardening, sitting on grass) can help stabilize energy and connect to the present moment."
            forthAction = "Writing: Journaling thoughts and feelings fosters self-awareness and provides emotional release."
        elif(most_likely_disorder == "Obsessive Compulsive Disorder"):
            raag = "Kafi"
            TOD = "evening"

            song1 = "Boli O Khokar Ma"
            link1 = "https://open.spotify.com/track/13tdWCj9rxHx7UqiNXL7Mt"

            song2 = "Hari Din To Gelo"
            link2 = "https://open.spotify.com/track/1ijtcd8LuYfI3fVLvtqNcT"

            song3 = "Bhatiyal Ganger Naiya"
            link3 = "https://open.spotify.com/track/5MPm6CXwqH9x3eBS0xPJkr"

            desc = "Kafi is mellow and thus promotes relaxation and reduces tension. It eases anxiety and encourages mindfulness, reducing the compulsion to perform repetitive behaviors."

            firstAction = "Puzzles or Board Games: Activities that engage problem-solving can distract the mind from intrusive thoughts."
            secondAction = "Hobbies: Engage in hobbies you enjoy, such as knitting, photography, or woodworking, to occupy your hands and mind."
            thirdAction = "Limit Overchecking: Create boundaries for actions like re-reading, re-checking, or seeking excessive reassurance."
            forthAction = "Digital Detox: Avoid spending too much time online researching fears or compulsions, as this can fuel anxiety."
        elif(most_likely_disorder == "Post-Traumatic Stress Disorder"):
            raag = "Todi"
            TOD = "morning, just after sunrise"

            song1 = "Hatey Hari Ebar Ami"
            link1 = "https://open.spotify.com/track/3DMR2iKoWQ0SkIxlJ3Yfr8"

            song2 = "Bhangor Bhola Shib Tomar"
            link2 = "https://open.spotify.com/track/3msn6YUhZTpiLDiY0CCw5w"

            song3 = "Ghum Venge Besh Moja Hoeche"
            link3 = "https://open.spotify.com/track/4jwBPXsdUK9bI3aS6WodWA"

            desc = "Todi is a profound and introspective raaga that uses komal (flat) notes and a slow progression, creating a melancholic yet healing atmosphere. It encourages emotional release and processing of suppressed trauma as well as provides a grounding effect, counteracting feelings of fear and hypervigilance."

            firstAction = "5-4-3-2-1 Method: Identify five things you can see, four you can touch, three you can hear, two you can smell, and one you can taste to stay grounded in the present."
            secondAction = "Deep Breathing: Practice slow, deep breaths to reduce anxiety. For example, inhale for 4 counts, hold for 4, exhale for 4, and hold for 4 (box breathing)."
            thirdAction = "Morning Rituals: Start the day with a calming activity, such as journaling or stretching, to set a positive tone."
            forthAction = "Nighttime Wind-Down: Create a bedtime routine involving calming activities, such as reading or drinking herbal tea, to improve sleep quality."
        elif(most_likely_disorder == "Schizophrenia"):
            raag = "Kalyan"
            TOD = "evening, just after sunset"

            song1 = "Bare Bare Aar Asa Hobena"
            link1 = "https://open.spotify.com/track/1ZRHOQ2Ciikozn4jrruJmp"

            song2 = "Lal Ke Keno Bhoy"
            link2 = "https://open.spotify.com/track/607li9G8YMzWrdydgI9OcB"

            song3 = "Loke Bole Lalon Fakir"
            link3 = "https://open.spotify.com/track/06sQAV5rnZMqWU3tEdRRoZ"

            desc = "Raaga Kalyan is known for its majestic and calming essence. It combines natural and harmonic notes that create a soothing and contemplative atmosphere. The calming melodies can ease episodes of restlessness or anxiety, and encourages focus and reduces intrusive or fragmented thoughts. However we also suggest that along with listening to these songs you seek professional help and therapy support."

            firstAction = "Family and Friends: Maintain close relationships with trusted individuals who provide emotional support."
            secondAction = "Reading or Audiobooks: Explore uplifting or educational material to stay mentally active."
            thirdAction = "Establishing Hygiene Routines: Create a checklist for daily self-care tasks like bathing, grooming, and dressing."
            forthAction = "Cognitive Behavioral Therapy (CBT): Work with a therapist to address delusional thinking or distressing emotions."

        #Adding the latest predicted data in responses table
        


        session['premium'] = user
        session['disorder'] = most_likely_disorder
        session['link1'] = link1
        session['link2'] = link2
        session['link3'] = link3
        session['desc'] = desc
        session['a1'] = firstAction
        session['a2'] = secondAction
        session['a3'] = thirdAction
        session['a4'] = forthAction
        session['s1'] = song1
        session['s2'] = song2
        session['s3'] = song3
        session['raag'] = raag
        session['tod'] = TOD





        # Pass prediction to result page
        return render_template('result.html',name=session['firstname'],user=user, prediction=most_likely_disorder,link1=link1,link2=link2,link3=link3,description=desc,actions1=firstAction,actions2=secondAction,actions3=thirdAction,actions4=forthAction,song1=song1,song2=song2,song3=song3, raaga=raag,timeOfDay=TOD)
    
    
# membership
@app.route('/membership', methods=['GET', 'POST'])
def membership():
    if 'loggedin' not in session:
        flash('Please log in to purchase membership.', 'error')
        return redirect(url_for('login'))
    next_page = request.args.get('next', '/')
    return render_template('membership.html', key_id=RAZORPAY_KEY_ID, next=next_page)



@app.route('/verify', methods=['POST'])
def verify_payment():
    #Get Data From Razorpay checkout
        payment_id = request.form.get("razorpay_payment_id")
        order_id = request.form.get("razorpay_order_id")
        signature = request.form.get("razorpay_signature")
        next_page = request.args.get("next", url_for('home'))
        #Verify signature
        try:
            razorpay_client.utility.verify_payment_signature({
                "razorpay_payment_id": payment_id,
                "razorpay_order_id": order_id,
                "razorpay_signature": signature
            })
            #Update membership status
            user_id = session['user_id']
            cur = sql_connection.cursor()
            cur.execute('UPDATE users SET membership = "active" WHERE id = %s', (user_id,))
            sql_connection.commit()
            session['membership'] = "active"
            flash("Membership activated successfully!", "success")

            return redirect(next_page)
            # return render_template('result.html',name=session['firstname'],user={'is_member':True}, prediction=session['disorder'],link1=session['link1'],link2=session['link2'],link3=session['link3'],description=session['desc'],actions1=session['a1'],actions2=session['a2'],actions3=session['a3'],actions4=session['a4'],song1=session['s1'],song2=session['s2'],song3=session['s3'], raaga=session['raag'],timeOfDay=session['tod'])
        except razorpay.errors.SignatureVerificationError:
            flash("Signature verification failed", "error")
            return render_template('membership.html',key_id=RAZORPAY_KEY_ID)

        
@app.route('/order', methods=['POST'])
def create_order():
    if 'loggedin' in session:
        amount = 9900 #In Paise
        currency = "INR"

        order_data = {"amount":amount,
                      "currency":currency }
        razorpay_order = razorpay_client.order.create(data=order_data)
        return{"order_id":razorpay_order['id'],"amount":amount}
    else:
        flash('Please log in to purchase membership.', 'error')
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
        return render_template('questions.html', image_path = filepath)

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

        password_regex = r'^(?=.[a-z])(?=.[A-Z])(?=.\d)(?=.[@$!%?&])[A-Za-z\d@$!%?&]{8,30}$'
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

    # Handling GET request (when page loads)
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
    session.pop('user_id', None)  # Remove user_id from session
    flash('You have been logged out.', 'logout') 
    return redirect(url_for('login')) 



# (Other diagnosis, membership, admin routes same as your original file)


#delete function
@app.route('/delete_playlist/<playlist_id>', methods=['DELETE'])
def delete_playlist(playlist_id):
    try:
        oid = ObjectId(playlist_id)
    except InvalidId:
        return jsonify({'error': 'Invalid playlist ID'}), 400

    result = playlist_collection.delete_one({'_id': oid})
    if result.deleted_count == 1:
        return jsonify({'success': True}), 200
    else:
        return jsonify({'error': 'Playlist not found'}), 404



if __name__ == '__main__':
    app.run(debug=True) 
