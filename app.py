from collections import defaultdict
from flask import Flask, render_template, request, redirect, url_for, session
from datetime import datetime, timedelta
import pytz
import firebase_admin
from firebase_admin import credentials, firestore, initialize_app
from werkzeug.security import generate_password_hash, check_password_hash
import json
import os


tz = pytz.timezone("America/New_York")

app = Flask(__name__)
app.secret_key = "your-secure-secret-key"
app.permanent_session_lifetime = timedelta(hours=6)

# Firebase setup
firebase_key_json = os.environ.get("FIREBASE_KEY_JSON")
if not firebase_key_json:
    raise RuntimeError("FIREBASE_KEY_JSON is not set")

cred = credentials.Certificate(json.loads(firebase_key_json))
firebase_admin.initialize_app(cred)
fs = firestore.client()

def ordinal(n):
    if 11 <= n % 100 <= 13:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return f"{n}{suffix}"

app.jinja_env.filters['ordinal'] = ordinal

# Models

fs.collection("points").document("singleton").set({"total": 0})

fs.collection("redemptions").add({
    "timestamp": datetime.now(tz),
    "reward": {
        "id": "abc123",
        "name": "New Toy",
        "cost": 100
    }
})

# Setup
def setup():
    # Initialize points document if it doesn't exist
    points_ref = fs.collection("points").document("singleton")
    if not points_ref.get().exists:
        points_ref.set({"total": 0})

    # Initialize rewards if collection is empty
    if not list(fs.collection("rewards").limit(1).stream()):
        default_rewards = [
            {"name": "1 Extra Hour of Screen Time", "cost": 20},
            {"name": "Dessert", "cost": 25},
            {"name": "Outdoor time", "cost": 10},
            {"name": "New toy", "cost": 100},
            {"name": "New book", "cost": 70},
        ]
        for reward in default_rewards:
            fs.collection("rewards").add(reward)

    # Initialize admin password
    admin_ref = fs.collection("auth").document("admin")
    if not admin_ref.get().exists:
        hashed_admin_pin = generate_password_hash("9999")
        admin_ref.set({"password": hashed_admin_pin})
    # Initialize user password if not already set
    auth_ref = fs.collection("auth").document("user")
    if not auth_ref.get().exists:
        hashed_password = generate_password_hash("1234")
        auth_ref.set({"password": hashed_password})


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        pin = request.form.get("pin")
        user_doc = fs.collection("auth").document("user").get()

        if user_doc.exists:
            stored_hash = user_doc.to_dict().get("password")
            if stored_hash and check_password_hash(stored_hash, pin):
                session["authenticated"] = True
                return redirect(url_for("index"))

        return render_template("login.html", error="Incorrect PIN")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        pin = request.form.get("pin")
        user_doc = fs.collection("auth").document("admin").get()

        if user_doc.exists:
            stored_hash = user_doc.to_dict().get("password")
            if stored_hash and check_password_hash(stored_hash, pin):
                session["admin_authenticated"] = True
                return redirect(url_for("manage_rewards"))

        return render_template("admin_login.html", error="Incorrect admin PIN")

    return render_template("admin_login.html")

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_authenticated", None)
    return redirect(url_for("admin_login"))

@app.route("/rewards", methods=["GET", "POST"])
def manage_rewards():
    if not session.get("admin_authenticated"):
        return redirect(url_for("admin_login"))

    # Get all rewards, ordered by name (since there's no numeric ID to sort on)
    rewards_query = fs.collection("rewards").stream()
    rewards = sorted(
        [doc.to_dict() | {"id": doc.id} for doc in rewards_query],
        key=lambda r: r["name"].lower()
    )

    # Get current points
    points_doc = fs.collection("points").document("singleton").get()
    current_points = points_doc.to_dict().get("total", 0) if points_doc.exists else 0

    return render_template("rewards.html", rewards=rewards, current_points=current_points)


@app.route("/update_points", methods=["POST"])
def update_points():
    if not session.get("admin_authenticated"):
        return redirect(url_for("admin_login"))

    try:
        new_total = int(request.form.get("new_total", 0))
    except ValueError:
        new_total = 0

    new_total = max(0, new_total)  # Prevent negative values

    # Update Firestore points document
    fs.collection("points").document("singleton").set({
        "total": new_total
    }, merge=True)

    return redirect(url_for("manage_rewards"))

@app.route("/add_reward", methods=["POST"])
def add_reward():
    if not session.get("admin_authenticated"):
        return redirect(url_for("admin_login"))

    name = request.form.get("name")
    cost = request.form.get("cost", type=int)

    if name and cost is not None:
        fs.collection("rewards").add({
            "name": name,
            "cost": cost
        })

    return redirect(url_for("manage_rewards"))


@app.route("/edit_reward/<reward_id>", methods=["POST"])
def edit_reward(reward_id):
    if not session.get("admin_authenticated"):
        return redirect(url_for("admin_login"))

    name = request.form.get("name")
    cost = request.form.get("cost", type=int)

    if name and cost is not None:
        fs.collection("rewards").document(reward_id).update({
            "name": name,
            "cost": cost
        })

    return redirect(url_for("manage_rewards"))

