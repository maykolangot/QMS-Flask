from flask import Blueprint, jsonify, request
from pymongo import MongoClient, errors
from datetime import datetime, timedelta
import logging

request_bp = Blueprint('request', __name__)

# Configure logging
logging.basicConfig(
    filename="logs/queue_system.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

CONFIG = {
    "open_hours": {"start": "06:00", "end": "17:00"},
    "lunch_hours": {"start": "12:00", "end": "13:00"},
    "valid_sections": {"1": "Main", "2": "South"},
    "queue_collections": ["CashierQueueRecords", "MarketingQueueRecords", "BusinessOfficeQueueRecords",
                          "CSDLQueueRecords", "RegistrarQueueRecords"]
}


class RequestConsole:
    def __init__(self, db_url="mongodb://localhost:27017/", db_name="QueueSystem"):
        try:
            self.client = MongoClient(db_url)
            self.db = self.client[db_name]
        except errors.ConnectionFailure as e:
            logging.error(f"Failed to connect to MongoDB: {e}")
            raise

    def reset_queue_counter_if_needed(self, office):
        today = datetime.now().strftime("%Y-%m-%d")
        counter_doc = self.db[f"{office}Counter"].find_one({"type": "queue_reset", "date": today})
        if not counter_doc:
            self.db[f"{office}Counter"].update_one(
                {"type": "queue_reset"},
                {"$set": {"date": today, "last_counter": 0}},
                upsert=True
            )
            logging.info(f"Queue counter reset for {office} on {today}")

    def check_open_hours(self):
        now = datetime.now()
        opening_time = datetime.strptime(CONFIG["open_hours"]["start"], "%H:%M").time()
        closing_time = datetime.strptime(CONFIG["open_hours"]["end"], "%H:%M").time()
        lunch_start = datetime.strptime(CONFIG["lunch_hours"]["start"], "%H:%M").time()
        lunch_end = datetime.strptime(CONFIG["lunch_hours"]["end"], "%H:%M").time()
        return opening_time <= now.time() <= closing_time and not (lunch_start <= now.time() <= lunch_end)

    def parse_id_input(self, id_input):
        if id_input == "0000000000010":
            return None, "Guest", "South"
        elif len(id_input) == 13 and id_input.isdigit():
            id_number = id_input[:12]
            section = CONFIG["valid_sections"].get(id_input[12], "Main")
            return id_number, "Student", section
        return None, None, None

    def is_duplicate_request(self, id_number, office):
        if not id_number:
            return False
        today = datetime.now().strftime("%Y-%m-%d")
        return self.db[office].find_one({"idNumber": id_number, "date": {"$regex": f"^{today}"}}) is not None

    def calculate_estimated_wait_time(self, queue_number, office):
        today = datetime.now().strftime("%Y-%m-%d")
        queue_records = list(
            self.db[office].find({"transaction": "On Queue", "date": {"$regex": f"^{today}"}}).sort("queueNumber", 1)
        )
        for position, record in enumerate(queue_records, start=1):
            if record["queueNumber"] == queue_number:
                estimated_time = f"{(position - 1) * 1.5} minutes"
                return position, estimated_time
        return None, "N/A"

    def request_queue(self, id_input, office, priority=False):
        if not self.check_open_hours():
            return {"error": "Queue is closed during non-operational hours."}

        id_number, role, section = self.parse_id_input(id_input)
        if not role:
            return {"error": "Invalid ID input."}

        if office not in CONFIG["queue_collections"]:
            return {"error": "Invalid office selection."}

        if self.is_duplicate_request(id_number, office):
            return {"error": "Duplicate request. You have already queued today."}

        self.reset_queue_counter_if_needed(office)
        queue_prefix = "P" if priority else "S"
        today = datetime.now().strftime("%Y-%m-%d")
        counter_doc = self.db[f"{office}Counter"].find_one_and_update(
            {"type": "queue_reset", "date": today},
            {"$inc": {"last_counter": 1}, "$setOnInsert": {"date": today}},
            upsert=True, return_document=True
        )

        queue_counter = counter_doc["last_counter"]
        queue_number = f"{queue_prefix}-{queue_counter:04d}-{section.upper()}"

        # Debugging line to check queue number generation
        officeStrip = office.removesuffix("QueueRecords")
        print(f"Generated Queue Number: {queue_number}  {id_number}  {officeStrip}")


        self.db[office].insert_one({
            "idNumber": id_number,
            "role": role,
            "section": section.upper(),
            "queueNumber": queue_number,
            "priority": priority,
            "transaction": "On Queue",
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

        position, estimated_time = self.calculate_estimated_wait_time(queue_number, office)

        # Fixed return statement to ensure queue_number is included
        return {
            "message": f"Queue number {queue_number} assigned.",
            "queue_number": queue_number,  # Ensure queue_number is included
            "position": position,
            "estimated_wait_time": estimated_time
        }
    # Dito yung Printer


request_console = RequestConsole()


@request_bp.route('/request_queue', methods=['POST'])
def request_queue():
    data = request.json
    id_input = data.get("id_input")
    office = data.get("office")
    priority = data.get("priority", False)

    if not id_input or not office:
        return jsonify({"error": "Missing required fields."}), 400

    response = request_console.request_queue(id_input, office, priority)
    return jsonify(response)