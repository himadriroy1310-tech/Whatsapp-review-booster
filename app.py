"""
Apex Dental Care - Google Review Automation MVP
Phase 1: Front-desk management dashboard, patient intake, database logging,
phone sanitation, edge-case validation, and WhatsApp Click-to-Chat URL generation.

Single-file Flask app using built-in sqlite3. No external DB, no Node/React.
"""

import os
import re
import sqlite3
import html
from datetime import datetime, timedelta
from urllib.parse import quote

from flask import (
    Flask, g, render_template, request, redirect,
    url_for, flash, jsonify, abort
)

# --------------------------------------------------------------------------- #
# App configuration
# --------------------------------------------------------------------------- #

CLINIC_NAME = "Apex Dental Care"
CLINIC_SLUG = "apex"
BASE_DOMAIN = "https://whatsapp-review-booster.onrender.com/"  # placeholder, update for production

# Google Business Profile Place ID for the "positive sentiment" redirect.
# Replace with the clinic's real Place ID before going live.
GOOGLE_PLACE_ID = "YOUR_PLACE_ID"
GOOGLE_REVIEW_URL = f"https://search.google.com/local/writereview?placeid={GOOGLE_PLACE_ID}"

# Country codes we support in the intake form: (dial code without '+', label)
COUNTRY_CODES = [
    {"code": "91", "label": "+91 India"},
    {"code": "44", "label": "+44 UK"},
    {"code": "1", "label": "+1 US/CA"},
    {"code": "61", "label": "+61 Australia"},
]
VALID_COUNTRY_CODES = {c["code"] for c in COUNTRY_CODES}

# instance_relative_config=True tells Flask that config/data files live in
# an `instance/` folder alongside this file, kept separate from the app
# package and excluded from version control (see .gitignore).
app = Flask(__name__, instance_relative_config=True)
# Secret key only needed for flash messages / session cookie signing.
# For an MVP, an env var fallback to a fixed dev key is fine.
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-only-secret-change-me")

# Flask does not create the instance folder automatically.
os.makedirs(app.instance_path, exist_ok=True)
DATABASE = os.path.join(app.instance_path, "clinic.db")


# --------------------------------------------------------------------------- #
# Database helpers
# --------------------------------------------------------------------------- #

def get_db():
    """Return a request-scoped sqlite3 connection with Row access."""
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()