@app.route("/delete_reward/<reward_id>", methods=["POST"])
def delete_reward(reward_id):
    if not session.get("admin_authenticated"):
        return redirect(url_for("admin_login"))

    fs.collection("rewards").document(reward_id).delete()

    return redirect(url_for("manage_rewards"))

@app.route("/", methods=["GET", "POST"])
def index():
    if not session.get("authenticated"):
        return redirect(url_for("login"))

    valid_actions = {
        "made_bed": "Made the bed",
        "brushed_teeth": "Brushed teeth",
        "listened": "Listened well",
        "clean_up": "Cleaned up",
        "stay_in_bed": "Stayed in bed all night",
        "use_manners": "Used manners: Say please and thank you",
        "clean_toys": "Cleaned up toys"
    }

    now_local = datetime.now(tz)
    today = now_local.date()
    today_start = tz.localize(datetime(today.year, today.month, today.day))
    today_end = today_start + timedelta(days=1)

    # Fetch all today's logs
    logs_query = fs.collection("behavior_logs") \
        .where("timestamp", ">=", today_start) \
        .where("timestamp", "<", today_end) \
        .stream()
    today_logs = [doc.to_dict() | {"id": doc.id} for doc in logs_query]
    completed_today = {log.get("task_key") for log in today_logs if log.get("task_key")}

    # Fetch current points
    points_doc = fs.collection("points").document("singleton").get()
    points = points_doc.to_dict() if points_doc.exists else {"total": 0}

    if request.method == "POST":
        action = request.form.get("action")

        if action in valid_actions:
            existing_logs = fs.collection("behavior_logs") \
                .where("task_key", "==", action) \
                .where("timestamp", ">=", today_start) \
                .where("timestamp", "<", today_end) \
                .stream()

            for existing_log in existing_logs:
                fs.collection("behavior_logs").document(existing_log.id).delete()
                points["total"] = max(0, points["total"] - 1)
                break

            else:
                fs.collection("behavior_logs").add({
                    "timestamp": datetime.now(tz),
                    "entry_type": valid_actions[action],
                    "task_key": action
                })
                points["total"] += 1

        elif action == "bad":
            fs.collection("behavior_logs").add({
                "timestamp": datetime.now(tz),
                "entry_type": "Needs improvement"
            })
            points["total"] = max(0, points["total"] - 1)

        elif action.startswith("redeem:"):
            reward_id = action.split(":")[1]
            reward_doc = fs.collection("rewards").document(reward_id).get()
            reward = reward_doc.to_dict()
            if reward and points["total"] >= reward["cost"]:
                points["total"] -= reward["cost"]
                fs.collection("redemptions").add({
                    "timestamp": datetime.now(tz),
                    "reward_id": reward_id,
                    "reward_name": reward["name"]
                })

        fs.collection("points").document("singleton").set(points)
        return redirect(url_for("index"))

    # Fetch logs, rewards, redemptions
    logs = [doc.to_dict() for doc in fs.collection("behavior_logs").order_by("timestamp", direction=firestore.Query.DESCENDING).stream()]
    rewards = [{**doc.to_dict(), "id": doc.id} for doc in fs.collection("rewards").stream()]
    redemptions = []
    redemption_docs = fs.collection("redemptions").order_by("timestamp", direction=firestore.Query.DESCENDING).stream()

    for doc in redemption_docs:
        data = doc.to_dict()
        reward_id = data.get("reward_id")
        reward_doc = fs.collection("rewards").document(str(reward_id)).get()
        reward_data = reward_doc.to_dict() if reward_doc.exists else {}
        data["reward_name"] = reward_data.get("name", "Unknown Reward")
        redemptions.append(data)

    # History and streaks
    one_year_ago = today - timedelta(days=364)
    year_logs = fs.collection("behavior_logs") \
        .where("timestamp", ">=", tz.localize(datetime(one_year_ago.year, one_year_ago.month, one_year_ago.day))) \
        .stream()
    
    daily_task_map = defaultdict(set)
    for log_doc in year_logs:
        log = log_doc.to_dict()
        if log.get("task_key"):
            date_str = log["timestamp"].astimezone(tz).strftime('%Y-%m-%d')
            daily_task_map[date_str].add(log["task_key"])

    history = {}
    for i in range(365):
        date = today - timedelta(days=i)
        date_str = date.strftime('%Y-%m-%d')
        history[date_str] = daily_task_map.get(date_str, set())

    task_streaks = {}
    for key in valid_actions.keys():
        streak = 0
        for i in range(365):
            date_str = (today - timedelta(days=i)).strftime('%Y-%m-%d')
            if key in history.get(date_str, set()):
                streak += 1
            else:
                break
        task_streaks[key] = streak

    return render_template(
        "index.html",
        logs=logs,
        points=points["total"],
        rewards=rewards,
        redemptions=redemptions,
        tasks=valid_actions,
        completed_today=completed_today,
        now=now_local,
        history=history,
        task_keys=list(valid_actions.keys()),
        task_labels=valid_actions,
        task_streaks=task_streaks
    )

if __name__ == "__main__":
    setup()
    app.run(host="0.0.0.0", port=5500, debug=True)