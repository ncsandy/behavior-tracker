from collections import defaultdict
from flask import Flask, render_template, request, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import pytz

tz = pytz.timezone("America/New_York")

app = Flask(__name__)
app.secret_key = "your-secure-secret-key"
app.permanent_session_lifetime = timedelta(hours=6)

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///./behavior.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

def ordinal(n):
    if 11 <= n % 100 <= 13:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return f"{n}{suffix}"

app.jinja_env.filters['ordinal'] = ordinal

# Models
class BehaviorLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(tz))
    entry_type = db.Column(db.String(50))
    task_key = db.Column(db.String(50))

class Points(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    total = db.Column(db.Integer, default=0)

class Reward(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    cost = db.Column(db.Integer)

class Redemption(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reward_id = db.Column(db.Integer, db.ForeignKey('reward.id'))
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(tz))
    reward = db.relationship("Reward")

# Setup
def setup():
    with app.app_context():
        db.create_all()
        if Points.query.first() is None:
            db.session.add(Points(total=0))
        if Reward.query.count() == 0:
            db.session.add_all([
                Reward(name="1 Extra Hour of Screen Time", cost=20),
                Reward(name="Dessert", cost=25),
                Reward(name="Outdoor time", cost=10),
                Reward(name="New toy", cost=100),
                Reward(name="New book", cost=70),
            ])
        db.session.commit()

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        pin = request.form.get("pin")
        if pin == "1234":
            session["authenticated"] = True
            return redirect(url_for("index"))
        else:
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
        if pin == "9999":
            session["admin_authenticated"] = True
            return redirect(url_for("manage_rewards"))
        else:
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
    rewards = Reward.query.order_by(Reward.id).all()
    points = Points.query.first()
    return render_template("rewards.html", rewards=rewards, current_points=points.total if points else 0)

@app.route("/update_points", methods=["POST"])
def update_points():
    if not session.get("admin_authenticated"):
        return redirect(url_for("admin_login"))

    try:
        new_total = int(request.form.get("new_total", 0))
    except ValueError:
        new_total = 0

    points = Points.query.first()
    if points:
        points.total = max(0, new_total)
        db.session.commit()

    return redirect(url_for("manage_rewards"))

@app.route("/add_reward", methods=["POST"])
def add_reward():
    if not session.get("admin_authenticated"):
        return redirect(url_for("admin_login"))
    name = request.form.get("name")
    cost = request.form.get("cost", type=int)
    if name and cost:
        db.session.add(Reward(name=name, cost=cost))
        db.session.commit()
    return redirect(url_for("manage_rewards"))

@app.route("/edit_reward/<int:reward_id>", methods=["POST"])
def edit_reward(reward_id):
    if not session.get("admin_authenticated"):
        return redirect(url_for("admin_login"))
    reward = db.session.get(Reward, reward_id)
    if reward:
        reward.name = request.form.get("name")
        reward.cost = request.form.get("cost", type=int)
        db.session.commit()
    return redirect(url_for("manage_rewards"))

@app.route("/delete_reward/<int:reward_id>", methods=["POST"])
def delete_reward(reward_id):
    if not session.get("admin_authenticated"):
        return redirect(url_for("admin_login"))
    reward = db.session.get(Reward, reward_id)
    if reward:
        db.session.delete(reward)
        db.session.commit()
    return redirect(url_for("manage_rewards"))

@app.route("/", methods=["GET", "POST"])
def index():
    if not session.get("authenticated"):
        return redirect(url_for("login"))

    points = Points.query.first()
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

    today_logs = BehaviorLog.query.filter(
        BehaviorLog.timestamp >= today_start,
        BehaviorLog.timestamp < today_start + timedelta(days=1)
    ).all()
    completed_today = {log.task_key for log in today_logs if log.task_key}

    if request.method == "POST":
        action = request.form.get("action")
        if action in valid_actions:
            existing_log = BehaviorLog.query.filter(
                BehaviorLog.task_key == action,
                BehaviorLog.timestamp >= today_start,
                BehaviorLog.timestamp < today_start + timedelta(days=1)
            ).first()
            if existing_log:
                db.session.delete(existing_log)
                points.total = max(0, points.total - 1)
            else:
                db.session.add(BehaviorLog(entry_type=valid_actions[action], task_key=action))
                points.total += 1
        elif action == "bad":
            db.session.add(BehaviorLog(entry_type="Needs improvement"))
            points.total = max(0, points.total - 1)
        elif action.startswith("redeem:"):
            reward_id = int(action.split(":")[1])
            reward = db.session.get(Reward, reward_id)
            if reward and points.total >= reward.cost:
                points.total -= reward.cost
                db.session.add(Redemption(reward=reward))
        db.session.commit()
        return redirect(url_for("index"))

    logs = BehaviorLog.query.order_by(BehaviorLog.timestamp.desc()).all()
    rewards = Reward.query.all()
    redemptions = Redemption.query.order_by(Redemption.timestamp.desc()).all()

    one_year_ago = today - timedelta(days=364)
    logs_last_year = BehaviorLog.query.filter(
        BehaviorLog.timestamp >= tz.localize(datetime(one_year_ago.year, one_year_ago.month, one_year_ago.day))
    ).all()

    daily_task_map = defaultdict(set)
    for log in logs_last_year:
        local_date = log.timestamp.astimezone(tz).strftime('%Y-%m-%d')
        if log.task_key:
            daily_task_map[local_date].add(log.task_key)

    history = {}
    for i in range(365):
        date = today - timedelta(days=i)
        date_str = date.strftime('%Y-%m-%d')
        history[date_str] = daily_task_map.get(date_str, set())

    task_streaks = {}
    for key in valid_actions.keys():
        streak = 0
        for i in range(365):
            day = (today - timedelta(days=i)).strftime('%Y-%m-%d')
            if key in history.get(day, set()):
                streak += 1
            else:
                break
        task_streaks[key] = streak

    return render_template(
        "index.html",
        logs=logs,
        points=points.total,
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

@app.route("/debug/simulate_streak120/<task_key>")
def simulate_streak_120(task_key):
    if not session.get("admin_authenticated"):
        return redirect(url_for("admin_login"))

    valid_tasks = {
        "made_bed", "brushed_teeth", "listened",
        "clean_up", "stay_in_bed", "use_manners", "clean_toys"
    }
    if task_key not in valid_tasks:
        return f"Invalid task key: {task_key}", 400

    now = datetime.now(tz)
    for i in range(120):
        day = now - timedelta(days=i)
        start = tz.localize(datetime(day.year, day.month, day.day))
        end = start + timedelta(days=1)

        already_logged = BehaviorLog.query.filter(
            BehaviorLog.task_key == task_key,
            BehaviorLog.timestamp >= start,
            BehaviorLog.timestamp < end
        ).first()

        if not already_logged:
            db.session.add(BehaviorLog(
                timestamp=start + timedelta(hours=9),
                entry_type=f"Simulated {task_key} (day {i+1})",
                task_key=task_key
            ))

    db.session.commit()
    return f"Simulated 120-day streak for task '{task_key}'.", 200

if __name__ == "__main__":
    setup()
    app.run(host="0.0.0.0", port=5000, debug=True)