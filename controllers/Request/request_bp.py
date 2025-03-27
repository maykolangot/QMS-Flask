from flask import Blueprint, jsonify, request
from pymongo import MongoClient, errors
from datetime import datetime, timedelta
import logging
import usb.core
import usb.util

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

    def reset_queue_counter_if_needed(self, office, priority):
        queue_type = "P" if priority else "S"
        today = datetime.now().strftime("%Y-%m-%d")

        # Check and reset specific queue type counter
        counter_doc = self.db[f"{office}Counter"].find_one({
            "type": "queue_reset",
            "date": today,
            "queue_type": queue_type
        })

        if not counter_doc:
            self.db[f"{office}Counter"].insert_one({
                "type": "queue_reset",
                "date": today,
                "queue_type": queue_type,
                "last_counter": 0
            })
            logging.info(f"Queue counter reset for {office} {queue_type} on {today}")

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
        elif id_input == "0000000000011":
            return None, "Student", "Main"
        elif id_input == "0000000000012":
            return None, "Student", "South"
        elif len(id_input) == 13 and id_input.isdigit():
            id_number = id_input[:12]
            section = CONFIG["valid_sections"].get(id_input[12], "Main")
            return id_number, "Student", section
        return None, None, None

    def is_duplicate_request(self, id_number, office):
        if not id_number:
            return False
        today = datetime.now().strftime("%Y-%m-%d")

        # Only consider active queue entries (not cancelled/completed)
        existing = self.db[office].find_one({
            "idNumber": id_number,
            "date": {"$regex": f"^{today}"},
            "transaction": {"$nin": ["Cut Off/Cancelled", "Completed"]}  # Match exact status
        })
        return existing is not None

    def calculate_estimated_wait_time(self, queue_number, office):
        today = datetime.now().strftime("%Y-%m-%d")
        # Get all queue entries sorted by priority first, then queue number
        queue_records = list(self.db[office].find({
            "transaction": "On Queue",
            "date": {"$regex": f"^{today}"}
        }).sort([
            ("priority", -1),  # Priority first
            ("queueNumber", 1)
        ]))

        current_position = None
        for index, record in enumerate(queue_records):
            if record["queueNumber"] == queue_number:
                current_position = index + 1
                break

        if current_position is None:
            return None, "N/A"

        # Calculate based on position in the merged queue
        estimated_time = f"{(current_position - 1) * 1.5} minutes"
        return current_position, estimated_time

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

        self.reset_queue_counter_if_needed(office, priority)
        queue_prefix = "P" if priority else "S"
        today_date = datetime.now().strftime("%Y-%m-%d")

        # Get separate counter for priority/standard
        counter_doc = self.db[f"{office}Counter"].find_one_and_update(
            {
                "type": "queue_reset",
                "date": today_date,
                "queue_type": queue_prefix  # Add queue type distinction
            },
            {"$inc": {"last_counter": 1}, "$setOnInsert": {
                "date": today_date,
                "queue_type": queue_prefix
            }},
            upsert=True,
            return_document=True
        )

        queue_counter = counter_doc["last_counter"]
        queue_number = f"{queue_prefix}-{queue_counter:04d}-{section.upper()}"
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

        self.print_ticket(office, queue_number, today_date)

        return {
            "message": f"Queue number {queue_number} assigned.",
            "queue_number": queue_number,
            "position": position,
            "estimated_wait_time": estimated_time
        }
    # Dito yung printer

    def print_ticket(self, office, queue_number, today_date):
        """ Prints the queue ticket via USB thermal printer with formatting & logo """

        department = office.removesuffix("QueueRecords")

        try:
            dev = usb.core.find(idVendor=0x0FE6, idProduct=0x811E)
            if dev is None:
                print("❌ Printer not detected.")
                return

            dev.set_configuration()

            # Claim the interface before using it
            cfg = dev.get_active_configuration()
            intf = cfg[(0, 0)]
            usb.util.claim_interface(dev, intf.bInterfaceNumber)

            # Get OUT endpoint
            ep_out = usb.util.find_descriptor(
                intf,
                custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT,
            )

            if ep_out:
                # ✅ ESC/POS COMMANDS for better formatting
                esc_reset = b'\x1b\x40'  # ESC @ (Reset printer)
                esc_center = b'\x1b\x61\x01'  # Center align
                esc_double_height = b'\x1b\x21\x10'  # Double height text
                esc_double_width = b'\x1b\x21\x20'  # Double width text
                esc_cut = b'\x1d\x56\x00'  # Cut paper

                esc_logo = b'\x1d\x2f\x00'  # Print logo if supported (Replace with actual image command)

                # 🖨 PRINT TICKET DESIGN
                ep_out.write(esc_reset)
                ep_out.write(esc_center + esc_logo)  # Print Logo Placeholder
                ep_out.write(b'\n')

                ep_out.write(esc_center + esc_double_height)
                ep_out.write(f"{department.upper()}\n".encode('utf-8'))  # Centered Office Name
                ep_out.write(b'\n')

                ep_out.write(esc_center + esc_double_width)
                ep_out.write(f"QUEUE NUMBER\n".encode('utf-8'))
                ep_out.write(esc_double_height + f"{queue_number}\n".encode('utf-8'))  # Large Queue Number
                ep_out.write(b'\n')

                ep_out.write(esc_center)
                ep_out.write(f"Date: {today_date}\n".encode('utf-8'))  # Print Date
                ep_out.write(b'\n')

                ep_out.write(esc_center)
                ep_out.write(b"Please wait for your turn.\n")  # Add a message
                ep_out.write(b'\n\n')

                ep_out.write(esc_cut)  # Cut paper
                print("✅ Printed queue ticket successfully!")

            usb.util.release_interface(dev, intf.bInterfaceNumber)
            usb.util.dispose_resources(dev)  # Free resources to avoid conflicts

        except Exception as e:
            print("❌ Printing error:", e)

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
