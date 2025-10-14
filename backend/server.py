import os, threading, time, requests, traceback
from pathlib import Path
from datetime import datetime
from flask import Flask, request, session, redirect, url_for, render_template, jsonify
from icalendar import Calendar
import stripe

from .models import init_db, SessionLocal, Unit
from . import import_properties as importer  # package-relative

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change_this_secret")

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")
APP_LANG_DEFAULT = os.environ.get("APP_LANG_DEFAULT", "en")
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "sk_test_4eC39HqLyjWDarjtT1zdp7dc")

def fetch_ical(ical_url):
    try:
        resp = requests.get(ical_url, timeout=12)
        resp.raise_for_status()
        cal = Calendar.from_ical(resp.text)
        events = []
        for comp in cal.walk("VEVENT"):
            try:
                start = comp.get("dtstart").dt
                end = comp.get("dtend").dt
                uid = str(comp.get("uid"))
                events.append({"uid": uid, "start": str(start), "end": str(end)})
            except Exception:
                continue
        return events
    except Exception as e:
        print("iCal fetch error:", e)
        return []

def periodic_sync():
    while True:
        try:
            db = SessionLocal()
            units = db.query(Unit).all()
            for u in units:
                if u.ical_url:
                    events = fetch_ical(u.ical_url)
                    print(f"[{datetime.now()}] {u.ota} {u.property_id}: {len(events)} events")
            db.close()
        except Exception as e:
            print("sync error:", e)
            traceback.print_exc()
        time.sleep(120)

# ---- Bootstrap when module is imported by Gunicorn ----
try:
    print("Bootstrap: init_db()")
    init_db()
    csv_path = Path(__file__).with_name("ota_properties_prefilled.csv")
    if csv_path.exists():
        print(f"Bootstrap: importing CSV {csv_path}")
        importer.import_csv(str(csv_path))
    else:
        print(f"Bootstrap: CSV not found (skipping) {csv_path}")
    # Start background sync thread (single worker on free plan)
    t = threading.Thread(target=periodic_sync, daemon=True)
    t.start()
except Exception as e:
    print("Bootstrap error:", e)
    traceback.print_exc()

@app.route("/")
def index():
    if "user" not in session:
        return redirect(url_for("login"))
    lang = session.get("lang", APP_LANG_DEFAULT)
    db = SessionLocal()
    units = db.query(Unit).all()
    db.close()
    return render_template("dashboard.html", units=units, lang=lang)

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email","").strip().lower()
        password = request.form.get("password","")
        if email == ADMIN_EMAIL.lower() and password == ADMIN_PASSWORD:
            session["user"] = email
            return redirect(url_for("index"))
        return render_template("login.html", error="Invalid credentials")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/lang/<code>")
def lang(code):
    if "user" not in session:
        return redirect(url_for("login"))
    if code in ("en","th"):
        session["lang"] = code
    return redirect(url_for("index"))

@app.route("/api/booking", methods=["POST"])
def api_booking():
    if "user" not in session:
        return jsonify({"error":"unauthorized"}),401
    data = request.json or {}
    try:
        amount = int(float(data.get("amount", 0))*100)
        currency = data.get("currency","usd")
        payment_method = data.get("payment_method_id")
        intent = stripe.PaymentIntent.create(
            amount=amount, currency=currency,
            payment_method=payment_method, confirm=True
        )
        return jsonify({"ok":True, "payment_intent": intent.id})
    except Exception as e:
        return jsonify({"error": str(e)}), 400
        @app.route("/api/check_ical", methods=["GET"])
def api_check_ical():
    if "user" not in session:
        return jsonify({"error": "unauthorized"}), 401

    db = SessionLocal()
    units = db.query(Unit).all()
    db.close()

    results = []
    for u in units:
        try:
            r = requests.get(u.ical_url, timeout=10)
            if r.status_code == 200 and "BEGIN:VCALENDAR" in r.text:
                status = "✅ OK"
            else:
                status = f"⚠️ Unexpected ({r.status_code})"
        except Exception as e:
            status = f"❌ Error: {str(e)[:40]}"
        results.append({
            "ota": u.ota,
            "property_id": u.property_id,
            "status": status
        })
    return jsonify(results)
