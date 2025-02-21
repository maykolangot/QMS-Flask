import time
from pymongo import MongoClient
from datetime import datetime, timedelta

# Connect to MongoDB
client = MongoClient("mongodb://localhost:27017/")
db = client["QueueSystem"]

# Collections
queue_records = db["CashierQueueRecords"]
queue_stats = db["CashierQueueStats"]

# Aggregation Pipeline
def get_daily_stats_pipeline(start_date_str, end_date_str):
    return [
        {"$match": {"date": {"$gte": start_date_str, "$lte": end_date_str}}},
        {"$group": {
            "_id": {"date": {"$substr": ["$date", 0, 10]}},
            "total_transactions": {"$sum": 1},
            "completed": {"$sum": {"$cond": [{"$eq": ["$transaction", "Completed"]}, 1, 0]}},
            "cut_off_cancelled": {"$sum": {"$cond": [{"$regexMatch": {"input": "$transaction", "regex": "^Cut Off/Cancelled$", "options": "i"}}, 1, 0]}},
            "priority_count": {"$sum": {"$cond": [{"$eq": ["$priority", True]}, 1, 0]}},
            "regular_count": {"$sum": {"$cond": [{"$eq": ["$priority", False]}, 1, 0]}},
            "student_count": {"$sum": {"$cond": [{"$eq": ["$role", "Student"]}, 1, 0]}},
            "guest_count": {"$sum": {"$cond": [{"$eq": ["$role", "Guest"]}, 1, 0]}},
            "by_section": {"$push": "$section"},
            "by_cashier": {"$push": "$reserved_by"},
            "hourly_distribution": {"$push": {"hour": {"$substr": ["$date", 11, 2]}, "count": 1}},
            "processing_times": {"$push": {"reserved_by": "$reserved_by", "start_time": "$date", "end_time": "$completed_at"}}
        }},
        {"$project": {
            "_id": 1,
            "total_transactions": 1,
            "completed": 1,
            "cut_off_cancelled": 1,
            "priority_count": 1,
            "regular_count": 1,
            "student_count": 1,
            "guest_count": 1,
            "by_section": {"$arrayToObject": {"$map": {"input": {"$setUnion": ["$by_section"]}, "as": "section", "in": {"k": "$$section", "v": {"$size": {"$filter": {"input": "$by_section", "as": "s", "cond": {"$eq": ["$$s", "$$section"]}}}}}}}},
            "by_cashier": {"$arrayToObject": {"$map": {"input": {"$setUnion": ["$by_cashier"]}, "as": "cashier", "in": {"k": "$$cashier", "v": {"$size": {"$filter": {"input": "$by_cashier", "as": "c", "cond": {"$eq": ["$$c", "$$cashier"]}}}}}}}},
            "hourly_distribution": {"$arrayToObject": {"$map": {"input": {"$setUnion": ["$hourly_distribution"]}, "as": "hour_data", "in": {"k": "$$hour_data.hour", "v": {"$size": {"$filter": {"input": "$hourly_distribution", "as": "h", "cond": {"$eq": ["$$h.hour", "$$hour_data.hour"]}}}}}}}},
            "processing_times": 1
        }}
    ]

# Function to run aggregation and update stats
def run_aggregation():
    today = datetime.now().strftime("%Y-%m-%d")
    start_date_str = f"{today} 00:00:00"
    end_date_str = f"{today} 23:59:59"

    # Check if today's stats already exist
    existing_stats = queue_stats.find_one({"_id.date": today})

    pipeline = get_daily_stats_pipeline(start_date_str, end_date_str)
    result = list(queue_records.aggregate(pipeline))

    if result:
        for doc in result:
            query = {"_id.date": doc["_id"]["date"]}
            # Exclude _id from the update to avoid immutable field error
            update_doc = {k: v for k, v in doc.items() if k != "_id"}
            queue_stats.update_one(query, {"$set": update_doc}, upsert=True)
        print(f"✅ Updated stats for {today}.")
    elif not existing_stats:
        # Create an empty stats document if none exists
        empty_doc = {
            "_id": {"date": today},
            "total_transactions": 0,
            "completed": 0,
            "cut_off_cancelled": 0,
            "priority_count": 0,
            "regular_count": 0,
            "student_count": 0,
            "guest_count": 0,
            "by_section": {},
            "by_cashier": {},
            "hourly_distribution": {},
            "processing_times": []
        }
        queue_stats.insert_one(empty_doc)
        print(f"🆕 Created empty stats for {today}.")
    else:
        print(f"⚠️ No new data found for {today}.")

# Main loop to run every 20 seconds
if __name__ == "__main__":
    try:
        while True:
            run_aggregation()
            time.sleep(20)
    except KeyboardInterrupt:
        print("\n🛑 Aggregator stopped by user.")