def init_db():
    """Create the customers table if it doesn't already exist."""
    conn = sqlite3.connect(DATABASE)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            country_code  TEXT NOT NULL,
            raw_phone     TEXT NOT NULL,
            clean_phone   TEXT NOT NULL,
            status        TEXT DEFAULT 'Pending',
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sent_at       TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS feedbacks (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name  TEXT,
            phone          TEXT NOT NULL,
            feedback_text  TEXT NOT NULL,
            submitted_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------- #
# Validation / sanitization helpers
# --------------------------------------------------------------------------- #

def sanitize_name(raw_name: str) -> str:
    """Strip whitespace and escape HTML entities to prevent stored XSS."""
    name = (raw_name or "").strip()
    return html.escape(name, quote=True)


def sanitize_phone(country_code: str, raw_phone: str):
    """
    Clean a raw phone number into a dialable, country-prefixed digit string.

    Rules:
      - Strip everything that isn't a digit (spaces, dashes, parens, '+').
      - If the resulting local number starts with a trunk '0' (common outside
        the North American numbering plan, e.g. UK '07123456789'), drop the
        leading zero before prefixing the country code.
      - Final clean_phone = country_code + local_digits (no '+', no spaces).

    Returns:
      (clean_phone, error_message). error_message is None on success.
    """
    if country_code not in VALID_COUNTRY_CODES:
        return None, "Please select a valid country code."

    # Strip every non-digit character (spaces, dashes, parens, leading '+', etc.)
    digits = re.sub(r"\D", "", raw_phone or "")

    if not digits:
        return None, "Please enter a phone number."

    # Trunk-zero handling: numbers dialed locally often start with '0'
    # (e.g. UK 07123456789 -> 7123456789). The North American plan (+1)
    # does not use a trunk '0', so we only strip it for other codes.
    if country_code != "1" and digits.startswith("0"):
        digits = digits.lstrip("0")
        if not digits:
            return None, "Phone number is invalid after removing leading zeros."

    clean_phone = f"{country_code}{digits}"

    # Length verification against the full E.164-style digit string.
    if len(clean_phone) < 7 or len(clean_phone) > 15:
        return None, (
            "Phone number length looks invalid. Please double-check the "
            "number and country code."
        )

    return clean_phone, None


def find_recent_duplicate(db, clean_phone: str):
    """Return a matching record if the same clean_phone was added in the last 7 days."""
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    row = db.execute(
        """
        SELECT id FROM customers
        WHERE clean_phone = ?
          AND created_at >= ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (clean_phone, seven_days_ago.strftime("%Y-%m-%d %H:%M:%S")),
    ).fetchone()
    return row


def build_whatsapp_link(customer_name: str, clean_phone: str) -> str:
    """
    Build a wa.me Click-to-Chat URL with a pre-filled, fully-encoded message
    that links to the (future) Phase 2 rating redirect page.
    """
    encoded_name_for_link = quote(customer_name)
    rating_url = (
        f"{BASE_DOMAIN}/rate/{CLINIC_SLUG}"
        f"?phone={clean_phone}&name={encoded_name_for_link}"
    )
    message = (
        f"Hi {customer_name}, thank you for choosing {CLINIC_NAME}! "
        f"If you had a great experience with us, could you please take "
        f"30 seconds to share your review? {rating_url}"
    )
    encoded_message = quote(message)
    return f"https://wa.me/{clean_phone}?text={encoded_message}"


def format_phone_display(country_code: str, clean_phone: str) -> str:
    """Human-friendly display: +<country_code> <local number>."""
    local_part = clean_phone[len(country_code):]
    return f"+{country_code} {local_part}"


def validate_rating_phone(raw_phone: str):
    """
    Validate a phone value arriving via query string / form data on the
    public rating page. Returns a clean, digits-only phone string, or
    None if the value is missing or clearly malformed. Never raises.
    """
    if not raw_phone:
        return None
    digits = re.sub(r"\D", "", raw_phone)
    if len(digits) < 7 or len(digits) > 15:
        return None
    return digits


def find_existing_feedback(db, phone: str):
    """Return an existing feedback row for this phone number, if any."""
    return db.execute(
        "SELECT id FROM feedbacks WHERE phone = ? LIMIT 1",
        (phone,),
    ).fetchone()


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

@app.route("/")
def dashboard():
    db = get_db()
    
    # 1. Fetch customer list
    rows = db.execute(
        "SELECT * FROM customers ORDER BY created_at DESC"
    ).fetchall()

    customers = []
    for r in rows:
        customers.append({
            "id": r["id"],
            "customer_name": r["customer_name"],
            "phone_display": format_phone_display(r["country_code"], r["clean_phone"]),
            "clean_phone": r["clean_phone"],
            "status": r["status"],
            "created_at": r["created_at"],
            "sent_at": r["sent_at"],
            "whatsapp_link": build_whatsapp_link(r["customer_name"], r["clean_phone"]),
        })

    # 2. Fetch all negative feedback submissions
    feedback_rows = db.execute(
        "SELECT * FROM feedbacks ORDER BY submitted_at DESC"
    ).fetchall()

    total_count = len(customers)
    pending_count = sum(1 for c in customers if c["status"] == "Pending")
    sent_count = sum(1 for c in customers if c["status"] == "Sent")

    return render_template(
        "dashboard.html",
        clinic_name=CLINIC_NAME,
        customers=customers,
        feedbacks=feedback_rows,  # Pass feedback list to template
        country_codes=COUNTRY_CODES,
        total_count=total_count,
        pending_count=pending_count,
        sent_count=sent_count,
    )


@app.route("/add-record", methods=["POST"])
def add_record():
    db = get_db()

    raw_name = request.form.get("customer_name", "")
    country_code = request.form.get("country_code", "")
    raw_phone = request.form.get("phone", "")

    customer_name = sanitize_name(raw_name)
    if not customer_name:
        flash("Customer name is required.", "error")
        return redirect(url_for("dashboard"))

    clean_phone, error = sanitize_phone(country_code, raw_phone)
    if error:
        flash(error, "error")
        return redirect(url_for("dashboard"))

    duplicate = find_recent_duplicate(db, clean_phone)
    if duplicate:
        flash(
            f"A record for this phone number was already added in the last "
            f"7 days. Skipped duplicate entry.",
            "warning",
        )
        return redirect(url_for("dashboard"))

    db.execute(
        """
        INSERT INTO customers (customer_name, country_code, raw_phone, clean_phone, status)
        VALUES (?, ?, ?, ?, 'Pending')
        """,
        (customer_name, country_code, raw_phone.strip(), clean_phone),
    )
    db.commit()

    flash(f"Record added for {customer_name}.", "success")
    return redirect(url_for("dashboard"))


@app.route("/delete-record/<int:record_id>", methods=["POST"])
def delete_record(record_id):
    db = get_db()
    db.execute("DELETE FROM customers WHERE id = ?", (record_id,))
    db.commit()
    flash("Record deleted.", "success")
    return redirect(url_for("dashboard"))


@app.route("/mark-sent/<int:record_id>", methods=["POST"])
def mark_sent(record_id):
    db = get_db()
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    cur = db.execute(
        "UPDATE customers SET status = 'Sent', sent_at = ? WHERE id = ?",
        (now, record_id),
    )
    db.commit()

    if cur.rowcount == 0:
        return jsonify({"success": False, "error": "Record not found"}), 404

    return jsonify({"success": True, "sent_at": now})


@app.route("/rate/<clinic_id>")
def rate_page(clinic_id):
    """
    Public-facing rating redirect page reached via the WhatsApp message link.
    Routes happy patients to Google reviews and captures unhappy patients'
    feedback privately instead of letting it land on a public review.
    """
    if clinic_id != CLINIC_SLUG:
        abort(404)

    raw_phone = request.args.get("phone", "")
    raw_name = request.args.get("name", "")

    phone = validate_rating_phone(raw_phone)
    customer_name = sanitize_name(raw_name)

    # Edge Case 1: missing/invalid phone -> graceful fallback card instead of
    # a crash or a confusing form with nothing to submit against.
    if not phone:
        return render_template(
            "rate.html",
            view="fallback",
            clinic_name=CLINIC_NAME,
            google_review_url=GOOGLE_REVIEW_URL,
        )

    # Edge Case 2: this phone already left private feedback -> don't ask again.
    db = get_db()
    if find_existing_feedback(db, phone):
        return render_template(
            "rate.html",
            view="already_submitted",
            clinic_name=CLINIC_NAME,
            google_review_url=GOOGLE_REVIEW_URL,
        )

    return render_template(
        "rate.html",
        view="rate",
        clinic_name=CLINIC_NAME,
        phone=phone,
        customer_name=customer_name,
        google_review_url=GOOGLE_REVIEW_URL,
    )


@app.route("/submit-feedback", methods=["POST"])
def submit_feedback():
    """
    Store a patient's private "Needs Improvement" feedback and move their
    front-desk record to 'Reviewed' so staff know to follow up.
    """
    db = get_db()

    raw_phone = request.form.get("phone", "")
    raw_name = request.form.get("name", "")
    raw_feedback = request.form.get("feedback_text", "")

    phone = validate_rating_phone(raw_phone)
    customer_name = sanitize_name(raw_name)
    feedback_text = html.escape((raw_feedback or "").strip(), quote=True)

    if not phone:
        return jsonify({"success": False, "error": "Invalid or missing phone number."}), 400

    if len(feedback_text) < 5:
        return jsonify({"success": False, "error": "Feedback must be at least 5 characters."}), 400

    # Guard against double-submits (e.g. a resubmitted form / replayed request).
    if find_existing_feedback(db, phone):
        return jsonify({
            "success": True,
            "message": "We already have your feedback on file. Thank you!",
        })

    db.execute(
        """
        INSERT INTO feedbacks (customer_name, phone, feedback_text)
        VALUES (?, ?, ?)
        """,
        (customer_name, phone, feedback_text),
    )

    db.execute(
        "UPDATE customers SET status = 'Reviewed' WHERE clean_phone = ?",
        (phone,),
    )

    db.commit()

    return jsonify({
        "success": True,
        "message": "Thank you for your feedback. Our management team will contact you shortly.",
    })


# --------------------------------------------------------------------------- #
# Application Initialization
# --------------------------------------------------------------------------- #

# Run table creation immediately when Gunicorn loads the module
init_db()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
