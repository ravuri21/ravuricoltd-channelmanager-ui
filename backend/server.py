import os, threading, time, requests, traceback, smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from datetime import datetime
from flask import Flask, request, session, redirect, url_for, render_template, jsonify
from icalendar import Calendar
import stripe

from .models import init_db, SessionLocal, Unit, AvailabilityBlock, RatePlan
from . import import_properties as importer

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change_this_secret")

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "pradeep@ravuricoltd.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")
APP_LANG_DEFAULT = os.environ.get("APP_LANG_DEFAULT", "en")
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "sk_test_4eC39HqLyjWDarjtT1zdp7dc")

# ---------------- EMAIL ALERTS ----------------
def send_alert(subject, body):
    try:
        smtp_server = os.environ.get("SMTP_SERVER", "")
        smtp_port = int(os.environ.get("SMTP_PORT", 587))
        smtp_user = os.environ.get("SMTP_USER", "")
        smtp_pass = os.environ.get("SMTP_PASSWORD", "")
        alert_to = os.environ.get("ALERT_TO", "")

        if not all([smtp_server, smtp_user, smtp_pass, alert_to]):
            print("⚠️ Email not configured correctly, skipping alert")
            return

        msg = MIMEMultipart()
        msg["From"] = smtp_user
        msg["To"] = alert_to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        print(f"📧 Alert email sent to {alert_to}")
    except Exception as e:
        print("❌ Error sending alert:", e)
# ------------------------------------------------

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
        time.sleep(600)

# Bootstrap
try:
    print("Bootstrap: init_db()")
    init_db()
    csv_path = Path(__file__).with_name("ota_properties_prefilled.csv")
    if csv_path.exists():
        print(f"Bootstrap: importing CSV {csv_path}")
        importer.import_csv(str(csv_path))
    t = threading.Thread(target=periodic_sync, daemon=True)
    t.start()
except Exception as e:
    print("Bootstrap error:", e)
    traceback.print_exc()

@app.route("/")
def index():
    if "user" not in session:
        return redirect(url_for("login"))
    db = SessionLocal()
    units = db.query(Unit).all()
    db.close()
    return render_template("dashboard.html", units=units, lang=session.get("lang", APP_LANG_DEFAULT))

@app.route("/r")
def list_public_links():
    db = SessionLocal()
    rows = db.query(Unit).all()
    db.close()
    html = ["<h2>Public Links</h2><ul>"]
    for u in rows:
        html.append(f'<li><a href="/r/{u.id}" target="_blank">/r/{u.id}</a> — {u.ota} / {u.property_id}</li>')
    html.append("</ul>")
    return "".join(html)

@app.route("/r")
def list_public_links():
    db = SessionLocal()
    rows = db.query(Unit).all()
    db.close()
    html = ["<h2>Public Links</h2><ul>"]
    for u in rows:
        html.append(f'<li><a href="/r/{u.id}" target="_blank">/r/{u.id}</a> — {u.ota} / {u.property_id}</li>')
    html.append("</ul>")
    return "".join(html)

@app.route("/r")
def list_public_links():
    db = SessionLocal()
    rows = db.query(Unit).all()
    db.close()
    items = [
        f'<li><a href="/r/{u.id}">/r/{u.id}</a> — {u.ota} / {u.property_id}</li>'
        for u in rows
    ]
    return "<h2>Public links</h2><ul>" + "".join(items) + "</ul>"

@app.route("/r")
def list_public_links():
    db = SessionLocal()
    rows = db.query(Unit).all()
    db.close()
    links = [f'<li><a href="/r/{u.id}">/r/{u.id}</a> — {u.ota} / {u.property_id}</li>' for u in rows]
    return "<h2>Public links</h2><ul>" + "".join(links) + "</ul>"

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
        amount = int(float(data.get("amount",0))*100)
        currency = data.get("currency","thb")
        payment_method = data.get("payment_method_id")
        intent = stripe.PaymentIntent.create(
            amount=amount, currency=currency,
            payment_method=payment_method, confirm=True
        )
        return jsonify({"ok":True,"payment_intent":intent.id})
    except Exception as e:
        return jsonify({"error":str(e)}),400

@app.route("/api/check_ical", methods=["GET"])
def api_check_ical():
    if "user" not in session:
        return jsonify({"error":"unauthorized"}),401
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
            status = f"❌ Error: {str(e)[:50]}"
        results.append({"ota":u.ota,"property_id":u.property_id,"status":status})
    return jsonify(results)

