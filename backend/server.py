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

# Resend / SMTP config (email)
EMAIL_PROVIDER = os.environ.get("EMAIL_PROVIDER", "").lower()  # "resend" or "smtp" or empty
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")  # if using Resend
SMTP_SERVER = os.environ.get("SMTP_SERVER", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587) or 587)
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
ALERT_TO = os.environ.get("ALERT_TO", os.environ.get("ALERT_TO1", ""))  # support ALERT_TO1 old name
EMAIL_FROM = os.environ.get("EMAIL_FROM", f"RavuriCo <{SMTP_USER or 'no-reply@example.com'}>")

# ====== Email helpers ======
def send_via_resend(to_email, subject, html_body, text_body=""):
    """Send using Resend HTTP API. Requires RESEND_API_KEY."""
    if not RESEND_API_KEY:
        raise RuntimeError("Resend API key not configured")
    try:
        payload = {
            "from": EMAIL_FROM,
            "to": [to_email],
            "subject": subject,
            "html": html_body,
            "text": text_body
        }
        headers = {"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"}
        resp = requests.post("https://api.resend.com/emails", headers=headers, json=payload, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise

def send_via_smtp(to_email, subject, html_body, text_body=""):
    """Send using SMTP (Gmail app password or other SMTP)."""
    if not all([SMTP_SERVER, SMTP_USER, SMTP_PASSWORD]):
        raise RuntimeError("SMTP not configured")
    msg = MIMEMultipart("alternative")
    msg["From"] = EMAIL_FROM
    msg["To"] = to_email
    msg["Subject"] = subject
    part_text = MIMEText(text_body or html_body, "plain")
    part_html = MIMEText(html_body, "html")
    msg.attach(part_text)
    msg.attach(part_html)
    try:
        # Prefer TLS on port 587
        if SMTP_PORT in (587, 25):
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
            server.quit()
        else:
            # SSL (465)
            server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=15)
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
            server.quit()
        return True
    except Exception:
        raise

def send_email_best_effort(to_email, subject, html_body, text_body=""):
    """Try provider(s) in order and return True on success, otherwise raise."""
    # If user explicitly configured SMTP, prefer that
    # If EMAIL_PROVIDER == "resend", try Resend first then SMTP.
    errors = []
    if EMAIL_PROVIDER == "smtp" or (EMAIL_PROVIDER == "" and SMTP_SERVER and SMTP_USER and SMTP_PASSWORD):
        try:
            send_via_smtp(to_email, subject, html_body, text_body)
            return True
        except Exception as e:
            errors.append(("smtp", str(e)))
    if EMAIL_PROVIDER == "resend" or (EMAIL_PROVIDER == "" and RESEND_API_KEY):
        try:
            send_via_resend(to_email, subject, html_body, text_body)
            return True
        except Exception as e:
            errors.append(("resend", str(e)))
    # If both attempted and failed, raise combined error
    raise RuntimeError("Email failed: " + " | ".join([f"{k}:{v}" for k,v in errors]))

def send_alert(subject, body):
    """Send an alert to ALERT_TO (admin). Uses same best-effort email path."""
    try:
        if not ALERT_TO:
            print("⚠️ ALERT_TO not set — skipping alert")
            return
        send_email_best_effort(ALERT_TO, subject, f"<pre>{body}</pre>", body)
        print("📧 Alert sent to", ALERT_TO)
    except Exception as e:
        print("❌ Resend/SMTP alert error:", e)

