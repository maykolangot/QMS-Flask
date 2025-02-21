from flask import Blueprint, jsonify, request, render_template, session
from pymongo import MongoClient, errors
from datetime import datetime
import logging

adminControls_bp = Blueprint('adminControls', __name__, url_prefix='settings')

# Configure logging
logging.basicConfig(
    filename="logs/admin_console.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

CONFIG = {
    "db_url": "mongodb://localhost:27017/",
    "db_name": "QueueSystem",
    "queue_collections": [
        "CashierQueueRecords", "MarketingQueueRecords", "BusinessOfficeQueueRecords",
        "CSDLQueueRecords", "RegistrarQueueRecords"
    ]
}


class AdminConsole:
    def __init__(self):
        try:
            self.client = MongoClient(CONFIG["db_url"])
            self.db = self.client[CONFIG["db_name"]]
        except errors.ConnectionFailure as e:
            logging.error(f"Failed to connect to MongoDB: {e}")
            raise

    def view_cashier_transactions(self, office, cashier_username):
        today = datetime.now().strftime("%Y-%m-%d")
        collection = self.db[office]
        stats = {
            "holds": collection.count_documents(
                {"transaction": "On Hold", "reserved_by": cashier_username, "date": {"$regex": f"^{today}"}}),
            "completed": collection.count_documents(
                {"transaction": "Completed", "reserved_by": cashier_username, "date": {"$regex": f"^{today}"}}),
            "cutoffs": collection.count_documents(
                {"transaction": "Cut Off/Cancelled", "reserved_by": cashier_username, "date": {"$regex": f"^{today}"}}),
        }
        logging.info(f"Viewed transactions for cashier '{cashier_username}' in office '{office}': {stats}")
        return stats

    def cancel_queues(self, office):
        today = datetime.now().strftime("%Y-%m-%d")
        collection = self.db[office]
        result = collection.update_many(
            {"transaction": "On Queue", "date": {"$regex": f"^{today}"}},
            {"$set": {"transaction": "Cut Off/Cancelled"}}
        )
        logging.info(f"Cancelled all queues in office '{office}': {result.modified_count} queues updated.")
        return result.modified_count

    def set_priority_section(self, office, section):
        if section not in ["MAIN", "SOUTH"]:
            return {"error": "Invalid section. Choose either 'MAIN' or 'SOUTH'."}
        today = datetime.now().strftime("%Y-%m-%d")
        collection = self.db[office]
        result = collection.update_many(
            {"transaction": "On Queue", "section": section, "date": {"$regex": f"^{today}"}},
            {"$set": {"priority": True}}
        )
        logging.info(f"Prioritized section '{section}' in office '{office}': {result.modified_count} queues updated.")
        return result.modified_count

    def cancel_section_queues(self, office, section):
        if section not in ["MAIN", "SOUTH"]:
            return {"error": "Invalid section. Choose either 'MAIN' or 'SOUTH'."}
        collection = self.db[office]
        result = collection.update_many(
            {"transaction": "On Queue", "section": section},
            {"$set": {"transaction": "Cut Off/Cancelled"}}
        )
        logging.info(
            f"Cancelled queues from section '{section}' in office '{office}': {result.modified_count} queues updated.")
        return result.modified_count


admin_console = AdminConsole()


@adminControls_bp.route('/view_cashier_transactions', methods=['POST'])
def view_cashier_transactions():
    data = request.json
    office = data.get("office")
    cashier_username = data.get("cashier_username")
    if not office or not cashier_username:
        return jsonify({"error": "Missing required fields."}), 400
    stats = admin_console.view_cashier_transactions(office, cashier_username)
    return jsonify(stats)


@adminControls_bp.route('/cancel_queues', methods=['POST'])
def cancel_queues():
    data = request.json
    office = data.get("office")
    if not office:
        return jsonify({"error": "Missing office field."}), 400
    count = admin_console.cancel_queues(office)
    return jsonify({"message": f"{count} queues have been cancelled."})


@adminControls_bp.route('/set_priority_section', methods=['POST'])
def set_priority_section():
    data = request.json
    logging.info(f"Received data for set_priority_section: {data}")

    office = data.get("office")
    section = data.get("section")

    if not office or not section:
        logging.error("Missing office or section in request payload.")
        return jsonify({"error": "Both office and section fields are required."}), 400

    if office not in CONFIG["queue_collections"]:
        return jsonify({"error": f"Invalid office: {office}."}), 400

    result = admin_console.set_priority_section(office, section)
    if isinstance(result, dict):
        return jsonify(result), 400

    return jsonify({"message": f"{result} queues from section '{section}' have been prioritized."})


@adminControls_bp.route('/cancel_section_queues', methods=['POST'])
def cancel_section_queues():
    data = request.json
    office = data.get("office")
    section = data.get("section")

    if not office or not section:
        return jsonify({"error": "Both office and section fields are required."}), 400

    if office not in CONFIG["queue_collections"]:
        return jsonify({"error": f"Invalid office: {office}."}), 400

    result = admin_console.cancel_section_queues(office, section)
    if isinstance(result, dict):
        return jsonify(result), 400

    return jsonify({"message": f"{result} queues from section '{section}' have been cancelled."})


@adminControls_bp.route('/')
def settings_dashboard():
    if 'username' not in session or session['role'] != 'superadmin':
        return redirect(url_for('login'))
    return render_template('superadmin/settings.html')