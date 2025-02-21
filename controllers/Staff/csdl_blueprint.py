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
    username = session.get("username")
    if not username:
        return jsonify({"error": "User not logged in"}), 403

    today = datetime.now().strftime("%Y-%m-%d")

    logging.info(f"User {username} requested the next queue.")

    # Complete the current queue in process
    current_queue = queue_collection.find_one_and_update(
        {"transaction": "In Process", "reserved_by": username, "date": {"$regex": f"^{today}"}},
        {"$set": {"transaction": "Completed", "reserved_by": username}},
        return_document=True
    )

    if current_queue:
        logging.info(f"Completed queue: {current_queue['queueNumber']} by {username}")

    # Fetch the next queue (prioritizing high priority & lower queue numbers)
    next_queue = queue_collection.find_one_and_update(
        {"transaction": "On Queue", "reserved_by": None, "date": {"$regex": f"^{today}"}},
        {"$set": {"transaction": "In Process", "reserved_by": username}},
        sort=[("priority", -1), ("queueNumber", 1)],
        return_document=True
    )

    if next_queue:
        logging.info(f"Next queue assigned to {username}: {next_queue['queueNumber']}")
        return jsonify({
            "message": f"Next queue reserved: {next_queue['queueNumber']}",
            "queueNumber": next_queue["queueNumber"]
        })

    logging.info("No available queues to process.")
    return jsonify({"message": "No available queues to process."})


# Hold Current Queue
@csdl_bp.route('/hold_queue', methods=['POST'])
def hold_queue():
    username = session.get("username")
    if not username:
        return jsonify({"error": "User not logged in"}), 403

    today = datetime.now().strftime("%Y-%m-%d")

    logging.info(f"User {username} requested to hold a queue.")

    queue = queue_collection.find_one_and_update(
        {"transaction": "In Process", "reserved_by": username, "date": {"$regex": f"^{today}"}},
        {"$set": {"transaction": "On Hold", "reserved_by": None, "hold_timestamp": datetime.utcnow()}},
        return_document=True
    )

    if queue:
        logging.info(f"Queue {queue['queueNumber']} put on hold by {username}.")
        return jsonify({"message": f"Queue {queue['queueNumber']} put on hold."})

    logging.warning(f"No queues available for {username} to hold.")
    return jsonify({"message": "No queues available to hold."})


# Get Queue Status for GUI
@csdl_bp.route('/queue_status', methods=['GET'])
def queue_status():
    username = session.get("username")
    if not username:
        return jsonify({"error": "User not logged in"}), 403

    today = datetime.now().strftime("%Y-%m-%d")

    logging.info(f"Fetching queue status for user: {username}")
    logging.info(f"Using date filter: {today}")

    on_queue_count = queue_collection.count_documents({"transaction": "On Queue", "date": {"$regex": f"^{today}"}})
    on_hold_count = queue_collection.count_documents({"transaction": "On Hold", "date": {"$regex": f"^{today}"}})
    cut_off_count = queue_collection.count_documents(
        {"transaction": "Cut Off/Cancelled", "date": {"$regex": f"^{today}"}})

    logging.info(f"On Queue: {on_queue_count}, On Hold: {on_hold_count}, Cut Off: {cut_off_count}")

    in_process_queue = queue_collection.find_one(
        {"transaction": "In Process", "reserved_by": username, "date": {"$regex": f"^{today}"}},
        sort=[("queueNumber", 1)]
    )

    if in_process_queue:
        in_process_message = f"Queue {in_process_queue['queueNumber']} (ID: {in_process_queue.get('idNumber', 'N/A')})"
    else:
        in_process_message = None

    return jsonify({
        "on_queue_count": on_queue_count,
        "on_hold_count": on_hold_count,
        "cut_off_count": cut_off_count,
        "in_process_queue": in_process_message
    })


@csdl_bp.route('/pause_queue', methods=['POST'])
def pause_queue():
    """
    Completes the current queue but prevents fetching the next one.
    """
    username = session.get("username")
    if not username:
        return jsonify({"error": "User not logged in"}), 403

    today = datetime.now().strftime("%Y-%m-%d")

    # Complete the current 'In Process' queue
    current_queue = queue_collection.find_one_and_update(
        {"transaction": "In Process", "reserved_by": username, "date": {"$regex": f"^{today}"}},
        {"$set": {"transaction": "Completed", "reserved_by": username}},
        return_document=True
    )

    if current_queue:
        logging.info(f"Queue {current_queue['queueNumber']} marked as 'Completed' by {username}.")
        return jsonify({
            "message": f"Queue {current_queue['queueNumber']} completed successfully.",
            "queueNumber": current_queue["queueNumber"]
        })

    logging.info(f"No active queue for {username} to complete.")
    return jsonify({"message": "No active queue to complete."})


# Start Background Tasks
def start_background_tasks():
    def periodic_auto_cutoff():
        """ Automatically cancels all 'On Queue' transactions after the cut-off time. """
        while True:
            try:
                today = get_today()
                now = datetime.utcnow().time()
                cutoff_time = datetime.strptime(CONFIG["cut_off_time"], "%H:%M").time()

                if now >= cutoff_time:
                    expired_queues = queue_collection.count_documents(
                        {"transaction": "On Queue", "date": {"$regex": f"^{today}"}}
                    )

                    if expired_queues > 0:
                        queue_collection.update_many(
                            {"transaction": "On Queue", "date": {"$regex": f"^{today}"}},
                            {"$set": {"transaction": "Cut Off/Cancelled"}}
                        )
                        logging.info(f"System automatically canceled {expired_queues} expired queues.")
                    else:
                        logging.info("No queues required auto cut-off.")

                time.sleep(60)  # Check every minute

            except Exception as e:
                logging.error(f"Error in periodic_auto_cutoff: {e}")
                time.sleep(10)  # Wait before retrying to avoid infinite errors

    def periodic_cancel_expired_holds():
        """ Cancels queues that have been 'On Hold' for more than 30 minutes. """
        while True:
            try:
                expiration_time = datetime.utcnow() - timedelta(minutes=30)
                today = get_today()

                expired_holds = queue_collection.count_documents(
                    {"transaction": "On Hold", "hold_timestamp": {"$lt": expiration_time},
                     "date": {"$regex": f"^{today}"}}
                )

                if expired_holds > 0:
                    queue_collection.update_many(
                        {"transaction": "On Hold", "hold_timestamp": {"$lt": expiration_time},
                         "date": {"$regex": f"^{today}"}},
                        {"$set": {"transaction": "Cut Off/Cancelled"}}
                    )
                    logging.info(f"System automatically canceled {expired_holds} expired holds.")
                else:
                    logging.info("No expired holds found for cancellation.")

                time.sleep(180)  # Run every 3 minutes

            except Exception as e:
                logging.error(f"Error in periodic_cancel_expired_holds: {e}")
                time.sleep(10)  # Wait before retrying to avoid infinite errors

    # Start Background Threads
    threading.Thread(target=periodic_auto_cutoff, daemon=True).start()
    threading.Thread(target=periodic_cancel_expired_holds, daemon=True).start()


start_background_tasks()