# ====== Helpers ======
def _load_meta():
    """Read backend/unit_meta.json to get grouped properties."""
    try:
        meta_path = Path(__file__).with_name("unit_meta.json")
        if meta_path.exists():
            with open(meta_path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print("unit_meta load error:", e)
    return {"groups": {}}

def _group_info(slug):
    meta = _load_meta()
    return meta.get("groups", {}).get(slug)

def _parse_yyyy_mm_dd(s):
    y, m, d = s.split("-")
    return date(int(y), int(m), int(d))

def _as_date_str(dval) -> str:
    # Normalize icalendar dt to "YYYY-MM-DD"
    if hasattr(dval, "date"):
        return dval.date().isoformat()
    return str(dval)

def _overlaps(db, unit_id: int, start: str, end: str) -> bool:
    """
    Overlap if NOT (existing.end <= start OR existing.start >= end)
    """
    q = db.query(AvailabilityBlock).filter(
        AvailabilityBlock.unit_id == unit_id,
        ~(
            (AvailabilityBlock.end_date <= start) |
            (AvailabilityBlock.start_date >= end)
        )
    )
    return db.query(q.exists()).scalar()

def fetch_ical(ical_url):
    """
    Lightweight fetch for public availability merge endpoint.
    Background sync uses a more robust parser below.
    """
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
def _sync_units(db, units):
    """
    Shared sync core used by background, global button, and per-property button.
    Returns list of result dicts.
    """
    results = []
    for u in units:
        if not u.ical_url:
            results.append({
                "unit_id": u.id,
                "ota": u.ota,
                "property_id": u.property_id,
                "status": "skipped (no iCal URL)"
            })
            continue
        try:
            r = requests.get(u.ical_url, timeout=15)
            r.raise_for_status()
            cal = ICal.from_ical(r.content)

            # Clear previous rows for this unit for its OTA source
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
            results.append({
                "unit_id": u.id,
                "ota": u.ota,
                "property_id": u.property_id,
                "status": f"OK — {inserted} events"
            })
        except Exception as e:
            db.rollback()
            results.append({
                "unit_id": u.id,
                "ota": u.ota,
                "property_id": u.property_id,
                "status": f"ERROR — {str(e)[:120]}"
            })
    return results

def periodic_sync():
    """Every 10 minutes: mirror each unit's OTA iCal into availability_blocks."""
    while True:
        try:
            db = SessionLocal()
            units = db.query(Unit).all()
            res = _sync_units(db, units)
            for row in res:
                print(f"[SYNC] Unit {row['unit_id']}: {row['status']}")
            db.close()
        except Exception as e:
            print("sync loop error:", e)
            traceback.print_exc()
        time.sleep(600)  # 10 minutes

# ====== One-shot sync helpers & APIs ======
def sync_calendars_once():
    db = SessionLocal()
    try:
        units = db.query(Unit).all()
        return _sync_units(db, units)
    finally:
        db.close()

def sync_calendars_for_group(slug):
    info = _group_info(slug)
    if not info:
        return {"error": "group not found"}
    unit_ids = info.get("unit_ids", [])
    if not unit_ids:
        return {"error": "no units linked"}
    db = SessionLocal()
    try:
        units = db.query(Unit).filter(Unit.id.in_(unit_ids)).all()
        return {"ok": True, "summary": _sync_units(db, units)}
    finally:
        db.close()

@app.post("/api/admin/sync_now")
def api_admin_sync_now():
    if "user" not in session:
        return jsonify({"error": "unauthorized"}), 401
    try:
        summary = sync_calendars_once()
        return jsonify({"ok": True, "summary": summary})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500

@app.post("/api/admin/sync_property/<slug>")
def api_admin_sync_property(slug):
    if "user" not in session:
        return jsonify({"error": "unauthorized"}), 401
    res = sync_calendars_for_group(slug)
    if "error" in res:
        return jsonify(res), 400
    return jsonify(res)

# ====== Bootstrap ======
try:
    print("Bootstrap: init_db()")
    init_db()

    # ⚠️ IMPORTANT: Do NOT auto-import CSV on every boot (it resets prices).
    # Seed manually once via /admin/reimport when DB is empty.

    if SINGLE_WORKER:
        print("Starting periodic_sync thread (single worker)")
        threading.Thread(target=periodic_sync, daemon=True).start()
    else:
        print("Skipping periodic_sync thread (multiple workers)")
except Exception as e:
    print("Bootstrap error:", e)
    traceback.print_exc()

# ====== Translations / template text helper ======
def _t(lang_code):
    """Return simple translation/context dict used by templates as `t`."""
    # Minimal: you can extend with more keys used by templates.
    return {
        "brand": "RavuriCo",
        "book_and_pay": "Book & Pay",
        "booking_confirmed": "Booking confirmed — dates closed",
        "currency_symbol": "฿",
        "per_night": "per night",
        "test_mode_label": "Test mode",
    }

# ====== Auth & Basic ======
@app.route("/")
def index():
    if "user" not in session:
        return redirect(url_for("login"))
    db = SessionLocal()
    try:
        units = db.query(Unit).all()
        rates = db.query(RatePlan).all()
        rates_map = {r.unit_id: r.base_rate for r in rates}
        currency_map = {r.unit_id: (r.currency or "THB") for r in rates}
    finally:
        db.close()
    return render_template(
        "dashboard.html",
        units=units,
        rates_map=rates_map,
        currency_map=currency_map,
        lang=session.get("lang", APP_LANG_DEFAULT),
        t=_t(session.get("lang", APP_LANG_DEFAULT))
    )

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

@app.route("/health")
def health():
    return "ok", 200

@app.route("/hello")
def hello():
    return "hello", 200

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
            ok_text = ""
            try:
                ok_text = r.text
            except Exception:
                ok_text = r.content.decode("utf-8", errors="ignore")
            if r.status_code == 200 and ("BEGIN:VCALENDAR" in ok_text):
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
        if request.method == "GET":
            unit_id = request.args.get("unit_id", type=int)
            q = db.query(AvailabilityBlock)
            if unit_id:
                q = q.filter(AvailabilityBlock.unit_id == unit_id)
            rows = q.order_by(AvailabilityBlock.start_date.desc()).all()
            out = []
            for b in rows:
                out.append({
                    "id": b.id,
                    "unit_id": b.unit_id,
                    "start_date": b.start_date,
                    "end_date": b.end_date,
                    "source": b.source,
                    "note": b.note
                })
            return jsonify(out)

        if request.method == "POST":
            data = request.json or {}
            b = AvailabilityBlock(
                unit_id=data.get("unit_id"),
                start_date=data.get("start_date"),
                end_date=data.get("end_date"),
                source=data.get("source", "manual"),
                note=data.get("note", "")
            )
            db.add(b)
            db.commit()
            # send an alert to admin when manual block is added
            try:
                send_alert("New Manual Block", f"Unit {b.unit_id}: {b.start_date}–{b.end_date} ({b.source}) {b.note}")
            except Exception as e:
                # don't fail the request if alert fails
                print("alert send error:", e)
            return jsonify({"ok": True, "id": b.id})

        if request.method == "DELETE":
            bid = request.args.get("id", type=int)
            if not bid:
                return jsonify({"error": "id required"}), 400
            b = db.query(AvailabilityBlock).filter(AvailabilityBlock.id == bid).first()
            if b:
                db.delete(b)
                db.commit()
            return jsonify({"ok": True})
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
    lines=[
        "BEGIN:VCALENDAR","VERSION:2.0","PRODID:-//ravuricoltd//channel-manager//EN"
    ]
    for b in blocks:
        lines+=[
            "BEGIN:VEVENT",
            f"UID:cm-{unit_id}-{b.id}@ravuricoltd",
            f"SUMMARY:BLOCKED ({u.ota} {u.property_id})",
            f"DTSTART;VALUE=DATE:{b.start_date.replace('-','')}",
            f"DTEND;VALUE=DATE:{b.end_date.replace('-','')}",
            "END:VEVENT"
        ]
    lines.append("END:VCALENDAR")
    ics="\r\n".join(lines)
    return (ics,200,{"Content-Type":"text/calendar; charset=utf-8",
                     "Content-Disposition":f'attachment; filename=unit-{unit_id}.ics'})

# ====== PUBLIC: Properties page (public) ======
@app.route("/properties")
def properties_index():
    meta = _load_meta()
    groups = meta.get("groups", {})

    # Optional: show "pending iCal" counts
    db = SessionLocal()
    pending_map = {}
    try:
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
    finally:
        db.close()

    return render_template("properties.html", groups=groups, pending_map=pending_map, t=_t(session.get("lang", APP_LANG_DEFAULT)))

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

    # Pass t for template text (fixes missing 't')
    return render_template(
        "room.html",
        title=title,
        image_url=image_url,
        price=price,
        currency=currency,
        publishable_key=STRIPE_PUBLISHABLE_KEY,
        slug=slug,
        t=_t(session.get("lang", APP_LANG_DEFAULT)),
        is_admin_logged_in=("user" in session)
    )

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
        # DB blocks
        for uid in unit_ids:
            rows = db.query(AvailabilityBlock).filter(AvailabilityBlock.unit_id == uid).all()
            for b in rows:
                blocks_out.append({
                    "start_date": b.start_date,
                    "end_date": b.end_date,
                    "source": b.source or "manual",
                    "unit_id": uid
                })
        # OTA iCal (best-effort merge)
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

    # de-dup
    seen = set()
    unique = []
    for b in blocks_out:
        key = (b["start_date"], b["end_date"], b["unit_id"], b["source"])
        if key in seen:
            continue
        seen.add(key); unique.append(b)

    return jsonify(unique)

# ---- Stripe: create PaymentIntent for group (price × nights) ----
@app.route("/api/public/create_intent/<slug>", methods=["POST"])
def api_public_create_intent(slug):
    info = _group_info(slug)
    if not info:
        return jsonify({"error": "property not found"}), 404

    data = request.json or {}
    start = (data.get("start_date") or "").strip()
    end   = (data.get("end_date") or "").strip()

    if not (start and end):
        return jsonify({"error": "missing dates"}), 400
    if end <= start:
        return jsonify({"error": "check-out must be after check-in"}), 400

    unit_ids = info.get("unit_ids", [])
    if not unit_ids:
        return jsonify({"error":"no units linked to this property"}),400

    db = SessionLocal()
    rp = db.query(RatePlan).filter(RatePlan.unit_id == unit_ids[0]).first()
    db.close()

    if not rp or not rp.base_rate:
        return jsonify({"error": "price not set for this property"}), 400

    nights = (_parse_yyyy_mm_dd(end) - _parse_yyyy_mm_dd(start)).days
    if nights <= 0:
        return jsonify({"error": "nights must be > 0"}), 400

    amount = int(round(rp.base_rate * nights * 100))  # THB → satang
    currency = (rp.currency or "THB").lower()

    try:
        intent = stripe.PaymentIntent.create(
            amount=amount,
            currency=currency,
            automatic_payment_methods={"enabled": True}
        )
        return jsonify({"ok": True, "client_secret": intent.client_secret})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# ---- Public booking: grouped + per-unit ----
@app.route("/api/public/book_group/<slug>", methods=["POST"])
def public_book_group(slug):
    """Block dates across ALL unit_ids in the group (Airbnb+Booking+Agoda)."""
    try:
        info = _group_info(slug)
        if not info:
            return jsonify({"error": "property not found"}), 404

        data = request.json or {}
        start = (data.get("start_date") or "").strip()
        end   = (data.get("end_date") or "").strip()
        name  = (data.get("name") or "").strip()
        email = (data.get("email") or "").strip()

        if not (start and end and name and email):
            return jsonify({"error": "missing fields"}), 400
        if end <= start:
            return jsonify({"error": "check-out must be after check-in"}), 400

        unit_ids = info.get("unit_ids", [])
        if not unit_ids:
            return jsonify({"error": "no units linked to this property"}), 400

        db = SessionLocal()
        try:
            # Reject if ANY unit overlaps
            for uid in unit_ids:
                if _overlaps(db, uid, start, end):
                    return jsonify({"error": "Dates not available"}), 409

            # Safe: create blocks for ALL units
            for uid in unit_ids:
                db.add(AvailabilityBlock(
                    unit_id=uid,
                    start_date=start,
                    end_date=end,
                    source="direct",
                    note=f"Guest: {name} {email} (group:{slug})"
                ))
            db.commit()
        finally:
            db.close()

        # Send emails (guest + admin alert) — best effort
        try:
            title = f"Booking confirmed — {slug} {start}–{end}"
            guest_html = f"<p>Hi {name},</p><p>Your booking for <strong>{slug}</strong> from <strong>{start}</strong> to <strong>{end}</strong> is confirmed.</p>"
            guest_text = f"Hi {name},\nYour booking for {slug} from {start} to {end} is confirmed."
            try:
                send_email_best_effort(email, title, guest_html, guest_text)
            except Exception as e:
                print("guest email error:", e)

            alert_body = f"Property {slug}: {start}–{end} Guest: {name} ({email}) on {len(unit_ids)} OTA listings"
            try:
                send_alert("New Direct Booking (Grouped)", alert_body)
            except Exception as e:
                print("alert error:", e)
        except Exception as ee:
            print("email sending error:", ee)

        return jsonify({"ok": True})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# ====== Legacy public/testing ======
@app.route("/r")
def list_public_links():
    db = SessionLocal()
    rows = db.query(Unit).all()
    db.close()
    base = request.host_url.rstrip("/")
    html = ["<h2>Public Links</h2><ul>"]
    for u in rows:
        html.append(f'<li><a href="/r/{u.id}" target="_blank">/r/{u.id}</a> — {u.ota} / {u.property_id} — <a href="{base}/ical/export/{u.id}.ics">ical</a></li>')
    html.append("</ul>")
    return "".join(html)

@app.route("/r/<int:unit_id>")
def room(unit_id):
    db = SessionLocal()
    u = db.query(Unit).filter(Unit.id == unit_id).first()
    rp = db.query(RatePlan).filter(RatePlan.unit_id == unit_id).first()
    db.close()
    if not u:
        return "Not found", 404

    display_name = f"{u.ota} — {u.property_id}"
    image_url = "https://source.unsplash.com/featured/?pattaya,villa"
    price = rp.base_rate if rp else None
    currency = rp.currency if rp else "THB"

    return render_template(
        "room.html",
        title=display_name,
        image_url=image_url,
        price=price,
        currency=currency,
        publishable_key=STRIPE_PUBLISHABLE_KEY,
        t=_t(session.get("lang", APP_LANG_DEFAULT))
    )

@app.route("/api/public/book/<int:unit_id>", methods=["POST"])
def public_book(unit_id):
    try:
        data = request.json or {}
        start = (data.get("start_date") or "").strip()
        end = (data.get("end_date") or "").strip()
        name = (data.get("name") or "").strip()
        email = (data.get("email") or "").strip()
        if not (start and end and name and email):
            return jsonify({"error": "missing fields"}), 400
        if end <= start:
            return jsonify({"error": "check-out must be after check-in"}), 400

        db = SessionLocal()
        u = db.query(Unit).filter(Unit.id == unit_id).first()
        if not u:
            db.close()
            return jsonify({"error": "unit not found"}), 404

        if _overlaps(db, unit_id, start, end):
            db.close()
            return jsonify({"error": "Dates not available"}), 409

        db.add(AvailabilityBlock(unit_id=unit_id, start_date=start, end_date=end, source="direct", note=f"Guest: {name} {email}"))
        db.commit()
        db.close()

        # emails
        try:
            title = f"Booking confirmed — Unit {unit_id} {start}–{end}"
            guest_html = f"<p>Hi {name},</p><p>Your booking for <strong>{u.property_id}</strong> from <strong>{start}</strong> to <strong>{end}</strong> is confirmed.</p>"
            guest_text = guest_html
            try:
                send_email_best_effort(email, title, guest_html, guest_text)
            except Exception as e:
                print("guest email error:", e)

            send_alert("New Direct Booking", f"Unit {unit_id}: {start}–{end} Guest: {name} ({email})")
        except Exception as e:
            print("email/alert error:", e)

        return jsonify({"ok": True})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# ====== Grouped Admin UI ======
@app.route("/admin/groups")
def admin_groups():
    if "user" not in session:
        return redirect(url_for("login"))
    meta = _load_meta()
    groups = meta.get("groups", {})
    html = ["<h2>Grouped Admin</h2><ul>"]
    for slug, info in groups.items():
        title = info.get("title", slug)
        html.append(f'<li><a href="/admin/calendar/{slug}">{title}</a> — <code>{slug}</code></li>')
    html.append("</ul>")
    return "".join(html)

@app.route("/admin/calendar/<slug>")
def admin_calendar(slug):
    if "user" not in session:
        return redirect(url_for("login"))
    info = _group_info(slug)
    if not info:
        return "Property group not found", 404
    title = info.get("title", slug)
    unit_ids = info.get("unit_ids", [])
    return render_template("admin_calendar.html", title=title, slug=slug, unit_ids=unit_ids, t=_t(session.get("lang", APP_LANG_DEFAULT)))

@app.route("/api/admin/toggle_day/<slug>", methods=["POST"])
def api_admin_toggle_day(slug):
    if "user" not in session:
        return jsonify({"error": "unauthorized"}), 401

    info = _group_info(slug)
    if not info:
        return jsonify({"error": "group not found"}), 404
    unit_ids = info.get("unit_ids", [])
    if not unit_ids:
        return jsonify({"error": "no units linked"}), 400

    data = request.json or {}
    date_str = (data.get("date") or "").strip()
    action = (data.get("action") or "block").strip().lower()

    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return jsonify({"error": "invalid date"}), 400

    start = dt.strftime("%Y-%m-%d")
    end = (dt + timedelta(days=1)).strftime("%Y-%m-%d")

    db = SessionLocal()
    try:
        if action == "block":
            for uid in unit_ids:
                exists = db.query(AvailabilityBlock).filter(
                    AvailabilityBlock.unit_id == uid,
                    AvailabilityBlock.start_date == start,
                    AvailabilityBlock.end_date == end,
                    AvailabilityBlock.source == "manual"
                ).first()
                if not exists:
                    db.add(AvailabilityBlock(
                        unit_id=uid,
                        start_date=start,
                        end_date=end,
                        source="manual",
                        note=f"admin calendar ({slug})"
                    ))
            db.commit()
            return jsonify({"ok": True})

        elif action == "unblock":
            for uid in unit_ids:
                q = db.query(AvailabilityBlock).filter(
                    AvailabilityBlock.unit_id == uid,
                    AvailabilityBlock.start_date == start,
                    AvailabilityBlock.end_date == end,
                    AvailabilityBlock.source == "manual"
                )
                for row in q.all():
                    db.delete(row)
            db.commit()
            return jsonify({"ok": True})

        else:
            return jsonify({"error": "unknown action"}), 400

    finally:
        db.close()

# ====== Helper: list export links ======
@app.get("/admin/export_links")
def admin_export_links():
    if "user" not in session:
        return redirect(url_for("login"))
    db = SessionLocal()
    rows = db.query(Unit).all()
    db.close()
    base = request.host_url.rstrip("/")
    html = ["<h3>Export iCal URLs (paste into Airbnb/Booking/Agoda)</h3><ul>"]
    for u in rows:
        url = f"{base}/ical/export/{u.id}.ics"
        html.append(f"<li>Unit {u.id} — {u.ota} / {u.property_id}: "
                    f"<a target='_blank' href='{url}'>{url}</a></li>")
    html.append("</ul>")
    return "".join(html)

# ====== Manual re-import (seed DB once after moving to persistent disk) ======
@app.get("/admin/reimport")
def admin_reimport():
    if "user" not in session:
        return "Login required", 401
    try:
        csv_path = Path(__file__).with_name("ota_properties_prefilled.csv")
        if not csv_path.exists():
            return "CSV not found", 404
        importer.import_csv(str(csv_path))
        return "CSV reimported successfully", 200
    except Exception as e:
        return f"Error: {e}", 500

# ====== Admin email test route ======
@app.get("/admin/test_email")
def admin_test_email():
    if "user" not in session:
        return redirect(url_for("login"))
    t = request.args.get("to", ALERT_TO or ADMIN_EMAIL)
    sample_html = "<p>This is a test email from RavuriCo Channel Manager.</p>"
    sample_text = "This is a test email from RavuriCo Channel Manager."
    try:
        send_email_best_effort(t, "Test email — RavuriCo Channel Manager", sample_html, sample_text)
        return "Test email sent (attempted). Check logs.", 200
    except Exception as e:
        print("❌ Email send error:", e)
        return f"Failed: {e}", 500
