# backend/server.py
import os, threading, time, requests, traceback, smtplib, json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from datetime import datetime, date, timedelta

from flask import (
    Flask, request, session, redirect, url_for,
    render_template, jsonify
)
from jinja2 import TemplateNotFound
from icalendar import Calendar as ICal
import stripe

# ====== Absolute imports (run with --chdir backend) ======
from models import init_db, SessionLocal, Unit, AvailabilityBlock, RatePlan
import import_properties as importer

# ====== App & Config ======
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change_this_secret")

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")
APP_LANG_DEFAULT = os.environ.get("APP_LANG_DEFAULT", "en")

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")

# Run background sync thread only once
SINGLE_WORKER = os.getenv("WEB_CONCURRENCY", "1") == "1"

# ====== Email alerts (optional) ======
def send_alert(subject, body):
    try:
        smtp_server = os.environ.get("SMTP_SERVER", "")
        smtp_port = int(os.environ.get("SMTP_PORT", 587))
        smtp_user = os.environ.get("SMTP_USER", "")
        smtp_pass = os.environ.get("SMTP_PASSWORD", "")
        alert_to = os.environ.get("ALERT_TO", "")

        if not all([smtp_server, smtp_user, smtp_pass, alert_to]):
            print("⚠️ Email not configured; skipping alert")
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

