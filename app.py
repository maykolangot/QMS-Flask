from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, g
from pymongo import MongoClient
from flask_session import Session
from flask_cors import CORS
from dotenv import load_dotenv
import os
import hashlib
# from cashier_console import CashierConsole
from bson import ObjectId
from datetime import datetime
from threading import Thread
from jinja2 import TemplateNotFound

# Request
from controllers.Request.request_bp import request_bp
from viewQueue_bp import viewQueue_bp

# Office controls
from controllers.Staff.csdl_blueprint import csdl_bp
from controllers.Staff.cashier_blueprint import cashier_bp
from controllers.Staff.marketing_blueprint import marketing_bp
from controllers.Staff.business_blueprint import business_bp
from controllers.Staff.registrar_blueprint import registrar_bp


# Superadmin Controls
from controllers.Stats.stats import stats_bp
from controllers.Stats.stats import fetch_latest_data, fetch_past_30_days, generate_trend_chart, generate_pie_chart, generate_hourly_distribution_chart

from controllers.Superadmin.users import users_bp
from controllers.Superadmin.adminControls_bp import adminControls_bp


# Loggings
from logs_bp import logs_bp

# Load environment variables from .env
load_dotenv()

app = Flask(__name__)
CORS(app)
app.secret_key = os.getenv('FLASK_SECRET_KEY')  # Load secret key from .env
app.config['SESSION_TYPE'] = 'filesystem'
Session(app)

# MongoDB Configuration
mongo_uri = os.getenv('MONGO_URI')  # Load MongoDB URI from .env
client = MongoClient(mongo_uri)
db = client['QueueSystem']  # Database name
users_collection = db['users']  # Users collection
collection = db["QueueRecords"]  # Queue Collection


# Helper function to hash passwords
def hash_password(password):
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


# Home or Index route
app.register_blueprint(request_bp, url_prefix='/api')


@app.route('/')
def index():
    return render_template('index3.html')



# Signup route (create superadmin user temporarily)
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        # Creating the superadmin user temporarily
        username = request.form.get('username')
        password = request.form.get('password')

        # Check if user already exists
        if users_collection.find_one({'username': username}):
            flash('Username already exists. Please choose another.', 'danger')
        else:
            hashed_password = hash_password(password)
            users_collection.insert_one(
                {'name': 'Superadmin', 'role': 'superadmin', 'username': username, 'password': hashed_password})
            flash('Superadmin created successfully!', 'success')
            return redirect(url_for('login'))

    return render_template('signup.html')


# Login route
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = users_collection.find_one({'username': username})
        if user and user['password'] == hash_password(password):
            session['username'] = username
            session['role'] = user['role']  # Store the user's role
            flash('Login successful!', 'success')
            return redirect(url_for(user['role']))
        flash('Invalid username or password.', 'danger')
        return redirect(url_for('login'))
    return render_template('login.html')


# Helper function to check the user's role
def check_role(role):
    if 'username' not in session or session['role'] != role:
        flash(f"Warning: You do not have access to this page. Redirecting to your {role} page.", 'warning')
        return redirect(url_for(role))
    return None  # No redirection needed, proceed with the route logic


# CSDL ----------------------------------------------------------------
app.register_blueprint(csdl_bp, url_prefix='/csdl_api')


@app.route('/csdl')
def csdl():
    if 'username' not in session or session['role'] != 'csdl':
        return redirect('/login')
    return render_template('csdl.html')


# Cashier --------------------------------------------------------------
app.register_blueprint(cashier_bp, url_prefix='/cashier_api')


@app.route('/cashier')
def cashier():
    if 'username' not in session or session['role'] != 'cashier':
        return redirect('/login')
    return render_template('cashier.html')


# Marketing Office -----------------------------------------------------
app.register_blueprint(marketing_bp, url_prefix='/marketing_api')


@app.route('/marketing')
def marketing():
    if 'username' not in session or session['role'] != 'marketing':
        return redirect('/login')
    return render_template('marketing.html')


# Business Office ------------------------------------------------------
app.register_blueprint(business_bp, url_prefix='/business_api')


@app.route('/business_office')
def business_office():
    # Ensure the user is logged in
    if 'username' not in session or session['role'] != 'business_office':
        return redirect(url_for('login'))  # Redirect to login page if not logged in
    return render_template('business_office.html')


# Registrar ----------------------------------------------------------
app.register_blueprint(registrar_bp, url_prefix='/registrar_api')


@app.route('/registrar')
def registrar():
    if 'username' not in session or session['role'] != 'registrar':
        return redirect('/login')
    return render_template('registrar.html')


# Superadmin route (only superadmin can access this to create users)
# Datas
app.register_blueprint(stats_bp, url_prefix='/superadmin/stats')
app.register_blueprint(users_bp, url_prefix='/superadmin/users')
app.register_blueprint(adminControls_bp, url_prefix='/superadmin/settings')
app.register_blueprint(logs_bp, url_prefix='/superadmin/logs')

@app.route('/superadmin')
def superadmin():
    if 'username' not in session or session.get('role') != 'superadmin':
        return redirect('/login')
    return render_template('superadmin/superadmin-base.html')  # Loads the base layout


@app.route('/page/<page>')
def load_page(page):
    try:
        if page == "stats":  # Only fetch data for stats.html
            data = fetch_latest_data() or {}
            past_data = fetch_past_30_days()
            trend_chart = generate_trend_chart(past_data) if past_data else None
            pie_chart = generate_pie_chart(data) if data else None
            hourly_chart = generate_hourly_distribution_chart(data) if data else None

            return render_template(
                f"superadmin/{page}.html",
                data=data,
                trend_chart=trend_chart,
                pie_chart=pie_chart,
                hourly_chart=hourly_chart
            )

        return render_template(f"superadmin/{page}.html")  # Default case

    except TemplateNotFound:
        return "<h2>Error</h2><p>Page not found.</p>", 404


# View Queue
app.register_blueprint(viewQueue_bp)



# Logout route
@app.route('/logout', methods=['POST'])
def logout():
    session.pop('username', None)
    session.pop('role', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


# Route for editing user information (only allowed to edit own info, not role)
@app.route('/edit_profile', methods=['GET', 'POST'])
def edit_profile():
    if 'username' not in session:
        return redirect(url_for('login'))

    user = users_collection.find_one({'username': session['username']})

    if request.method == 'POST':
        # Retrieve form data
        username = request.form.get('username')
        old_password = request.form.get('old_password')
        new_password = request.form.get('new_password')

        # Validate old password
        if hash_password(old_password) != user['password']:
            flash('Old password is incorrect.', 'danger')
            return redirect(url_for('edit_profile'))

        # Update username if changed
        if username and username != user['username']:
            user['username'] = username

        # Update password if a new one is provided
        if new_password:
            user['password'] = hash_password(new_password)

        # Update the database
        users_collection.update_one(
            {'_id': user['_id']},
            {"$set": {'username': user['username'], 'password': user['password']}}
        )

        # Update session data
        session['username'] = user['username']
        flash('Profile updated successfully!', 'success')
        return redirect(url_for(session['role']))

    return render_template('edit_profile.html', user=user)


if __name__ == '__main__':
    # Optional: Start background threads for polling changes and auto cut-off
    # polling_thread = Thread(target=console.poll_changes, daemon=True)
    # polling_thread.start()

    # cutoff_thread = Thread(target=console.auto_cut_off, daemon=True)
    # cutoff_thread.start()

    app.run(debug=True, host='0.0.0.0', port=5000)
