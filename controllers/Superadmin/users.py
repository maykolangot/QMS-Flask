from flask import Blueprint, render_template, request, jsonify
from pymongo import MongoClient
import hashlib

users_bp = Blueprint('users', __name__, url_prefix='/users')

# Database connection
mongo_uri = 'mongodb://localhost:27017/'
client = MongoClient(mongo_uri)
db = client['QueueSystem']
users_collection = db['users']

def hash_password(password):
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

# Read Users (Displays All Users)
@users_bp.route('', methods=['GET'])
@users_bp.route('/', methods=['GET'])
def read_users():
    roles = ['csdl', 'business_office', 'marketing', 'cashier', 'registrar']
    users = list(users_collection.find({}, {'_id': 0}))
    return render_template('superadmin/users.html', roles=roles, users=users)

# Create User ✅ FIXED
@users_bp.route('/create', methods=['POST'])
def create_user():
    name = request.form.get('name')
    role = request.form.get('role')
    username = request.form.get('username')
    password = request.form.get('password')

    if not name or not role or not username or not password:
        return jsonify({"error": "All fields are required!"}), 400

    if users_collection.find_one({'username': username}):
        return jsonify({"error": "Username already exists!"}), 400
    else:
        hashed_password = hash_password(password)
        users_collection.insert_one({
            'name': name,
            'role': role,
            'username': username,
            'password': hashed_password
        })
        return jsonify({"message": "User created successfully!"}), 200

# Update User ✅ FIXED
@users_bp.route('/update/<username>', methods=['POST'])
def update_user(username):
    user = users_collection.find_one({'username': username})
    if not user:
        return jsonify({"error": "User not found"}), 404

    name = request.form.get('name')
    role = request.form.get('role')
    password = request.form.get('password')

    update_data = {'name': name, 'role': role}
    if password:
        update_data['password'] = hash_password(password)

    users_collection.update_one({'username': username}, {'$set': update_data})
    return jsonify({"message": "User updated successfully!"}), 200

# Delete User ✅ FIXED
@users_bp.route('/delete/<username>', methods=['POST'])
def delete_user(username):
    users_collection.delete_one({'username': username})
    return jsonify({"message": "User deleted successfully!"}), 200
