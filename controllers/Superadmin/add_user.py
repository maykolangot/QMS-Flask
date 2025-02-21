from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from pymongo import MongoClient
import hashlib
import os
from dotenv import load_dotenv
from controllers.Superadmin.superadmin import superadmin_bp

load_dotenv()

# MongoDB setup
mongo_uri = os.getenv('MONGO_URI')
client = MongoClient(mongo_uri)
db = client['QueueSystem']
users_collection = db['users']

# Create a sub-blueprint
add_user_bp = Blueprint('/add_user', __name__)

# Attach this sub-blueprint to the main blueprint
@superadmin_bp.route('/add_user', methods=['GET', 'POST'])
def add_user():
    if 'username' not in session or session.get('role') != 'superadmin':
        return redirect(url_for('login'))

    if request.method == 'POST':
        name = request.form.get('name')
        role = request.form.get('role')
        username = request.form.get('username')
        password = request.form.get('password')

        if users_collection.find_one({'username': username}):
            flash('Username already exists. Please choose another.', 'danger')
        else:
            hashed_password = hashlib.sha256(password.encode('utf-8')).hexdigest()
            users_collection.insert_one({
                'name': name,
                'role': role,
                'username': username,
                'password': hashed_password
            })
            flash('User created successfully!', 'success')

    roles = ['csdl', 'marketing', 'business_office', 'registrar', 'cashier']
    return render_template('superadmin/add-user.html', roles=roles)
