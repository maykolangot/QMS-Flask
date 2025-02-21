from flask import Blueprint, render_template
from pymongo import MongoClient
from datetime import datetime
import logging

# Initialize logging
logging.basicConfig(
    filename="logs/queue_system.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# Flask Blueprint
viewQueue_bp = Blueprint('viewQueue', __name__, template_folder='templates')

# MongoDB client setup (modify with actual URI)
client = MongoClient("mongodb://localhost:27017/")
db = client["QueueSystem"]

# Configuration
CONFIG = {
    "queue_collections": {
        "cashier": "CashierQueueRecords",
        "marketing": "MarketingQueueRecords",
        "business_office": "BusinessOfficeQueueRecords",
        "csdl": "CSDLQueueRecords",
        "registrar": "RegistrarQueueRecords"
    }
}

# Route for each department queue
@viewQueue_bp.route('/queue/<department>')
def display_department_queue(department):
    """
    Display 'In Process' and 'On Queue' states for a specific department.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    states = ["In Process", "On Queue"]

    collection_name = CONFIG["queue_collections"].get(department)
    if not collection_name:
        return f"<h2>Error</h2><p>Department '{department}' not found.</p>", 404

    collection = db[collection_name]
    department_queues = {}

    for state in states:
        queues = list(collection.find(
            {"transaction": state, "date": {"$regex": f"^{today}"}}
        ).sort([
            ("priority", -1),
            ("queueNumber", 1)
        ]))
        department_queues[state] = queues

    return render_template("department_queue.html",
                           department_name=department.capitalize(),
                           queues=department_queues)