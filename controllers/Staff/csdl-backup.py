from flask import Blueprint, jsonify, request, session
from datetime import datetime, timedelta
import threading
import logging
import time
from pymongo import MongoClient, errors

# Initialize Flask Blueprint
csdl_bp = Blueprint('csdl', __name__)

# Logging Configuration
logging.basicConfig(
    filename="logs/queue_system.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# MongoDB Configurations
CONFIG = {
    "cut_off_time": "17:00",
    "db_url": "mongodb://localhost:27017/",
    "db_name": "QueueSystem",
    "collection_name": "CSDLQueueRecords"
}

# Establish MongoDB Connection
try:
    mongo_client = MongoClient(CONFIG["db_url"])
    db = mongo_client[CONFIG["db_name"]]
    queue_collection = db[CONFIG["collection_name"]]
except errors.ConnectionFailure as e:
    logging.error(f"Failed to connect to MongoDB: {e}")
    raise RuntimeError("Database connection failed.")


# Helper Function: Get Current Date
def get_today():
    return datetime.utcnow().strftime("%Y-%m-%d")  # Ensure consistency with MongoDB stored format


# Helper Function: Ensure User is Logged In
def get_username():
    return session.get("username")


# Fetch Next Queue
@csdl_bp.route('/get_next_queue', methods=['POST'])
def get_next_queue():
    username = get_username()
    if not username:
        return jsonify({"error": "User not logged in"}), 403

    today = get_today()

    # Complete the current queue in process
    current_queue = queue_collection.find_one_and_update(
        {"transaction": "In Process", "reserved_by": username, "date": {"$regex": f"^{today}"}},
        {"$set": {"transaction": "Completed", "reserved_by": username}},
        return_document=True
    )

    # Fetch the next queue (prioritizing high priority & lower queue numbers)
    next_queue = queue_collection.find_one_and_update(
        {"transaction": "On Queue", "reserved_by": None, "date": {"$regex": f"^{today}"}},
        {"$set": {"transaction": "In Process", "reserved_by": username}},
        sort=[("priority", -1), ("queueNumber", 1)],
        return_document=True
    )

    if next_queue:
        logging.info(f"Queue {next_queue['queueNumber']} reserved by {username}.")
        return jsonify({
            "message": f"Next queue reserved: {next_queue['queueNumber']}",
            "queueNumber": next_queue["queueNumber"]
        })

    return jsonify({"message": "No available queues to process."})


# Hold Current Queue
@csdl_bp.route('/hold_queue', methods=['POST'])
def hold_queue():
    username = get_username()
    if not username:
        return jsonify({"error": "User not logged in"}), 403

    today = get_today()

    queue = queue_collection.find_one_and_update(
        {"transaction": "In Process", "reserved_by": username, "date": {"$regex": f"^{today}"}},
        {"$set": {"transaction": "On Hold", "reserved_by": None, "hold_timestamp": datetime.utcnow()}},
        return_document=True
    )

    if queue:
        logging.info(f"Queue {queue['queueNumber']} put on hold by {username}.")
        return jsonify({"message": f"Queue {queue['queueNumber']} put on hold."})

    return jsonify({"message": "No queues available to hold."})


# Cancel Queues Past Cut-Off Time
@csdl_bp.route('/cancel_queues', methods=['POST'])
def cancel_queues():
    username = get_username()
    if not username:
        return jsonify({"error": "User not logged in"}), 403

    today = get_today()
    cutoff_time = datetime.strptime(CONFIG["cut_off_time"], "%H:%M").time()

    now = datetime.utcnow().time()
    if now >= cutoff_time:
        result = queue_collection.update_many(
            {"transaction": "On Queue", "date": {"$regex": f"^{today}"}},
            {"$set": {"transaction": "Cut Off/Cancelled"}}
        )

        logging.info(f"{result.modified_count} queues manually canceled by {username}.")
        return jsonify({"message": f"{result.modified_count} queues canceled due to cut-off time."})

    return jsonify({"message": "Cut-off time not yet reached."})


# Cancel Expired Holds (30+ Minutes)
@csdl_bp.route('/cancel_expired_holds', methods=['POST'])
def cancel_expired_holds():
    username = get_username()
    if not username:
        return jsonify({"error": "User not logged in"}), 403

    expiration_time = datetime.utcnow() - timedelta(minutes=30)
    today = get_today()

    result = queue_collection.update_many(
        {"transaction": "On Hold", "hold_timestamp": {"$lt": expiration_time}, "date": {"$regex": f"^{today}"}},
        {"$set": {"transaction": "Cut Off/Cancelled"}}
    )

    logging.info(f"{result.modified_count} expired holds canceled by system.")
    return jsonify({"message": f"{result.modified_count} expired holds canceled."})


# Get Queue Status for GUI
@csdl_bp.route('/queue_status', methods=['GET'])
def queue_status():
    username = get_username()
    if not username:
        return jsonify({"error": "User not logged in"}), 403

    today = get_today()

    # Fetch queue counts
    on_queue_count = queue_collection.count_documents({"transaction": "On Queue", "date": {"$regex": f"^{today}"}})
    on_hold_count = queue_collection.count_documents({"transaction": "On Hold", "date": {"$regex": f"^{today}"}})
    cut_off_count = queue_collection.count_documents(
        {"transaction": "Cut Off/Cancelled", "date": {"$regex": f"^{today}"}})

    # Fetch in-process queue for user
    in_process_queue = queue_collection.find_one(
        {"transaction": "In Process", "reserved_by": username, "date": {"$regex": f"^{today}"}},
        sort=[("queueNumber", 1)]
    )

    in_process_message = (
        f"Queue {in_process_queue['queueNumber']} (ID: {in_process_queue['idNumber']})"
        if in_process_queue else None
    )

    return jsonify({
        "on_queue_count": on_queue_count,
        "on_hold_count": on_hold_count,
        "cut_off_count": cut_off_count,
        "in_process_queue": in_process_message
    })


# Background Tasks
def start_background_tasks():
    """
    Starts periodic queue cut-off and expired hold cancellations.
    """

    def periodic_auto_cutoff():
        while True:
            today = get_today()
            now = datetime.utcnow().time()
            cutoff_time = datetime.strptime(CONFIG["cut_off_time"], "%H:%M").time()

            if now >= cutoff_time:
                queue_collection.update_many(
                    {"transaction": "On Queue", "date": {"$regex": f"^{today}"}},
                    {"$set": {"transaction": "Cut Off/Cancelled"}}
                )
                logging.info("System automatically canceled expired queues.")
            time.sleep(60)

    def periodic_cancel_expired_holds():
        while True:
            expiration_time = datetime.utcnow() - timedelta(minutes=30)
            today = get_today()

            queue_collection.update_many(
                {"transaction": "On Hold", "hold_timestamp": {"$lt": expiration_time}, "date": {"$regex": f"^{today}"}},
                {"$set": {"transaction": "Cut Off/Cancelled"}}
            )
            logging.info("System automatically canceled expired holds.")
            time.sleep(180)

    threading.Thread(target=periodic_auto_cutoff, daemon=True).start()
    threading.Thread(target=periodic_cancel_expired_holds, daemon=True).start()


# Start Background Tasks
start_background_tasks()
