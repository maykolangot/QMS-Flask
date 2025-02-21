from flask import Blueprint, render_template, session, redirect, url_for
from pymongo import MongoClient
import matplotlib.pyplot as plt
import io, base64
import pandas as pd
from datetime import datetime, timedelta
from statsmodels.tsa.arima.model import ARIMA

# Create Blueprint for superadmin
stats_bp = Blueprint("stats", __name__, url_prefix="/stats")

# Connect to MongoDB
client = MongoClient("mongodb://localhost:27017/")
db = client["QueueSystem"]
queue_stats = db["CashierQueueStats"]


def fetch_latest_data():
    """Fetch the latest queue statistics from MongoDB."""
    return queue_stats.find_one(sort=[("_id", -1)])  # Get the latest document


def fetch_past_30_days():
    """Fetch queue stats for the past 30 days for trend analysis."""
    today = datetime.now().strftime("%Y-%m-%d")
    past_30_days = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    cursor = queue_stats.find({"_id.date": {"$gte": past_30_days, "$lte": today}})
    return list(cursor)


def generate_trend_chart(data):
    """Generate a smaller trend line chart."""
    if not data:
        return None

    df = pd.DataFrame(data)
    df["_id"] = pd.to_datetime(df["_id"].apply(lambda x: x["date"]))
    df.set_index("_id", inplace=True)
    df = df.sort_index()

    # Fill NaN values with 0
    df["total_transactions"] = df["total_transactions"].fillna(0)

    if df["total_transactions"].sum() == 0:
        return None  # No data to plot

    model = ARIMA(df["total_transactions"], order=(5, 1, 0))
    model_fit = model.fit()
    forecast = model_fit.forecast(steps=7)

    plt.figure(figsize=(4, 3))
    plt.plot(df.index, df["total_transactions"], marker="o", label="Past 30 Days")
    plt.plot(pd.date_range(start=df.index[-1], periods=8, freq="D")[1:], forecast, linestyle="dashed",
             label="Forecast (Next 7 Days)")
    plt.xlabel("Date", fontsize=8)
    plt.ylabel("Transactions", fontsize=8)
    plt.title("Trends", fontsize=10)
    plt.legend(fontsize=6)
    plt.xticks(fontsize=6, rotation=45)
    plt.yticks(fontsize=6)

    img = io.BytesIO()
    plt.savefig(img, format="png", bbox_inches="tight")
    img.seek(0)
    return base64.b64encode(img.getvalue()).decode()


def generate_pie_chart(data):
    """Generate a smaller pie chart for transaction status."""
    labels = ["Completed", "Cut Off/Cancelled"]
    values = [data.get("completed", 0), data.get("cut_off_cancelled", 0)]

    # Handle empty data
    if sum(values) == 0:
        # Display "No data yet" instead of an empty chart
        fig, ax = plt.subplots(figsize=(4, 3))
        ax.text(0.5, 0.5, "No data yet", fontsize=12, ha='center', va='center')
        ax.axis('off')
    else:
        fig, ax = plt.subplots(figsize=(4, 3))
        ax.pie(values, labels=labels, autopct="%1.1f%%", colors=["green", "red"], textprops={'fontsize': 8})
        ax.set_title("Transaction Breakdown", fontsize=10)

    img = io.BytesIO()
    plt.savefig(img, format="png", bbox_inches="tight")
    img.seek(0)
    return base64.b64encode(img.getvalue()).decode()



def generate_hourly_distribution_chart(data):
    """Generate a smaller bar chart for peak hours."""
    hourly_data = data.get("hourly_distribution", {})

    if not hourly_data:
        return None

    hours = list(hourly_data.keys())
    counts = [hourly_data.get(hour, 0) for hour in hours]

    # Fill NaN values with 0
    counts = [0 if pd.isna(c) else c for c in counts]

    plt.figure(figsize=(4, 3))
    plt.bar(hours, counts, color="blue")
    plt.xlabel("Hour", fontsize=8)
    plt.ylabel("Transactions", fontsize=8)
    plt.title("Peak Hours", fontsize=10)
    plt.xticks(fontsize=6)
    plt.yticks(fontsize=6)

    img = io.BytesIO()
    plt.savefig(img, format="png", bbox_inches="tight")
    img.seek(0)
    return base64.b64encode(img.getvalue()).decode()


@stats_bp.route("/")
def stats():
    if 'username' not in session or session['role'] != 'superadmin':
        return redirect(url_for('login'))

    data = fetch_latest_data() or {}  # Ensure data is always a dictionary
    past_data = fetch_past_30_days()

    if not data:
        return "<h1>No data available</h1>"

    trend_chart = generate_trend_chart(past_data) if past_data else None
    pie_chart = generate_pie_chart(data) if data else None
    hourly_chart = generate_hourly_distribution_chart(data) if data else None

    return render_template(
        "superadmin/stats.html",
        data=data,
        trend_chart=trend_chart,
        pie_chart=pie_chart,
        hourly_chart=hourly_chart
    )