# ====== Helpers ======
def _load_meta():
    try:
        meta_path = Path(__file__).with_name("unit_meta.json")
        if meta_path.exists():
            with open(meta_path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print("unit_meta load error:", e)
    return {"groups": {}}

def _group_info(slug):
    return _load_meta().get("groups", {}).get(slug)

def _parse_yyyy_mm_dd(s):
    y, m, d = s.split("-")
    return date(int(y), int(m), int(d))

def _as_date_str(dval) -> str:
    if isinstance(dval, datetime):
        return dval.date().isoformat()
    return dval.isoformat()

def _overlaps(db, unit_id: int, start: str, end: str) -> bool:
    q = db.query(AvailabilityBlock).filter(
        AvailabilityBlock.unit_id == unit_id,
        ~(
            (AvailabilityBlock.end_date <= start) |
            (AvailabilityBlock.start_date >= end)
        )
    )
    return db.query(q.exists()).scalar()

def fetch_ical(ical_url):
    try:
        resp = requests.get(ical_url, timeout=12)
        resp.raise_for_status()
        cal = ICal.from_ical(resp.content)
        events = []
        for comp in cal.walk("VEVENT"):
            try:
                start = comp.get("dtstart").dt
                end = comp.get("dtend").dt
                events.append({"start": _as_date_str(start), "end": _as_date_str(end)})
            except Exception:
                continue
        return events
    except Exception as e:
        print("iCal fetch error:", e)
        return []

# ====== Background iCal sync → write to DB ======
def periodic_sync():
    while True:
        try:
            db = SessionLocal()
            units = db.query(Unit).all()
            for u in units:
                if not u.ical_url:
                    continue
                try:
                    r = requests.get(u.ical_url, timeout=15)
                    r.raise_for_status()
                    cal = ICal.from_ical(r.content)

                    db.query(AvailabilityBlock).filter(
                        AvailabilityBlock.unit_id == u.id,
                        AvailabilityBlock.source == (u.ota or "").lower()
                    ).delete()

                    inserted = 0
                    for comp in cal.walk('VEVENT'):
                        try:
                            s = comp.get('dtstart').dt
                            e = comp.get('dtend').dt
                            s_str = _as_date_str(s)
                            e_str = _as_date_str(e)
                            if e_str <= s_str:
                                continue
                            db.add(AvailabilityBlock(
                                unit_id=u.id,
                                start_date=s_str,
                                end_date=e_str,
                                source=(u.ota or "").lower(),
                                note=str(comp.get('summary', ""))[:120]
                            ))
                            inserted += 1
                        except Exception:
                            continue

                    db.commit()
                    print(f"[{datetime.now()}] {u.ota} {u.property_id}: {inserted} events mirrored")
                except Exception as e:
                    db.rollback()
                    print(f"[SYNC ERROR] {u.ota} {u.property_id}:", e)
            db.close()
        except Exception as e:
            print("sync loop error:", e)
            traceback.print_exc()
        time.sleep(600)

# ====== Bootstrap ======
try:
    print("Bootstrap: init_db()")
    init_db()

    # Auto-seed ONCE if DB is empty (safe; won't override existing data)
    try:
        db = SessionLocal()
        count_units = db.query(Unit).count()
        db.close()
        if count_units == 0:
            csv_path = Path(__file__).with_name("ota_properties_prefilled.csv")
            if csv_path.exists():
                print(f"Seeding units from CSV: {csv_path}")
                importer.import_csv(str(csv_path))
            else:
                print("⚠️ CSV not found for seeding:", csv_path)
    except Exception as e:
        print("Seeding check failed:", e)

    if SINGLE_WORKER:
        print("Starting periodic_sync thread (single worker)")
        threading.Thread(target=periodic_sync, daemon=True).start()
    else:
        print("Skipping periodic_sync thread (multiple workers)")
except Exception as e:
    print("Bootstrap error:", e)
    traceback.print_exc()

# ====== Auth & Basic ======
@app.route("/")
def index():
    if "user" not in session:
        return redirect(url_for("login"))
    db = SessionLocal()
    try:
        units = db.query(Unit).all()
        rates = db.query(RatePlan).all()
        # Build maps for quick lookup in the template
        rates_map = {r.unit_id: r.base_rate for r in rates}
        currency_map = {r.unit_id: (r.currency or "THB") for r in rates}
    finally:
        db.close()
    return render_template(
        "dashboard.html",
        units=units,
        rates_map=rates_map,
        currency_map=currency_map,
        lang=session.get("lang", APP_LANG_DEFAULT)
    )

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email","").strip().lower()
        password = request.form.get("password","")
        if email == ADMIN_EMAIL.lower() and password == ADMIN_PASSWORD:
            session["user"] = email
            return redirect(url_for("index"))
        try:
            return render_template("login.html", error="Invalid credentials")
        except TemplateNotFound:
            return "<h3>Login</h3><form method='post'><input name='email' placeholder='Email'><br><input type='password' name='password' placeholder='Password'><br><button>Login</button></form>"
    try:
        return render_template("login.html")
    except TemplateNotFound:
        return "<h3>Login</h3><form method='post'><input name='email' placeholder='Email'><br><input type='password' name='password' placeholder='Password'><br><button>Login</button></form>"

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

@app.route("/health")
def health():
    return "ok", 200

# ====== Admin APIs ======
@app.route("/api/unit/<int:unit_id>/ical", methods=["POST"])
def api_update_ical(unit_id):
    if "user" not in session:
        return jsonify({"error":"unauthorized"}),401
    new_url = (request.json or {}).get("ical_url","").strip()
    if not new_url.startswith("http"):
        return jsonify({"error":"invalid url"}),400
    db = SessionLocal()
    u = db.query(Unit).filter(Unit.id==unit_id).first()
    if not u:
        db.close(); return jsonify({"error":"not found"}),404
    u.ical_url = new_url; db.commit(); db.close()
    return jsonify({"ok":True})

@app.route("/api/check_ical")
def api_check_ical():
    if "user" not in session:
        return jsonify({"error":"unauthorized"}),401
    db = SessionLocal()
    units = db.query(Unit).all()
    db.close()
    results = []
    for u in units:
        if not u.ical_url:
            results.append({"ota":u.ota,"property_id":u.property_id,"status":"(empty — add later)"})
            continue
        try:
            r = requests.get(u.ical_url, timeout=12)
            content = r.content.decode("utf-8", errors="ignore")
            if r.status_code == 200 and ("BEGIN:VCALENDAR" in content):
                try:
                    cal = ICal.from_ical(r.content)
                    cnt = sum(1 for _ in cal.walk("VEVENT"))
                    status = f"✅ OK ({cnt} events)"
                except Exception:
                    status = "✅ OK"
            else:
                status = f"⚠️ Unexpected ({r.status_code})"
        except Exception as e:
            status = f"❌ Error: {str(e)[:80]}"
        results.append({"ota":u.ota,"property_id":u.property_id,"status":status})
    return jsonify(results)

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

# ====== iCal export (per-unit) ======
@app.route("/ical/export/<int:unit_id>.ics")
def ical_export(unit_id):
    db=SessionLocal()
    u=db.query(Unit).filter(Unit.id==unit_id).first()
    blocks=db.query(AvailabilityBlock).filter(AvailabilityBlock.unit_id==unit_id).all()
    db.close()
    if not u: return "Not found",404
    lines=["BEGIN:VCALENDAR","VERSION:2.0","PRODID:-//ravuricoltd//channel-manager//EN"]
    for b in blocks:
        lines+=["BEGIN:VEVENT",
                 f"UID:cm-{unit_id}-{b.id}@ravuricoltd",
                 f"SUMMARY:BLOCKED ({u.ota} {u.property_id})",
                 f"DTSTART;VALUE=DATE:{b.start_date.replace('-','')}",
                 f"DTEND;VALUE=DATE:{b.end_date.replace('-','')}",
                 "END:VEVENT"]
    lines.append("END:VCALENDAR")
    ics="\r\n".join(lines)
    return (ics,200,{"Content-Type":"text/calendar; charset=utf-8",
                     "Content-Disposition":f'attachment; filename=unit-{unit_id}.ics'})

# ====== PUBLIC: Properties page (public + fallback) ======
@app.route("/properties")
def properties_index():
    meta = _load_meta()
    groups = meta.get("groups", {})

    # Optional: pending iCal count
    pending_map = {}
    try:
        db = SessionLocal()
        for slug, info in groups.items():
            unit_ids = info.get("unit_ids", [])
            if not unit_ids: 
                continue
            missing = db.query(Unit).filter(
                Unit.id.in_(unit_ids),
                (Unit.ical_url == None) | (Unit.ical_url == "")
            ).count()
            if missing:
                pending_map[slug] = missing
    except Exception:
        pass
    finally:
        try:
            db.close()
        except Exception:
            pass

    try:
        return render_template("properties.html", groups=groups, pending_map=pending_map)
    except TemplateNotFound:
        # Fallback simple list
        items = []
        for slug, info in groups.items():
            title = info.get("title", slug)
            items.append(f"<li><a href='/prop/{slug}' target='_blank'>{title}</a></li>")
        return f"<h2>Properties</h2><ul>{''.join(items)}</ul>"

# ====== Public property page ======
@app.route("/prop/<slug>")
def property_page(slug):
    info = _group_info(slug)
    if not info:
        return "Not found", 404

    title = info.get("title", slug)
    image_url = info.get("image_url") or "https://source.unsplash.com/featured/?pattaya,villa"
    unit_ids = info.get("unit_ids", [])

    price = None
    currency = "THB"
    if unit_ids:
        db = SessionLocal()
        rp = db.query(RatePlan).filter(RatePlan.unit_id == unit_ids[0]).first()
        db.close()
        if rp:
            price = rp.base_rate
            currency = rp.currency or "THB"

    try:
        return render_template(
            "room.html",
            title=title,
            image_url=image_url,
            price=price,
            currency=currency,
            publishable_key=STRIPE_PUBLISHABLE_KEY,
            slug=slug
        )
    except TemplateNotFound:
        # Minimal fallback page with calendar hidden (to avoid missing template crash)
        return f"<h2>{title}</h2><p>Public booking page template missing. Please restore templates/room.html.</p>"

# ---- Availability (grouped): DB blocks + iCal events merged ----
@app.route("/api/public/availability/<slug>", methods=["GET"])
def api_public_availability(slug):
    info = _group_info(slug)
    if not info:
        return jsonify({"error":"property not found"}), 404

    unit_ids = info.get("unit_ids", [])
    blocks_out = []

    db = SessionLocal()
    try:
        for uid in unit_ids:
            rows = db.query(AvailabilityBlock).filter(AvailabilityBlock.unit_id == uid).all()
            for b in rows:
                blocks_out.append({
                    "start_date": b.start_date,
                    "end_date": b.end_date,
                    "source": b.source or "manual",
                    "unit_id": uid
                })
        for uid in unit_ids:
            u = db.query(Unit).filter(Unit.id == uid).first()
            if not u or not u.ical_url:
                continue
            try:
                ev = fetch_ical(u.ical_url)
                for e in ev:
                    blocks_out.append({
                        "start_date": e["start"], "end_date": e["end"],
                        "source": "ical", "unit_id": uid
                    })
            except Exception:
                continue
    finally:
        db.close()

    seen = set()
    unique = []
    for b in blocks_out:
        key = (b["start_date"], b["end_date"], b["unit_id"], b["source"])
        if key in seen:
            continue
        seen.add(key); unique.append(b)

    return jsonify(unique)
