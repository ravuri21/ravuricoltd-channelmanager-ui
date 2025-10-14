import os, threading, time, requests
from datetime import datetime
from flask import Flask, request, session, redirect, url_for, render_template, jsonify
from icalendar import Calendar
import stripe
from models import init_db, SessionLocal, Unit

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
        time.sleep(120)

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

if __name__ == "__main__":
    from pathlib import Path

    init_db()

    # One-time safe bootstrap import of your CSV (skips duplicates and won't crash on error)
    try:
        from import_properties import import_csv
        csv_path = Path(__file__).with_name("ota_properties_prefilled.csv")
        if csv_path.exists():
            import_csv(str(csv_path))
            print("Bootstrap CSV import done:", csv_path)
        else:
            print("Bootstrap CSV import skipped (file not found):", csv_path)
    except Exception as e:
        print("Bootstrap CSV import error (continuing without it):", e)

    t = threading.Thread(target=periodic_sync, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=5000, debug=False)