@app.route("/api/unit/<int:unit_id>/ical", methods=["POST"])
def api_update_ical(unit_id):
    if "user" not in session:
        return jsonify({"error":"unauthorized"}),401
    new_url = (request.json or {}).get("ical_url","").strip()
    if not new_url.startswith("https://"):
        return jsonify({"error":"invalid url"}),400
    db = SessionLocal()
    u = db.query(Unit).filter(Unit.id==unit_id).first()
    if not u:
        db.close(); return jsonify({"error":"not found"}),404
    u.ical_url = new_url; db.commit(); db.close()
    return jsonify({"ok":True})

@app.route("/api/blocks", methods=["GET","POST","DELETE"])
def api_blocks():
    if "user" not in session:
        return jsonify({"error":"unauthorized"}),401
    db = SessionLocal()
    try:
        if request.method=="GET":
            unit_id=request.args.get("unit_id",type=int)
            q=db.query(AvailabilityBlock)
            if unit_id: q=q.filter(AvailabilityBlock.unit_id==unit_id)
            rows=q.order_by(AvailabilityBlock.start_date.desc()).all()
            return jsonify([{"id":b.id,"unit_id":b.unit_id,"start_date":b.start_date,"end_date":b.end_date,"source":b.source,"note":b.note} for b in rows])
        if request.method=="POST":
            data=request.json or {}
            b=AvailabilityBlock(
                unit_id=data.get("unit_id"),
                start_date=data.get("start_date"),
                end_date=data.get("end_date"),
                source=data.get("source","manual"),
                note=data.get("note","")
            )
            db.add(b); db.commit()
            send_alert("New Manual Block", f"Unit {b.unit_id}: {b.start_date}–{b.end_date} ({b.source}) {b.note}")
            return jsonify({"ok":True,"id":b.id})
        if request.method=="DELETE":
            bid=request.args.get("id",type=int)
            if not bid: return jsonify({"error":"id required"}),400
            b=db.query(AvailabilityBlock).filter(AvailabilityBlock.id==bid).first()
            if b: db.delete(b); db.commit()
            return jsonify({"ok":True})
    finally:
        db.close()

@app.route("/ical/export/<int:unit_id>.ics")
def ical_export(unit_id):
    db=SessionLocal()
    u=db.query(Unit).filter(Unit.id==unit_id).first()
    blocks=db.query(AvailabilityBlock).filter(AvailabilityBlock.unit_id==unit_id).all()
    db.close()
    if not u: return "Not found",404
    lines=["BEGIN:VCALENDAR","VERSION:2.0","PRODID:-//ravuricoltd//channel-manager//EN"]
    for b in blocks:
        lines+=["BEGIN:VEVENT",f"UID:cm-{unit_id}-{b.id}@ravuricoltd",
                 f"SUMMARY:{u.ota} {u.property_id} ({b.source})",
                 f"DTSTART;VALUE=DATE:{b.start_date.replace('-','')}",
                 f"DTEND;VALUE=DATE:{b.end_date.replace('-','')}",
                 "END:VEVENT"]
    lines.append("END:VCALENDAR")
    ics="\\r\\n".join(lines)
    return (ics,200,{"Content-Type":"text/calendar; charset=utf-8",
                     "Content-Disposition":f'attachment; filename="unit-{unit_id}.ics"'})

@app.route("/api/rates", methods=["POST"])
def api_rates():
    if "user" not in session:
        return jsonify({"error":"unauthorized"}),401
    data=request.json or {}
    unit_id=data.get("unit_id")
    base_rate=float(data.get("base_rate",0))
    currency=data.get("currency","THB")
    db=SessionLocal()
    rp=db.query(RatePlan).filter(RatePlan.unit_id==unit_id).first()
    if not rp:
        rp=RatePlan(unit_id=unit_id,base_rate=base_rate,currency=currency); db.add(rp)
    else:
        rp.base_rate=base_rate; rp.currency=currency
    db.commit(); db.close()
    return jsonify({"ok":True})

@app.route("/r/<int:unit_id>")
def room(unit_id):
    db = SessionLocal()
    u = db.query(Unit).filter(Unit.id == unit_id).first()
    db.close()
    if not u:
        return "Not found", 404
    return render_template("room.html", title=f"{u.ota} — {u.property_id}")

@app.route("/health")
def health():
    return "ok", 200
    
@app.route("/api/public/book/<int:unit_id>", methods=["POST"])
def public_book(unit_id):
    data=request.json or {}
    start=data.get("start_date"); end=data.get("end_date"); name=data.get("name",""); email=data.get("email","")
    if not (start and end and name and email): return jsonify({"error":"missing fields"}),400
    db=SessionLocal()
    b=AvailabilityBlock(unit_id=unit_id,start_date=start,end_date=end,source="direct",note=f"Guest: {name} {email}")
    db.add(b); db.commit(); db.close()
    send_alert("New Direct Booking", f"Unit {unit_id}: {start}–{end} Guest: {name} ({email})")
    return jsonify({"ok":True,"id":b.id})
