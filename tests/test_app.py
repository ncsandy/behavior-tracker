import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from app import app, db, setup, Points, Reward, BehaviorLog, Redemption
from datetime import datetime, timedelta
from app import ordinal
import pytz

tz = pytz.timezone("America/New_York")

@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    with app.test_client() as client:
        with app.app_context():
            db.drop_all()
            db.create_all()
            setup()
        yield client

def test_ordinal():
    assert ordinal(1) == "1st"
    assert ordinal(2) == "2nd"
    assert ordinal(3) == "3rd"
    assert ordinal(4) == "4th"
    assert ordinal(11) == "11th"
    assert ordinal(12) == "12th"
    assert ordinal(13) == "13th"
    assert ordinal(21) == "21st"
    assert ordinal(22) == "22nd"
    assert ordinal(23) == "23rd"
    assert ordinal(24) == "24th"

def test_login_incorrect_pin(client):
    response = client.post("/login", data={"pin": "0000"}, follow_redirects=True)
    assert response.status_code == 200
    assert b"Incorrect PIN" in response.data

def test_login_page_loads(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert b"PIN" in response.data  # Or whatever keyword is in your login template

def test_login_logout(client):
    assert client.post("/login", data={"pin": "1234"}, follow_redirects=True).status_code == 200
    assert b"Made the bed" in client.get("/").data
    assert b"Login" in client.get("/logout", follow_redirects=True).data

def test_admin_login_and_manage_rewards(client):
    client.post("/admin", data={"pin": "9999"}, follow_redirects=True)
    assert b"Manage Rewards" in client.get("/rewards").data

def test_admin_login_incorrect_pin(client):
    response = client.post("/admin", data={"pin": "0000"}, follow_redirects=True)
    assert b"Incorrect admin PIN" in response.data

def test_admin_logout(client):
    # Log in as admin
    client.post("/admin", data={"pin": "9999"}, follow_redirects=True)
    # Ensure access to rewards works
    assert client.get("/rewards").status_code == 200

    # Logout
    response = client.get("/admin/logout", follow_redirects=True)
    assert b"Admin PIN" in response.data  # Should redirect to login page

    # Ensure access is denied after logout
    response = client.get("/rewards", follow_redirects=True)
    assert b"Admin PIN" in response.data  # Should require login again

def test_update_points_unauthenticated(client):
    response = client.post("/update_points", data={"new_total": 50}, follow_redirects=False)
    assert response.status_code == 302
    assert "/admin" in response.headers["Location"]

def test_update_points_invalid_value(client):
    client.post("/admin", data={"pin": "9999"}, follow_redirects=True)
    points = Points.query.first()
    points.total = 10
    db.session.commit()

    client.post("/update_points", data={"new_total": "invalid"})
    # Should default to 0
    assert Points.query.first().total == 0

def test_add_reward(client):
    client.post("/admin", data={"pin": "9999"}, follow_redirects=True)
    client.post("/add_reward", data={"name": "Test Reward", "cost": 15})
    assert b"Test Reward" in client.get("/rewards").data

def test_add_reward_requires_admin_authentication(client):
    # Try to add a reward without logging in as admin
    response = client.post("/add_reward", data={"name": "Fail Reward", "cost": 5}, follow_redirects=True)
    
    # Should redirect to admin login page
    assert b"Admin" in response.data or b"PIN" in response.data

def test_edit_reward(client):
    client.post("/admin", data={"pin": "9999"}, follow_redirects=True)
    db.session.add(Reward(name="Old", cost=10))
    db.session.commit()
    rid = Reward.query.filter_by(name="Old").first().id
    client.post(f"/edit_reward/{rid}", data={"name": "New", "cost": 20})
    assert b"New" in client.get("/rewards").data

def test_edit_reward_requires_admin_authentication(client):
    # First, add a reward using admin session
    with client.application.app_context():
        reward = Reward(name="EditTest", cost=10)
        db.session.add(reward)
        db.session.commit()
        reward_id = reward.id

    # Try to edit it without logging in as admin
    response = client.post(f"/edit_reward/{reward_id}", data={"name": "ShouldFail", "cost": 99}, follow_redirects=True)

    # Should redirect to admin login
    assert b"Admin" in response.data or b"PIN" in response.data

    # Confirm the reward was not changed
    with client.application.app_context():
        unchanged = db.session.get(Reward, reward_id)
        assert unchanged.name == "EditTest"
        assert unchanged.cost == 10

def test_delete_reward(client):
    client.post("/admin", data={"pin": "9999"}, follow_redirects=True)
    db.session.add(Reward(name="Trash", cost=5))
    db.session.commit()
    rid = Reward.query.filter_by(name="Trash").first().id
    client.post(f"/delete_reward/{rid}")
    assert b"Trash" not in client.get("/rewards").data

def test_delete_reward_requires_admin_authentication(client):
    # Add a reward to try deleting
    with client.application.app_context():
        reward = Reward(name="Should Not Delete", cost=1)
        db.session.add(reward)
        db.session.commit()
        rid = reward.id

    # Attempt to delete without logging in as admin
    response = client.post(f"/delete_reward/{rid}", follow_redirects=True)

    # Should redirect to admin login
    assert b"Admin" in response.data or b"PIN" in response.data  # Based on your admin_login.html
    # Check that reward still exists
    with client.application.app_context():
        assert db.session.get(Reward, rid) is not None

def test_update_points(client):
    client.post("/admin", data={"pin": "9999"}, follow_redirects=True)
    client.post("/update_points", data={"new_total": 42})
    assert Points.query.first().total == 42

def test_update_points_no_points_record(client):
    client.post("/admin", data={"pin": "9999"}, follow_redirects=True)
    points = Points.query.first()
    db.session.delete(points)
    db.session.commit()

    response = client.post("/update_points", data={"new_total": 25})
    # Should not raise error; gracefully skip commit
    assert response.status_code == 302

def test_behavior_log_entry(client):
    client.post("/login", data={"pin": "1234"}, follow_redirects=True)
    client.post("/", data={"action": "made_bed"})
    assert BehaviorLog.query.filter_by(task_key="made_bed").count() == 1

def test_index_authenticated_get(client):
    client.post("/login", data={"pin": "1234"}, follow_redirects=True)
    response = client.get("/")
    assert b"Made the bed" in response.data  # Expect task text on page

def test_index_redirects_if_not_authenticated(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 302  # Redirect status
    assert "/login" in response.headers["Location"]

def test_index_post_add_and_remove_task(client):
    client.post("/login", data={"pin": "1234"}, follow_redirects=True)

    # Add task
    client.post("/", data={"action": "made_bed"})
    assert BehaviorLog.query.filter_by(task_key="made_bed").count() == 1

    # Toggle off task (removes it)
    client.post("/", data={"action": "made_bed"})
    assert BehaviorLog.query.filter_by(task_key="made_bed").count() == 0

def test_index_post_bad_action(client):
    client.post("/login", data={"pin": "1234"}, follow_redirects=True)

    points = Points.query.first()
    points.total = 10
    db.session.commit()

    client.post("/", data={"action": "bad"})
    assert BehaviorLog.query.filter_by(entry_type="Needs improvement").count() == 1
    assert Points.query.first().total == 9

def test_index_post_redeem(client):
    client.post("/login", data={"pin": "1234"}, follow_redirects=True)

    reward = Reward.query.first()
    points = Points.query.first()
    points.total = reward.cost
    db.session.commit()

    client.post("/", data={"action": f"redeem:{reward.id}"})
    assert Redemption.query.filter_by(reward_id=reward.id).count() == 1
    assert Points.query.first().total == 0

def test_simulate_streak(client):
    client.post("/admin", data={"pin": "9999"}, follow_redirects=True)
    client.get("/debug/simulate_streak120/made_bed")
    assert BehaviorLog.query.filter_by(task_key="made_bed").count() >= 120
