from flask import Blueprint, render_template, jsonify
import os

logs_bp = Blueprint('logs', __name__)

LOG_FILE_PATH = "./logs/queue_system.log"  # ✅ Change if needed

@logs_bp.route('/', methods=['GET'])
def view_logs():
    """Reads and returns log contents."""
    try:
        if not os.path.exists(LOG_FILE_PATH):
            return render_template('superadmin/logs.html', logs=[])  # ✅ Return empty logs initially

        with open(LOG_FILE_PATH, "r") as file:
            logs = file.readlines()[-50:]  # ✅ Return the last 50 log entries

        return render_template('superadmin/logs.html', logs=logs)

    except Exception as e:
        return render_template('superadmin/logs.html', logs=[f"Error loading logs: {str(e)}"])
