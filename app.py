from flask import (
    Flask, render_template, request, redirect, url_for, flash,
    abort, jsonify, send_from_directory, Response
)
import io
from PIL import Image, ImageOps
from werkzeug.exceptions import HTTPException
from dotenv import load_dotenv
import html

load_dotenv()  # Ensure .env is loaded and overrides any existing environment variables

import os
import re
import json
import requests
import psycopg
from functools import wraps
from psycopg.rows import dict_row, tuple_row
import uuid
from datetime import date, datetime, timezone, timedelta 
from decimal import Decimal, InvalidOperation
from functools import wraps
from urllib.parse import urlsplit, quote
import xml.etree.ElementTree as ET

from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    logout_user,
    login_required,
    current_user
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)



import os
import logging
from supabase import create_client, Client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

logger.info(
    "Supabase environment check: URL present=%s, KEY present=%s",
    bool(SUPABASE_URL),
    bool(SUPABASE_KEY),
)

supabase: Client | None = None

if not SUPABASE_URL or not SUPABASE_KEY:
    logger.error(
        "Supabase configuration missing. "
        "Check SUPABASE_URL and SUPABASE_KEY in your environment."
    )
else:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("Supabase client initialized successfully.")
    except Exception:
        logger.exception("Supabase client initialization failed.")
        raise




from werkzeug.utils import secure_filename
import mysql.connector
from config import Config


app = Flask(
    __name__,
    static_folder="static",
    static_url_path="/static"
)

app.config.from_object(Config)

app.logger.info("Application root: %s", app.root_path)
app.logger.info("Static folder: %s", app.static_folder)
app.logger.info(
    "Static folder exists: %s",
    os.path.isdir(app.static_folder)
)

@app.route("/debug-static")
def debug_static():
    static_dir = app.static_folder

    files_to_check = [
        "home.css",
        "theme.css",
        "site.css",
        "img/cat-houses.jpeg",
        "img/cat-hostels.jpeg",
        "img/cat-plots.jpeg",
        "img/cat-roommates.jpeg",
        "img/cat-stay.jpeg",
        "img/cat-travel.jpeg",
        "img/hero-house.jpeg",
    ]

    return jsonify({
        "app_root": app.root_path,
        "static_folder": static_dir,
        "static_folder_exists": os.path.isdir(static_dir),
        "files": {
            filename: os.path.isfile(
                os.path.join(static_dir, filename)
            )
            for filename in files_to_check
        }
    })

@app.template_filter("photo_url")
def photo_url(filename):
    """Return a usable image URL for both Supabase URLs and old local files."""
    if not filename:
        return ""
    if filename.startswith(("http://", "https://")):
        return filename
    return url_for("static", filename="uploads/properties/" + filename)

@app.context_processor
def inject_year():
    return {"current_year": date.today().year}    

# =========================================================
# FILE UPLOAD CONFIGURATION
# =========================================================

UPLOAD_FOLDER = os.path.join(
    app.root_path,
    "static",
    "uploads",
    "properties"
)

ALLOWED_EXTENSIONS = {
    "jpg",
    "jpeg",
    "png",
    "webp"
}

PLACE_CATEGORIES = [
    ("guest_house", "Guest house"),
    ("motel", "Motel"),
    ("resort", "Resort"),
    ("restaurant", "Restaurant"),
]
VALID_CATEGORIES = {c for c, _ in PLACE_CATEGORIES}

_KENYA_COUNTIES = {
    "Baringo", "Bomet", "Bungoma", "Busia", "Elgeyo-Marakwet", "Embu",
    "Garissa", "Homa Bay", "Isiolo", "Kajiado", "Kakamega", "Kericho",
    "Kiambu", "Kilifi", "Kirinyaga", "Kisii", "Kisumu", "Kitui", "Kwale",
    "Laikipia", "Lamu", "Machakos", "Makueni", "Mandera", "Marsabit",
    "Meru", "Migori", "Mombasa", "Murang'a", "Nairobi", "Nakuru", "Nandi",
    "Narok", "Nyamira", "Nyandarua", "Nyeri", "Samburu", "Siaya",
    "Taita-Taveta", "Tana River", "Tharaka-Nithi", "Trans Nzoia", "Turkana",
    "Uasin Gishu", "Vihiga", "Wajir", "West Pokot",
}

_MAJOR_TOWNS = {
    "Athi River", "Diani", "Eldoret", "Gilgil", "Juja", "Kapsabet",
    "Kikuyu", "Kitale", "Kitengela", "Limuru", "Lodwar", "Malindi",
    "Molo", "Mtwapa", "Mumias", "Naivasha", "Nanyuki", "Ngong",
    "Nyahururu", "Karatina", "Ongata Rongai", "Ruiru", "Thika", "Voi",
    "Webuye", "Kimilili", "Kericho", "Kakamega", "Chuka", "Maua",
}

# Alphabetical, with "Other" always last (for places outside Kenya)
SUPPORTED_TOWNS = sorted(_KENYA_COUNTIES | _MAJOR_TOWNS) + ["Other"]

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Adjusted to 30 MB to prevent Gunicorn timeouts on mobile connections
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024  

PRIVATE_FOLDER = os.path.join(app.instance_path, "private_proofs")
os.makedirs(PRIVATE_FOLDER, exist_ok=True)

MAX_PHOTOS = 10
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_PROOF_BYTES = 5 * 1024 * 1024
PROOF_EXTENSIONS = {"pdf", "jpg", "jpeg", "png"}
RENT_TYPES = {"house", "bedsitter", "single_room", "apartment", "hostel"}
SALE_TYPES = {"house", "plot"}
Image.MAX_IMAGE_PIXELS = 60_000_000


# =========================================================
# SEO: ROBOTS.TXT AND XML SITEMAP
@app.route("/robots.txt")
def serve_robots_txt():
    """Serve robots.txt from the static directory."""
    return send_from_directory(app.static_folder, "robots.txt")


@app.route("/sitemap.xml", methods=["GET"])
def sitemap():
    """Generate the CivicNest XML sitemap."""

    namespace = "http://www.sitemaps.org/schemas/sitemap/0.9"
    ET.register_namespace("", namespace)

    urlset = ET.Element(f"{{{namespace}}}urlset")

    def add_url(loc, changefreq="weekly", priority="0.7",
                lastmod=None):
        entry = ET.SubElement(
            urlset, f"{{{namespace}}}url"
        )

        ET.SubElement(
            entry, f"{{{namespace}}}loc"
        ).text = loc

        if lastmod:
            ET.SubElement(
                entry, f"{{{namespace}}}lastmod"
            ).text = str(lastmod)

        ET.SubElement(
            entry, f"{{{namespace}}}changefreq"
        ).text = changefreq

        ET.SubElement(
            entry, f"{{{namespace}}}priority"
        ).text = priority

    # Public pages. Missing endpoints are skipped safely.
    static_pages = [
        ("home", "daily", "1.0"),
        ("rent_page", "daily", "0.8"),
        ("buy_page", "daily", "0.8"),
        ("sell_page", "weekly", "0.7"),
        ("travel_page", "weekly", "0.7"),
    ]

    for endpoint, frequency, priority in static_pages:
        if endpoint not in app.view_functions:
            app.logger.warning(
                "Sitemap skipped missing endpoint: %s",
                endpoint
            )
            continue

        try:
            page_url = url_for(
                endpoint,
                _external=True,
                _scheme="https"
            )
            add_url(page_url, frequency, priority)

        except Exception:
            app.logger.exception(
                "Could not generate URL for %s",
                endpoint
            )

    # Include active property listings.
    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute("""
            SELECT id, updated_at
            FROM properties
            WHERE status = 'active'
        """)

        properties = cursor.fetchall()

        if "property_details" in app.view_functions:
            for property_id, updated_at in properties:
                try:
                    property_url = url_for(
                        "property_details",
                        property_id=property_id,
                        _external=True,
                        _scheme="https"
                    )

                    lastmod = None
                    if updated_at:
                        lastmod = (
                            updated_at.date().isoformat()
                            if hasattr(updated_at, "date")
                            else str(updated_at)[:10]
                        )

                    add_url(
                        property_url,
                        changefreq="weekly",
                        priority="0.9",
                        lastmod=lastmod
                    )

                except Exception:
                    app.logger.exception(
                        "Could not generate URL for property %s",
                        property_id
                    )
        else:
            app.logger.warning(
                "Sitemap skipped properties: "
                "property_details endpoint not found"
            )

    except Exception:
        app.logger.exception(
            "Could not retrieve properties for sitemap"
        )

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()

    xml_bytes = ET.tostring(
        urlset,
        encoding="utf-8",
        xml_declaration=True
    )

    return Response(
        xml_bytes,
        content_type="application/xml; charset=utf-8"
    )



# =========================================================
# UPLOAD ERROR HANDLING AND SUPABASE STORAGE
# =========================================================

@app.errorhandler(413)
def upload_too_large(error):
    flash(
        "Those files are too large. Use smaller photos and try again.",
        "error"
    )
    return redirect(request.referrer or url_for("home"))


def require_supabase():
    """Return the configured Supabase client or raise a clear error."""
    if supabase is None:
        app.logger.error(
            "Supabase Storage is unavailable. Check SUPABASE_URL "
            "and SUPABASE_KEY in the deployment environment."
        )
        raise RuntimeError(
            "Photo storage is temporarily unavailable. "
            "Please try again later."
        )

    return supabase


def save_photo(file):
    """Validate, optimize, and upload a property photo as WebP."""
    if not file or not file.filename:
        raise ValueError("Please select a photo to upload.")

    data = file.read(MAX_IMAGE_BYTES + 1)

    if not data:
        raise ValueError("The selected photo is empty.")

    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Each photo must be under 12 MB.")

    try:
        # Verify the image before processing.
        test_img = Image.open(io.BytesIO(data))
        test_img.verify()

        # Reopen the image because verify() consumes its image state.
        img = Image.open(io.BytesIO(data))

        if img.format not in {"JPEG", "PNG", "WEBP"}:
            raise ValueError(
                "One of the photos is not a valid JPG, PNG or WEBP image."
            )

        img = ImageOps.exif_transpose(img)
        img.thumbnail((1600, 1600))

        if img.mode != "RGB":
            img = img.convert("RGB")

        buffer = io.BytesIO()
        img.save(buffer, format="WEBP", quality=80)
        buffer.seek(0)

    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(
            "One of the photos is not a valid JPG, PNG or WEBP image."
        ) from exc

    name = f"{uuid.uuid4().hex}.webp"
    client = require_supabase()
    storage = client.storage.from_("property-images")

    storage.upload(
        path=name,
        file=buffer.getvalue(),
        file_options={"content-type": "image/webp"}
    )

    return storage.get_public_url(name)


def save_proof(file):
    """Upload an ownership document to Supabase Storage."""
    if not file or not file.filename:
        raise ValueError("Please select a proof-of-ownership document.")

    original = secure_filename(file.filename)
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""

    if ext not in PROOF_EXTENSIONS:
        raise ValueError(
            "Proof of ownership must be a PDF, JPG or PNG file."
        )

    data = file.read(MAX_PROOF_BYTES + 1)

    if not data:
        raise ValueError("The proof document is empty.")

    if len(data) > MAX_PROOF_BYTES:
        raise ValueError("The proof document must be under 5 MB.")

    if ext == "pdf" and not data.startswith(b"%PDF"):
        raise ValueError("That file is not a valid PDF.")

    if ext in {"jpg", "jpeg", "png"}:
        try:
            image = Image.open(io.BytesIO(data))
            image.verify()
        except Exception as exc:
            raise ValueError(
                "The proof image is not a valid JPG or PNG."
            ) from exc

    name = f"proofs/{uuid.uuid4().hex}.{ext}"

    if ext == "pdf":
        content_type = "application/pdf"
    elif ext in {"jpg", "jpeg"}:
        content_type = "image/jpeg"
    else:
        content_type = "image/png"

    client = require_supabase()
    storage = client.storage.from_("property-images")

    storage.upload(
        path=name,
        file=data,
        file_options={"content-type": content_type}
    )

    return storage.get_public_url(name)


def remove_uploads(photo_urls, proof_url=None):
    """Attempt to remove uploaded files if database insertion fails."""
    client = require_supabase()
    files_to_remove = []

    for url in photo_urls or []:
        if not url:
            continue

        filename = url.split("?", 1)[0].rstrip("/").split("/")[-1]

        if filename:
            files_to_remove.append(filename)

    if proof_url:
        path = proof_url.split("?", 1)[0].rstrip("/")
        parts = path.split("/")

        if len(parts) >= 2:
            files_to_remove.append(f"{parts[-2]}/{parts[-1]}")

    if files_to_remove:
        try:
            client.storage.from_("property-images").remove(
                files_to_remove
            )
        except Exception:
            app.logger.exception(
                "Supabase upload cleanup failed."
            )


# =========================================================
# FLASK-LOGIN
# =========================================================

login_manager = LoginManager()
login_manager.init_app(app)

login_manager.login_view = "login"

login_manager.login_message = "Please log in to continue."

class CompatConnection(psycopg.Connection):
    """Lets the existing code keep calling cursor(dictionary=True)."""

    def cursor(self, *args, dictionary=False, **kwargs):
        kwargs.setdefault("row_factory", dict_row if dictionary else tuple_row)
        return super().cursor(*args, **kwargs)


def get_db_connection():
    url = os.getenv("SUPABASE_DB_URL", "").strip().strip('"').strip("'")
    if not url:
        raise RuntimeError("SUPABASE_DB_URL is missing. Check your .env file.")

    connection = CompatConnection.connect(url, connect_timeout=15)
    connection.execute("SET search_path TO civicnest")
    connection.commit()
    return connection


def _transport_row_to_dict(cursor, row):
    if row is None:
        return None

    if isinstance(row, dict):
        return row

    columns = [column.name for column in cursor.description]
    return dict(zip(columns, row))


def _transport_fetchone(cursor):
    return _transport_row_to_dict(cursor, cursor.fetchone())


def _transport_fetchall(cursor):
    return [
        _transport_row_to_dict(cursor, row)
        for row in cursor.fetchall()
    ]


def get_supabase_connection():
    """Kept so old code keeps working. It is now the same connection."""
    return get_db_connection()


@app.route("/test-supabase")
def test_supabase():
    connection = None
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_database(), current_schema(), (SELECT COUNT(*) FROM users)"
            )
            db, schema, users = cursor.fetchone()
        return {"status": "success", "database": db, "schema": schema, "users": users}
    except Exception:
        app.logger.exception("Supabase connection test failed")
        return {"status": "error", "message": "Connection failed. Check the terminal logs."}, 500
    finally:
        if connection:
            connection.close()

def _send_telegram(text):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        response = requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
        return response.status_code == 200
    except Exception as e:
        print("TELEGRAM ERROR:", e)
        return False

def notify_admin_listing(property_title, landlord_name, location):
    text = (
        f"🚨 <b>New Property Pending Approval!</b>\n\n"
        f"<b>Title:</b> {property_title}\n"
        f"<b>Landlord:</b> {landlord_name}\n"
        f"<b>Location:</b> {location}\n\n"
        f"Log into the CivicNest admin dashboard to review and publish it."
    )
    _send_telegram(text)   

import requests

def notify_tenant_lead(property_title, landlord_name, contact_method,
                       tenant_phone=None, tenant_info=None, message_text=None):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return

    esc = lambda v: html.escape(str(v or ""))
    lines = [
        "🚨 <b>NEW TENANT LEAD!</b>",
        "",
        f"🏠 <b>Property:</b> {esc(property_title)}",
        f"👤 <b>Landlord:</b> {esc(landlord_name)}",
        f"📞 <b>Method:</b> {esc(contact_method)}",
    ]
    if tenant_info:
        lines.append(f"🙋 <b>Tenant:</b> {esc(tenant_info)}")
    if tenant_phone:
        lines.append(f"📱 <b>Tenant Contact:</b> {esc(tenant_phone)}")
    if message_text:
        lines.append(f"💬 <b>Message:</b> {esc(message_text[:500])}")

    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": "\n".join(lines),
                "parse_mode": "HTML",
            },
            timeout=5,
        )
    except Exception:
        app.logger.exception("TELEGRAM LEAD ERROR")        


def allowed_file(filename):

    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower()
        in ALLOWED_EXTENSIONS
    )


def normalize_whatsapp_number(phone):
    digits = re.sub(r"\D", "", phone or "")

    if digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = "254" + digits[1:]

    if not 7 <= len(digits) <= 15:
        return None

    return digits


def parse_roommate_form():
    form = request.form
    campus = form.get("campus", "").strip()
    preferred_location = form.get("preferred_location", "").strip()
    phone = form.get("phone", "").strip()
    whatsapp_phone = normalize_whatsapp_number(phone)
    accommodation_type = form.get("accommodation_type", "").strip()
    gender_preference = form.get("gender_preference", "any").strip()
    move_in_date = form.get("move_in_date", "").strip()
    budget_min_raw = form.get("budget_min", "").strip()
    budget_max_raw = form.get("budget_max", "").strip()
    people_needed_raw = form.get("people_needed", "1").strip()
    lifestyle_preferences = form.get("lifestyle_preferences", "").strip()
    study_preferences = form.get("study_preferences", "").strip()
    bio = form.get("bio", "").strip()
    allowed_types = {
        "",
        "Single Room",
        "Bedsitter",
        "Apartment",
        "House",
        "Hostel",
        "Other",
    }

    if len(campus) > 200 or len(preferred_location) > 255:
        return None, "Campus or location is too long."
    if not campus and not preferred_location:
        return None, "Enter a campus or preferred location so students can find you."
    if not whatsapp_phone:
        return None, "Enter a valid WhatsApp phone number, including its country code if needed."
    if accommodation_type not in allowed_types:
        return None, "Select a valid accommodation type."
    if gender_preference not in {"any", "male", "female"}:
        return None, "Select a valid roommate gender preference."

    try:
        budget_min = Decimal(budget_min_raw) if budget_min_raw else None
        budget_max = Decimal(budget_max_raw) if budget_max_raw else None
        if any(
            value is not None and (not value.is_finite() or value < 0)
            for value in (budget_min, budget_max)
        ):
            raise InvalidOperation
        if (
            budget_min is not None
            and budget_max is not None
            and budget_max < budget_min
        ):
            return None, "Maximum budget must be greater than or equal to minimum budget."
    except InvalidOperation:
        return None, "Enter a valid non-negative budget."

    try:
        people_needed = int(people_needed_raw)
    except ValueError:
        return None, "Enter a valid number of roommates."
    if not 1 <= people_needed <= 100:
        return None, "People needed must be between 1 and 100."

    if move_in_date:
        try:
            move_in_date = date.fromisoformat(move_in_date).isoformat()
        except ValueError:
            return None, "Enter a valid move-in date."

    if any(
        len(value) > limit
        for value, limit in (
            (accommodation_type, 100),
            (lifestyle_preferences, 4000),
            (study_preferences, 4000),
            (bio, 4000),
        )
    ):
        return None, "One or more profile fields are too long."

    return {
        "campus": campus,
        "preferred_location": preferred_location,
        "phone": phone,
        "whatsapp_phone": whatsapp_phone,
        "budget_min": budget_min,
        "budget_max": budget_max,
        "accommodation_type": accommodation_type or None,
        "move_in_date": move_in_date or None,
        "people_needed": people_needed,
        "gender_preference": gender_preference,
        "lifestyle_preferences": lifestyle_preferences,
        "study_preferences": study_preferences,
        "bio": bio,
    }, None


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user.role != "admin":
            flash("Administrator access is required.", "error")
            return redirect(url_for("dashboard"))
        return view(*args, **kwargs)

    return wrapped


# =========================================================
# USER MODEL
# =========================================================

class User(UserMixin):

    def __init__(
        self,
        user_id,
        full_name,
        email,
        phone,
        password_hash,
        role,
        profile_image,
        is_verified
    ):

        self.id = user_id
        self.full_name = full_name
        self.email = email
        self.phone = phone
        self.password_hash = password_hash
        self.role = role
        self.profile_image = profile_image
        self.is_verified = is_verified

# =========================================================
# LOAD USER
# =========================================================

@login_manager.user_loader
def load_user(user_id):
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return None

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, full_name, email, phone, password_hash, role,
                   profile_image, is_verified, is_active
            FROM users
            WHERE id = %s
            """,
            (user_id,)
        )
        row = cursor.fetchone()
        if not row or not row["is_active"]:
            return None
        return User(
            row["id"], row["full_name"], row["email"], row["phone"],
            row["password_hash"], row["role"], row["profile_image"],
            row["is_verified"]
        )
    except Exception:
        app.logger.exception("LOAD USER ERROR")
        return None
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()




# =========================================================
# HOME
# =========================================================


def get_active_properties(limit, category=None, listing_type="rent"):
    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        query = """
            SELECT
                p.id, p.title, p.property_type, p.description,
                CASE WHEN p.location = 'Other'
                     THEN COALESCE(NULLIF(p.location_other, ''), 'Other')
                     ELSE p.location END AS location,
                p.campus, p.price, p.deposit, p.distance_from_campus,
                p.total_units, p.vacant_units, p.occupied_units,
                p.furnished, p.available, p.is_verified, p.status,
                p.listing_type, p.bedrooms, p.bathrooms, p.size_sqm,
                (
                    SELECT pi.filename
                    FROM property_images pi
                    WHERE pi.property_id = p.id
                    ORDER BY pi.is_cover DESC, pi.id ASC
                    LIMIT 1
                ) AS cover_image
            FROM properties p
            WHERE p.status = 'active'
              AND p.available = TRUE
        """
        params = []

        if listing_type:
            query += " AND p.listing_type = %s"
            params.append(listing_type)

        if category == "hostels":
            query += " AND p.property_type = %s"
            params.append("hostel")
        elif category == "rentals":
            query += " AND p.property_type <> %s"
            params.append("hostel")

        query += " ORDER BY p.created_at DESC LIMIT %s"
        params.append(limit)
        cursor.execute(query, tuple(params))
        return cursor.fetchall()
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@app.route("/")
def home():
    try:
        properties = get_active_properties(12, listing_type=None)
        return render_template("index.html", properties=properties)
    except Exception:
        app.logger.exception("HOME PAGE ERROR")
        return render_template("index.html", properties=[])            


@app.route("/rent")
def rent_page():
    category = request.args.get("category")
    if category not in {"hostels", "rentals"}:
        category = None

    try:
        properties = get_active_properties(48, category)
        return render_template(
            "rent.html",
            market="rent",
            properties=properties,
            properties_error=False,
            category=category
        )
    except Exception as e:
        print("RENT MARKETPLACE ERROR:", e)
        return render_template(
            "rent.html",
            market="rent",
            properties=[],
            properties_error=True,
            category=category
        ), 500


@app.route("/buy")
def buy_page():
    try:
        properties = get_active_properties(48, listing_type="sale")
        error = False
    except Exception as e:
        print("BUY MARKETPLACE ERROR:", e)
        properties, error = [], True
    return render_template(
        "buy.html",
        market="buy",
        properties=properties,
        properties_error=error
    )


@app.route("/sell")
def sell_page():
    if not current_user.is_authenticated:
        return redirect(url_for(
            "login", role="landlord", next=url_for("add_property")
        ))
    if current_user.role not in ("landlord", "admin"):
        flash("Listing properties is for landlord accounts.", "error")
        return redirect(url_for("home"))
    return redirect(url_for("add_property"))

@app.route("/invest")
def invest_page():
    return render_template(
        "invest.html",
        market="invest",
        properties=[],
        properties_error=False
    )

# =========================================================
# REGISTER
# =========================================================
@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "student")

        if role not in ("student", "landlord"):
            role = "student"

        back = (
            url_for("register", role="landlord")
            if role == "landlord"
            else url_for("register")
        )

        if not full_name or not email or not password:
            flash("Please fill in all required fields.", "error")
            return redirect(back)

        if len(password) < 8:
            flash("Password must contain at least 8 characters.", "error")
            return redirect(back)

        if password != request.form.get("confirm_password", ""):
            flash("Passwords do not match.", "error")
            return redirect(back)

        connection = None
        cursor = None

        try:
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)

            cursor.execute(
                "SELECT id FROM users WHERE LOWER(email) = LOWER(%s)",
                (email,)
            )
            if cursor.fetchone():
                flash("An account with that email already exists.", "error")
                return redirect(back)

            password_hash = generate_password_hash(password)

            cursor.execute(
                """
                INSERT INTO users (
                    full_name, email, phone, password_hash, role,
                    is_verified, is_active, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, FALSE, TRUE, NOW(), NOW())
                RETURNING id
                """,
                (full_name, email, phone or None, password_hash, role)
            )
            user_id = cursor.fetchone()["id"]
            connection.commit()

        except Exception as e:
            if connection:
                connection.rollback()
            print("REGISTER ERROR:", e)
            flash("Unable to create your account right now.", "error")
            return redirect(back)

        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()

        user = User(
            user_id, full_name, email, phone, password_hash,
            role, None, False
        )
        login_user(user)
        return redirect(url_for("dashboard"))

    return render_template(
        "register.html",
        selected_role=(
            "landlord"
            if request.args.get("role") == "landlord"
            else "student"
        )
    )

def get_conn():
    # If you already have a connection helper, use that instead.
    return get_db_connection()


def admin_required(f):
    # If you already have an admin decorator, use that instead.
    @wraps(f)
    @login_required
    def wrapper(*args, **kwargs):
        if getattr(current_user, "role", None) != "admin":
            abort(403)
        return f(*args, **kwargs)
    return wrapper


def fetch_places(only_active=True):
    sql = "SELECT * FROM civicnest.places"
    if only_active:
        sql += " WHERE is_active = TRUE AND status = 'approved'"
    sql += " ORDER BY (status = 'pending') DESC, created_at DESC"
    with get_db_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql)
        return cur.fetchall()

def place_form_to_dict():
    """Turn the submitted form into a dict the template can re-display."""
    f = request.form
    d = f.to_dict()
    d["amenities"] = f.getlist("amenities")
    d["delivery"] = f.get("delivery") == "on"
    d["is_verified"] = f.get("is_verified") == "on"
    d["is_active"] = f.get("is_active") == "on"
    return d


def read_admin_place_form(existing=None):
    """Validate the admin form and upload photos.
    Returns (data, error). On error, data is None."""
    f = request.form
    category = f.get("category", "").strip()
    name = f.get("name", "").strip()
    location = f.get("location", "").strip()
    phone = f.get("phone", "").strip()
    description = f.get("description", "").strip()

    if category not in VALID_CATEGORIES:
        return None, "Choose what type of place this is."
    if not name or len(name) > 120:
        return None, "Enter a name of up to 120 characters."
    if location not in SUPPORTED_TOWNS:
        return None, "Please select a valid town from the list."
    if location == "Other":
        other = f.get("location_other", "").strip()[:120]
        if len(other) < 3:
            return None, "Enter the town and country for this place."
        location = other
    if not phone or len(phone) > 30:
        return None, "Enter a valid phone number."
    if len(description) < 30:
        return None, "Write a description of at least 30 characters."

    try:
        price = Decimal(f.get("price", "").strip())
        if not price.is_finite() or price <= 0 or price > Decimal("9999999999"):
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        return None, "Enter a valid price."

    rooms = None
    if category != "restaurant" and f.get("rooms", "").strip():
        try:
            rooms = int(f.get("rooms"))
            if not 1 <= rooms <= 5000:
                raise ValueError
        except ValueError:
            return None, "Enter a valid number of rooms."

    website = f.get("website", "").strip()[:255] or None
    if website:
        if "://" in website and not website.lower().startswith(("http://", "https://")):
            return None, "The website must start with http:// or https://."
        if "://" not in website:
            website = "https://" + website

    cover_url = f.get("cover_image", "").strip()[:500] or None
    if cover_url and not cover_url.lower().startswith(("http://", "https://")):
        return None, "The cover image URL must start with http:// or https://."

    new_files = [p for p in request.files.getlist("photos") if p and p.filename]
    if len(new_files) > 5:
        return None, "You can add up to 5 photos."
    if not all(allowed_file(p.filename) for p in new_files):
        return None, "Only JPG, PNG and WEBP photos are allowed."

    old_photos = list((existing or {}).get("photos") or [])
    old_cover = (existing or {}).get("cover_image")
    if not new_files and not (cover_url or old_cover):
        return None, "Add at least one photo or a cover image URL."

    # Upload last, after everything else has been validated
    uploaded = []
    try:
        for p in new_files:
            uploaded.append(save_photo(p))
    except ValueError as exc:
        remove_uploads(uploaded)
        return None, str(exc)
    except Exception:
        app.logger.exception("Photo upload failed in admin place form.")
        remove_uploads(uploaded)
        return None, "We could not upload the photos. Please try again."

    if uploaded:
        photos, cover = uploaded, uploaded[0]
    else:
        photos = old_photos
        cover = cover_url or old_cover

    return {
        "name": name,
        "category": category,
        "location": location,
        "price": price,
        "phone": phone,
        "description": description,
        "cover_image": cover,
        "photos": photos,
        "website": website,
        "rooms": rooms,
        "check_in_time": f.get("check_in_time", "").strip()[:60] or None,
        "amenities": ", ".join(f.getlist("amenities"))[:500] or None,
        "cuisine": f.get("cuisine", "").strip()[:120] or None,
        "opening_hours": f.get("opening_hours", "").strip()[:150] or None,
        "delivery": f.get("delivery") == "on",
        "is_verified": f.get("is_verified") == "on",
        "is_active": f.get("is_active") == "on",
        "_uploaded": uploaded,   # used only for cleanup, not saved
    }, None


# ---------- Public page ----------
@app.route("/stay-and-dine")
def hospitality_page():
    return render_template("hospitality.html", places=fetch_places(only_active=True))

@app.route("/stay-and-dine/<int:place_id>")
def hospitality_details(place_id):
    connection = None
    cursor = None

    viewer_role = current_user.role if current_user.is_authenticated else ""
    viewer_id = str(current_user.id) if current_user.is_authenticated else ""

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT *
            FROM civicnest.places
            WHERE id = %s
            AND (
                (is_active = TRUE AND status = 'approved')
                OR owner_id = %s
                OR %s = 'admin'
            )
            LIMIT 1
            """,
            (place_id, viewer_id, viewer_role)
        )

        place = cursor.fetchone()

        if not place:
            flash("This listing was not found or is no longer available.", "error")
            return redirect(url_for("hospitality_page"))

        return render_template(
            "hospitality_details.html",
            place=place
        )

    except Exception:
        app.logger.exception("HOSPITALITY DETAILS ERROR")
        flash("Unable to load this listing right now.", "error")
        return redirect(url_for("hospitality_page"))

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()    


# ---------- Admin ----------
@app.route("/admin/places")
@admin_required
def admin_places():
    return render_template(
        "admin_places.html",
        places=fetch_places(only_active=False),
        categories=dict(PLACE_CATEGORIES),
    )


@app.route("/admin/places/add", methods=["GET", "POST"])
@admin_required
def admin_place_add():
    def show(place, status=200):
        return render_template(
            "admin_place_form.html", place=place,
            categories=PLACE_CATEGORIES, towns=get_towns(), editing=False,
        ), status

    if request.method == "GET":
        return show({"is_active": True})

    data, error = read_admin_place_form()
    if error:
        flash(error, "error")
        return show(place_form_to_dict(), 400)

    uploaded = data.pop("_uploaded")
    data["status"] = "approved"          # admin-added places go live
    data["owner_role"] = "owner"
    data["owner_id"] = str(current_user.id)

    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO civicnest.places (
                    name, category, location, price, phone, description,
                    cover_image, photos, website, wants_website, rooms,
                    check_in_time, amenities, cuisine, opening_hours,
                    delivery, owner_role, owner_id, status,
                    is_verified, is_active
                )
                VALUES (
                    %(name)s, %(category)s, %(location)s, %(price)s, %(phone)s,
                    %(description)s, %(cover_image)s, %(photos)s, %(website)s,
                    FALSE, %(rooms)s, %(check_in_time)s, %(amenities)s,
                    %(cuisine)s, %(opening_hours)s, %(delivery)s,
                    %(owner_role)s, %(owner_id)s, %(status)s,
                    %(is_verified)s, %(is_active)s
                )
                """,
                data,
            )
    except Exception:
        app.logger.exception("Admin could not save the place.")
        try:
            remove_uploads(uploaded)
        except Exception:
            pass
        flash("Something went wrong while saving. Please try again.", "error")
        return show(place_form_to_dict(), 500)

    flash("Place added.", "success")
    return redirect(url_for("admin_places"))


@app.route("/admin/places/<int:place_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_place_edit(place_id):
    with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select * from civicnest.places where id = %s", (place_id,))
        place = cur.fetchone()
    if not place:
        abort(404)

    def show(p, status=200):
        return render_template(
            "admin_place_form.html", place=p,
            categories=PLACE_CATEGORIES, towns=get_towns(),
            editing=True, place_id=place_id,
        ), status

    if request.method == "GET":
        # amenities are stored as "Wi-Fi, Parking"; the form wants a list
        place["amenities"] = [
            a.strip() for a in (place.get("amenities") or "").split(",") if a.strip()
        ]
        return show(place)

    data, error = read_admin_place_form(existing=place)
    if error:
        flash(error, "error")
        return show(place_form_to_dict(), 400)

    uploaded = data.pop("_uploaded")
    data["id"] = place_id

    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE civicnest.places SET
                    name=%(name)s, category=%(category)s, location=%(location)s,
                    price=%(price)s, phone=%(phone)s, description=%(description)s,
                    cover_image=%(cover_image)s, photos=%(photos)s,
                    website=%(website)s, rooms=%(rooms)s,
                    check_in_time=%(check_in_time)s, amenities=%(amenities)s,
                    cuisine=%(cuisine)s, opening_hours=%(opening_hours)s,
                    delivery=%(delivery)s, is_verified=%(is_verified)s,
                    is_active=%(is_active)s
                WHERE id=%(id)s
                """,
                data,
            )
    except Exception:
        app.logger.exception("Admin could not update the place.")
        try:
            remove_uploads(uploaded)
        except Exception:
            pass
        flash("Something went wrong while saving. Please try again.", "error")
        return show(place_form_to_dict(), 500)

    flash("Place updated.", "success")
    return redirect(url_for("admin_places"))


@app.route("/admin/places/<int:place_id>/toggle", methods=["POST"])
@admin_required
def admin_place_toggle(place_id):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "update civicnest.places set is_active = not is_active where id = %s",
            (place_id,),
        )
    return redirect(url_for("admin_places"))


@app.route("/admin/places/<int:place_id>/delete", methods=["POST"])
@admin_required
def admin_place_delete(place_id):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("delete from civicnest.places where id = %s", (place_id,))
    flash("Place deleted.", "success")
    return redirect(url_for("admin_places"))

def notify_admin_place(name, category, location, owner_name, phone,
                       website, wants_website):
    esc = lambda v: html.escape(str(v or ""))
    lines = [
        "🏨 <b>New Stay &amp; Dine listing pending!</b>",
        "",
        f"<b>Name:</b> {esc(name)}",
        f"<b>Type:</b> {esc(dict(PLACE_CATEGORIES).get(category, category))}",
        f"<b>Location:</b> {esc(location)}",
        f"<b>Owner:</b> {esc(owner_name)}",
        f"<b>Phone:</b> {esc(phone)}",
    ]
    if website:
        lines.append(f"<b>Website:</b> {esc(website)}")
    if wants_website:
        lines.append("🌐 <b>Wants a website built</b>")
    lines += ["", "Open /admin/places to review and approve it."]
    _send_telegram("\n".join(lines))


def render_place_form(status=200):
    saved = (
        {k: request.form.getlist(k) for k in request.form}
        if request.method == "POST" else {}
    )
    return render_template(
        "list_place.html", towns=SUPPORTED_TOWNS, saved=saved
    ), status


@app.route("/stay-and-dine/list", methods=["GET", "POST"])
def list_place():
    if not current_user.is_authenticated:
        return redirect(url_for(
            "login", role="landlord", next=url_for("list_place")
        ))
    if current_user.role not in ("landlord", "admin"):
        flash("Listing is for owner accounts. Sign in with a landlord account.", "error")
        return redirect(url_for("hospitality_page"))

    if request.method == "GET":
        return render_place_form()

    def fail(message):
        flash(message, "error")
        return render_place_form(400)

    def cleanup(urls):
        try:
            remove_uploads(urls)
        except Exception:
            app.logger.exception("Could not clean up place photos.")

    f = request.form
    category = f.get("category", "").strip()
    name = f.get("name", "").strip()
    location = f.get("location", "").strip()
    phone = f.get("phone", "").strip()
    description = f.get("description", "").strip()
    ownership_role = f.get("ownership_role", "").strip()

    if category not in VALID_CATEGORIES:
        return fail("Choose what you are listing.")
    if not name or len(name) > 120:
        return fail("Enter a name of up to 120 characters.")
    if location not in SUPPORTED_TOWNS:
        return fail("Please select a valid town from the list.")
    if location == "Other":
        other = f.get("location_other", "").strip()[:120]
        if len(other) < 3:
            return fail("Enter the town and country for this place.")
        location = other
    if not phone or len(phone) > 30:
        return fail("Enter a valid phone number.")
    if len(description) < 30:
        return fail("Write a description of at least 30 characters.")
    if ownership_role not in {"owner", "agent"}:
        return fail("Say whether you are the owner or an authorized manager.")

    try:
        price = Decimal(f.get("price", "").strip())
        if not price.is_finite() or price <= 0 or price > Decimal("9999999999"):
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        return fail("Enter a valid price.")

    rooms = None
    if category != "restaurant" and f.get("rooms", "").strip():
        try:
            rooms = int(f.get("rooms"))
            if not 1 <= rooms <= 5000:
                raise ValueError
        except ValueError:
            return fail("Enter a valid number of rooms.")

    website = f.get("website", "").strip()[:255] or None
    if website:
        if "://" in website and not website.lower().startswith(("http://", "https://")):
            return fail("The website must start with http:// or https://.")
        if "://" not in website:
            website = "https://" + website

    photos = [p for p in request.files.getlist("photos") if p and p.filename]
    if not photos:
        return fail("Add at least one photo.")
    if len(photos) > 5:
        return fail("You can add up to 5 photos.")
    if not all(allowed_file(p.filename) for p in photos):
        return fail("Only JPG, PNG and WEBP photos are allowed.")

    saved_photos = []
    try:
        for photo in photos:
            saved_photos.append(save_photo(photo))
    except ValueError as exc:
        cleanup(saved_photos)
        return fail(str(exc))
    except Exception:
        app.logger.exception("Supabase upload failed while listing a place.")
        cleanup(saved_photos)
        return fail("We could not upload your photos. Please try again later.")

    is_admin = current_user.role == "admin"
    wants_website = f.get("wants_website") == "on"
    data = {
        "name": name,
        "category": category,
        "location": location,
        "price": price,
        "phone": phone,
        "description": description,
        "cover_image": saved_photos[0],
        "photos": saved_photos,
        "website": website,
        "wants_website": wants_website,
        "rooms": rooms,
        "check_in_time": f.get("check_in_time", "").strip()[:60] or None,
        "amenities": ", ".join(f.getlist("amenities"))[:500] or None,
        "cuisine": f.get("cuisine", "").strip()[:120] or None,
        "opening_hours": f.get("opening_hours", "").strip()[:150] or None,
        "delivery": f.get("delivery") == "on",
        "owner_role": ownership_role,
        "owner_id": str(current_user.id),
        "status": "approved" if is_admin else "pending",
    }

    try:
        with get_db_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO civicnest.places (
                    name, category, location, price, phone, description,
                    cover_image, photos, website, wants_website, rooms,
                    check_in_time, amenities, cuisine, opening_hours,
                    delivery, owner_role, owner_id, status,
                    is_verified, is_active
                )
                VALUES (
                    %(name)s, %(category)s, %(location)s, %(price)s, %(phone)s,
                    %(description)s, %(cover_image)s, %(photos)s, %(website)s,
                    %(wants_website)s, %(rooms)s, %(check_in_time)s,
                    %(amenities)s, %(cuisine)s, %(opening_hours)s,
                    %(delivery)s, %(owner_role)s, %(owner_id)s, %(status)s,
                    FALSE, TRUE
                )
                """,
                data,
            )
    except Exception:
        app.logger.exception("Failed to save the place listing.")
        cleanup(saved_photos)
        return fail("Something went wrong while saving the listing. Please try again.")

    if not is_admin:
        try:
            notify_admin_place(
                name, category, location, current_user.full_name,
                phone, website, wants_website
            )
        except Exception:
            app.logger.exception("Telegram notification failed for a place.")

    flash(
        "Your place is now live." if is_admin else
        "Thanks! Your place was sent for review. It will appear once approved.",
        "success",
    )
    return redirect(url_for("hospitality_page"))


@app.route("/admin/places/<int:place_id>/status/<status>", methods=["POST"])
@admin_required
def admin_place_status(place_id, status):
    if status not in ("approved", "rejected"):
        abort(400)
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE civicnest.places SET status = %s WHERE id = %s",
            (status, place_id),
        )
    flash("Place " + status + ".", "success")
    return redirect(url_for("admin_places"))    


def get_towns():
    return SUPPORTED_TOWNS if "SUPPORTED_TOWNS" in globals() else []

# =========================================================
# LOGIN
# =========================================================

@app.route("/login", methods=["GET", "POST"])
def login():
    requested_role = request.values.get("role")
    if requested_role != "landlord":
        requested_role = None

    next_url = request.form.get("next") or request.args.get("next")
    if next_url:
        parsed_next_url = urlsplit(next_url)
        if (
            not next_url.startswith("/")
            or next_url.startswith("//")
            or "\\" in next_url
            or parsed_next_url.scheme
            or parsed_next_url.netloc
        ):
            next_url = None

    login_args = {}
    if requested_role:
        login_args["role"] = requested_role
    if next_url:
        login_args["next"] = next_url

    if current_user.is_authenticated:
        if requested_role and current_user.role not in (requested_role, "admin"):
            flash(
                "Please sign in with a landlord account to list a property.",
                "error"
            )
            return redirect(url_for("sell_page"))
        if next_url:
            return redirect(next_url)
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        connection = None
        cursor = None
        user_data = None

        try:
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, full_name, email, phone, password_hash, role,
                       profile_image, is_verified, is_active
                FROM users
                WHERE LOWER(email) = LOWER(%s)
                LIMIT 1
                """,
                (email,)
            )
            user_data = cursor.fetchone()

        except Exception as e:
            print("LOGIN ERROR:", e)
            flash("Unable to log in right now.", "error")
            return redirect(url_for("login", **login_args))

        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()

        if not user_data or not check_password_hash(user_data["password_hash"], password):
            flash("Invalid email or password.", "error")
            return redirect(url_for("login", **login_args))

        if not user_data["is_active"]:
            flash("This account has been suspended. Please contact CivicNest support.", "error")
            return redirect(url_for("login", **login_args))

        if requested_role and user_data["role"] not in (requested_role, "admin"):
            flash(
                "Please sign in with a landlord account to list a property.",
                "error"
            )
            return redirect(url_for("login", **login_args))

        user = User(
            user_data["id"], user_data["full_name"], user_data["email"],
            user_data["phone"], user_data["password_hash"], user_data["role"],
            user_data["profile_image"], user_data["is_verified"]
        )
        login_user(user)

        if next_url:
            return redirect(next_url)
        return redirect(url_for("dashboard"))

    return render_template(
        "login.html",
        requested_role=requested_role,
        next_url=next_url
    )

@app.route("/property/<int:property_id>/track-contact/<method>")
def track_contact(property_id, method):
    if method not in {"call", "whatsapp"}:
        abort(404)

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT p.title, u.full_name AS landlord_name, u.phone AS landlord_phone
            FROM properties p
            JOIN users u ON p.landlord_id::text = u.id::text
            WHERE p.id = %s
            """,
            (property_id,)
        )
        prop = cursor.fetchone()

        if prop:
            notify_tenant_lead(
                property_title=prop["title"],
                landlord_name=prop["landlord_name"],
                contact_method=method.upper()
            )

            phone = normalize_whatsapp_number(prop.get("landlord_phone"))
            if method == "whatsapp" and phone:
                text = quote(
                    f"Hello, I found your property '{prop['title']}' on CivicNest."
                )
                return redirect(f"https://wa.me/{phone}?text={text}")
            if method == "call" and prop.get("landlord_phone"):
                return redirect(f"tel:{prop['landlord_phone']}")

    except Exception:
        app.logger.exception("TRACK CONTACT ERROR")
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

    return redirect(url_for("property_details", property_id=property_id))

# =========================================================
# DASHBOARD ROUTER
# =========================================================

@app.route("/dashboard")
@login_required
def dashboard():

    if current_user.role == "landlord":

        return redirect(
            url_for("landlord_dashboard")
        )

    if current_user.role == "admin":

        return redirect(
            url_for("admin_dashboard")
        )

    return redirect(
        url_for("home")
    )


# =========================================================
# LANDLORD DASHBOARD
# =========================================================

@app.route("/landlord/dashboard")
@login_required
def landlord_dashboard():
    if current_user.role not in ("landlord", "admin"):
        flash(
            "Sign in with a landlord account to manage property listings.",
            "error"
        )
        return redirect(url_for("sell_page"))

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(row_factory=dict_row)

        user_id_str = str(current_user.id)

        cursor.execute(
            """
            SELECT COUNT(*) AS total_properties
            FROM properties
            WHERE landlord_id::text = %s
            """,
            (user_id_str,)
        )
        total_properties = cursor.fetchone()["total_properties"]

        cursor.execute(
            """
            SELECT COUNT(*) AS active_listings
            FROM properties
            WHERE landlord_id::text = %s
            AND status = 'active'
            """,
            (user_id_str,)
        )
        active_listings = cursor.fetchone()["active_listings"]

        cursor.execute(
            """
            SELECT COUNT(*) AS new_inquiries
            FROM inquiries i
            INNER JOIN properties p
                ON i.property_id = p.id
            WHERE p.landlord_id::text = %s
            AND i.status = 'new'
            """,
            (user_id_str,)
        )
        new_inquiries = cursor.fetchone()["new_inquiries"]

        cursor.execute(
            """
            SELECT
                p.id,
                p.title,
                p.property_type,
                p.description,
                CASE WHEN p.location = 'Other'
                     THEN COALESCE(NULLIF(p.location_other, ''), 'Other')
                     ELSE p.location END AS location,
                p.campus,
                p.price,
                p.deposit,
                p.total_units,
                p.vacant_units,
                p.occupied_units,
                p.available,
                p.is_verified,
                p.status,
                p.created_at,
                p.listing_type,
                p.rejection_reason,
                (
                    SELECT pi.filename
                    FROM property_images pi
                    WHERE pi.property_id = p.id
                    ORDER BY pi.is_cover DESC, pi.id ASC
                    LIMIT 1
                ) AS cover_image
            FROM properties p
            WHERE p.landlord_id::text = %s
            ORDER BY p.created_at DESC
            """,
            (user_id_str,)
        )
        properties = cursor.fetchall()

        cursor.execute(
            """
            SELECT COUNT(*) AS total_inquiries
            FROM inquiries i
            INNER JOIN properties p
                ON i.property_id = p.id
            WHERE p.landlord_id::text = %s
            """,
            (user_id_str,)
        )
        total_inquiries = cursor.fetchone()["total_inquiries"]

        cursor.execute(
            """
            SELECT
                i.id,
                i.message,
                i.status,
                i.created_at,
                u.full_name AS seeker_name,
                u.email AS seeker_email,
                u.phone AS seeker_phone,
                p.id AS property_id,
                p.title AS property_title
            FROM inquiries i
            INNER JOIN users u
                ON i.student_id = u.id
            INNER JOIN properties p
                ON i.property_id = p.id
            WHERE p.landlord_id::text = %s
            ORDER BY i.created_at DESC
            LIMIT 20
            """,
            (user_id_str,)
        )
        inquiries = cursor.fetchall()

        cursor.execute(
            """
            SELECT
                COALESCE(SUM(total_units), 0) AS total_units,
                COALESCE(SUM(vacant_units), 0) AS vacant_units,
                COALESCE(SUM(occupied_units), 0) AS occupied_units
            FROM properties
            WHERE landlord_id::text = %s
            AND status != 'removed'
            """,
            (user_id_str,)
        )
        unit_totals = cursor.fetchone()

        total_units = unit_totals["total_units"] or 0
        vacant_units = unit_totals["vacant_units"] or 0
        occupied_units = unit_totals["occupied_units"] or 0

        return render_template(
            "landlord_dashboard.html",
            total_properties=total_properties,
            active_listings=active_listings,
            new_inquiries=new_inquiries,
            total_inquiries=total_inquiries,
            properties=properties,
            inquiries=inquiries,
            total_units=total_units,
            vacant_units=vacant_units,
            occupied_units=occupied_units
        )

    except Exception:
        app.logger.exception("LANDLORD DASHBOARD ERROR")
        flash("Unable to load your dashboard right now.", "error")
        return render_template(
            "landlord_dashboard.html",
            total_properties=0,
            active_listings=0,
            new_inquiries=0,
            total_inquiries=0,
            properties=[],
            inquiries=[],
            total_units=0,
            vacant_units=0,
            occupied_units=0
        )

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# =========================================================
# UPDATE PROPERTY AVAILABILITY
# =========================================================

@app.route(
    "/landlord/property/<int:property_id>/availability",
    methods=["POST"]
)
@login_required
def update_property_availability(property_id):
    if current_user.role not in ("landlord", "admin"):
        flash(
            "Only landlords can update property availability.",
            "error"
        )
        return redirect(
            url_for("dashboard")
        )

    total_units_raw = request.form.get(
        "total_units",
        ""
    ).strip()

    vacant_units_raw = request.form.get(
        "vacant_units",
        ""
    ).strip()

    try:
        total_units = int(
            total_units_raw
        )
        vacant_units = int(
            vacant_units_raw
        )
    except ValueError:
        flash(
            "Please enter valid whole numbers for the unit counts.",
            "error"
        )
        return redirect(
            url_for("landlord_dashboard")
        )

    if total_units < 1:
        flash(
            "A property must have at least 1 unit.",
            "error"
        )
        return redirect(
            url_for("landlord_dashboard")
        )

    if vacant_units < 0:
        flash(
            "Vacant units cannot be negative.",
            "error"
        )
        return redirect(
            url_for("landlord_dashboard")
        )

    if vacant_units > total_units:
        flash(
            "Vacant units cannot be greater than total units.",
            "error"
        )
        return redirect(
            url_for("landlord_dashboard")
        )

    occupied_units = (
        total_units - vacant_units
    )

    available = (
        vacant_units > 0
    )

    connection = None
    cursor = None
    user_id_str = str(current_user.id)

    try:
        connection = get_db_connection()
        cursor = connection.cursor(
            dictionary=True
        )

        cursor.execute(
            """
            SELECT
                id,
                title,
                status

            FROM properties

            WHERE id = %s
            AND landlord_id::text = %s

            LIMIT 1
            """,
            (
                property_id,
                user_id_str
            )
        )

        property_data = cursor.fetchone()

        if not property_data:
            flash(
                "Property not found or you do not have permission to edit it.",
                "error"
            )
            return redirect(
                url_for("landlord_dashboard")
            )

        cursor.execute(
            """
            UPDATE properties

            SET
                total_units = %s,
                vacant_units = %s,
                occupied_units = %s,
                available = %s,
                updated_at = NOW()

            WHERE id = %s
            AND landlord_id::text = %s
            """,
            (
                total_units,
                vacant_units,
                occupied_units,
                available,
                property_id,
                user_id_str
            )
        )

        connection.commit()

        if vacant_units == 0:
            flash(
                f"{property_data['title']} is now fully occupied.",
                "info"
            )
        else:
            flash(
                f"Availability updated successfully. "
                f"{vacant_units} unit(s) are vacant and "
                f"{occupied_units} unit(s) are occupied.",
                "success"
            )

        return redirect(
            url_for("landlord_dashboard")
        )

    except Exception as e:
        if connection:
            connection.rollback()

        print(
            "UPDATE AVAILABILITY ERROR:",
            e
        )
        flash(
            "Unable to update property availability.",
            "error"
        )
        return redirect(
            url_for("landlord_dashboard")
        )

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# =========================================================
# PROPERTY DETAILS
# =========================================================

@app.route("/landlord/property/<int:property_id>/edit", methods=["GET", "POST"])
@login_required
def edit_property(property_id):
    if current_user.role not in ("landlord", "admin"):
        flash("Only landlords can edit properties.", "error")
        return redirect(url_for("dashboard"))

    uploaded_urls = []
    connection = None
    cursor = None
    owner_id = str(current_user.id)
    is_admin = current_user.role == "admin"

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT id, landlord_id, title, property_type, description, location,
                   location_other, campus, price, deposit, distance_from_campus,
                   furnished, total_units, vacant_units, occupied_units,
                   available, is_verified, status, listing_type, bedrooms,
                   bathrooms, size_sqm
            FROM properties
            WHERE id = %s AND (landlord_id::text = %s OR %s)
            """,
            (property_id, owner_id, is_admin)
        )
        property_data = cursor.fetchone()

        if not property_data:
            flash("Property not found or you do not have permission to edit it.", "error")
            return redirect(url_for("landlord_dashboard"))

        cursor.execute("SELECT id, name FROM amenities ORDER BY name ASC")
        amenities = cursor.fetchall()

        cursor.execute(
            "SELECT amenity_id FROM property_amenities WHERE property_id = %s",
            (property_id,)
        )
        selected_amenity_ids = {row["amenity_id"] for row in cursor.fetchall()}

        cursor.execute(
            """
            SELECT id, property_id, filename, is_cover, uploaded_at
            FROM property_images
            WHERE property_id = %s
            ORDER BY is_cover DESC, id ASC
            """,
            (property_id,)
        )
        images = cursor.fetchall()

        if request.method == "GET":
            return render_template(
                "edit_property.html",
                property=property_data,
                amenities=amenities,
                selected_amenity_ids=selected_amenity_ids,
                images=images,
                towns=SUPPORTED_TOWNS
            )

        # ---------------- POST: validate ----------------
        form = request.form
        is_rent = property_data["listing_type"] == "rent"
        title = form.get("title", "").strip()
        property_type = form.get("property_type", "").strip()
        description = form.get("description", "").strip()
        location = form.get("location", "").strip()

        def back(message):
            flash(message, "error")
            return redirect(url_for("edit_property", property_id=property_id))

        def num(name, label, cast=Decimal, maximum=9999999999,
                required=False, keep=None):
            """Parse an optional number. If the field is not in the form,
            keep the value already stored."""
            if name not in form:
                return keep
            raw = form.get(name, "").strip()
            if not raw:
                if required:
                    raise ValueError(f"Please enter a valid {label}.")
                return None
            try:
                value = cast(raw)
                if value < 0 or value > maximum:
                    raise ValueError
            except (ValueError, InvalidOperation, TypeError):
                raise ValueError(f"Please enter a valid {label}.")
            return value

        if not title or len(title) > 120:
            return back("Enter a title of up to 120 characters.")
        allowed_types = RENT_TYPES if is_rent else SALE_TYPES
        if property_type not in allowed_types:
            return back("Please select a valid property type.")
        if len(description) < 30:
            return back("Write a description of at least 30 characters.")
        if location not in SUPPORTED_TOWNS:
            return back("Please select a valid town from the list.")

        location_other = form.get("location_other", "").strip()[:120]
        if location == "Other":
            if len(location_other) < 3:
                return back("Enter the town and country for this property.")
        else:
            location_other = None

        try:
            price_value = num("price", "property price", required=True)
            if price_value is None or price_value <= 0:
                raise ValueError("Please enter a valid property price.")

            if is_rent:
                campus = form.get("campus", "").strip()[:200] or None
                deposit_value = num(
                    "deposit", "deposit amount",
                    keep=property_data["deposit"]
                )
                distance_value = num(
                    "distance_from_campus", "distance from campus",
                    cast=float, maximum=1000,
                    keep=property_data["distance_from_campus"]
                )
                try:
                    total_units_value = int(form.get("total_units", "").strip())
                    vacant_units_value = int(form.get("vacant_units", "").strip())
                except ValueError:
                    raise ValueError("Total units and vacant units must be whole numbers.")
                furnished = bool(form.get("furnished"))
                bedrooms = property_data["bedrooms"]
                bathrooms = property_data["bathrooms"]
                size_sqm = property_data["size_sqm"]
            else:
                campus = deposit_value = distance_value = None
                total_units_value = property_data["total_units"] or 1
                vacant_units_value = property_data["vacant_units"] or 0
                furnished = bool(property_data["furnished"])
                size_sqm = num(
                    "size_sqm", "size", maximum=100000000,
                    keep=property_data["size_sqm"]
                )
                if property_type == "plot":
                    bedrooms = bathrooms = None
                else:
                    bedrooms = num(
                        "bedrooms", "number of bedrooms", cast=int,
                        maximum=50, keep=property_data["bedrooms"]
                    )
                    bathrooms = num(
                        "bathrooms", "number of bathrooms", cast=int,
                        maximum=50, keep=property_data["bathrooms"]
                    )
        except ValueError as e:
            return back(str(e))

        if total_units_value < 1:
            return back("Total units must be at least 1.")
        if vacant_units_value < 0:
            return back("Vacant units cannot be negative.")
        if vacant_units_value > total_units_value:
            return back("Vacant units cannot be greater than total units.")

        occupied_units_value = total_units_value - vacant_units_value
        available_value = vacant_units_value > 0

        selected_amenities = form.getlist("amenities")
        new_files = [f for f in request.files.getlist("photos") if f and f.filename]

        if not all(allowed_file(f.filename) for f in new_files):
            return back("One or more uploaded photos have an unsupported format.")

        review_status = "active" if is_admin else "pending"
        verified_value = bool(property_data["is_verified"]) if is_admin else False

        # ---------------- UPDATE ----------------
        cursor.execute(
            """
            UPDATE properties
            SET title = %s, property_type = %s, description = %s,
                location = %s, location_other = %s, campus = %s,
                price = %s, deposit = %s,
                distance_from_campus = %s, furnished = %s,
                total_units = %s, vacant_units = %s, occupied_units = %s,
                available = %s, status = %s, is_verified = %s,
                bedrooms = %s, bathrooms = %s, size_sqm = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (
                title, property_type, description, location, location_other,
                campus, price_value, deposit_value, distance_value,
                furnished, total_units_value, vacant_units_value,
                occupied_units_value, available_value, review_status,
                verified_value, bedrooms, bathrooms, size_sqm,
                property_id
            )
        )

        # Amenities (amenity checkboxes submit ids)
        cursor.execute(
            "DELETE FROM property_amenities WHERE property_id = %s",
            (property_id,)
        )
        for amenity_id in selected_amenities:
            try:
                cursor.execute(
                    """
                    INSERT INTO property_amenities (property_id, amenity_id)
                    VALUES (%s, %s) ON CONFLICT DO NOTHING
                    """,
                    (property_id, int(amenity_id))
                )
            except (ValueError, TypeError):
                continue

        # Photos
        cursor.execute(
            "SELECT COUNT(*) AS image_count FROM property_images WHERE property_id = %s",
            (property_id,)
        )
        image_count = cursor.fetchone()["image_count"]

        if image_count + len(new_files) > MAX_PHOTOS:
            connection.rollback()
            return back(f"A listing can have at most {MAX_PHOTOS} photos. Delete some first.")

        for file in new_files:
            try:
                photo_url = save_photo(file)
            except ValueError as photo_error:
                connection.rollback()
                try:
                    remove_uploads(uploaded_urls)
                except Exception:
                    app.logger.exception("Cleanup failed")
                return back(str(photo_error))

            uploaded_urls.append(photo_url)
            cursor.execute(
                """
                INSERT INTO property_images (property_id, filename, is_cover, uploaded_at)
                VALUES (%s, %s, %s, NOW())
                """,
                (property_id, photo_url, image_count == 0)
            )
            image_count += 1

        connection.commit()

        if not is_admin:
            try:
                notify_admin_listing(
                    property_title=title,
                    landlord_name=current_user.full_name,
                    location=location_other if location == "Other" else location
                )
            except Exception:
                app.logger.exception("Telegram notify failed after edit")

        flash("Property updated successfully.", "success")
        return redirect(url_for("edit_property", property_id=property_id))

    except Exception:
        if connection:
            try:
                connection.rollback()
            except Exception:
                pass
        try:
            remove_uploads(uploaded_urls)
        except Exception:
            app.logger.exception("Cleanup failed")
        app.logger.exception("EDIT PROPERTY ERROR")
        flash("An error occurred while updating the property.", "error")
        return redirect(url_for("landlord_dashboard"))

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

# =========================================================
# PROPERTY DETAILS
# =========================================================

@app.route("/property/<int:property_id>")
def property_details(property_id):
    connection = None
    cursor = None
    viewer_role = current_user.role if current_user.is_authenticated else ""
    viewer_id = str(current_user.id) if current_user.is_authenticated else ""

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                p.id,
                p.title,
                p.property_type,
                p.description,
                CASE WHEN p.location = 'Other'
                     THEN COALESCE(NULLIF(p.location_other, ''), 'Other')
                     ELSE p.location END AS location,
                p.campus,
                p.price,
                p.deposit,
                p.distance_from_campus,

                p.total_units,
                p.vacant_units,
                p.occupied_units,

                p.furnished,
                p.available,
                p.is_verified,
                p.status,
                p.created_at,
                p.listing_type,
                p.bedrooms,
                p.bathrooms,
                p.size_sqm,

                u.id AS landlord_id,
                u.full_name AS landlord_name,
                u.phone AS landlord_phone,
                u.email AS landlord_email,
                u.profile_image AS landlord_image

            FROM properties p

            INNER JOIN users u
                ON p.landlord_id::text = u.id::text

            WHERE p.id = %s
            AND (p.status = 'active' OR %s = 'admin' OR p.landlord_id::text = %s)

            LIMIT 1
            """,
            (property_id, viewer_role, viewer_id)
        )

        property_data = cursor.fetchone()

        if not property_data:
            flash("Property not found or is no longer available.", "error")
            return redirect(url_for("home"))

        cursor.execute(
            """
            SELECT id, filename, is_cover
            FROM property_images
            WHERE property_id = %s
            ORDER BY is_cover DESC, id ASC
            """,
            (property_id,)
        )
        images = cursor.fetchall()

        cursor.execute(
            """
            SELECT a.id, a.name
            FROM amenities a
            INNER JOIN property_amenities pa
                ON a.id = pa.amenity_id
            WHERE pa.property_id = %s
            ORDER BY a.name ASC
            """,
            (property_id,)
        )
        amenities = cursor.fetchall()

        return render_template(
            "property_details.html",
            property=property_data,
            images=images,
            amenities=amenities
        )

    except Exception:
        app.logger.exception("PROPERTY DETAILS ERROR")
        flash("Unable to load this property right now.", "error")
        return redirect(url_for("home"))

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()            


# =========================================================
# SEND PROPERTY INQUIRY
# =========================================================

@app.route("/property/<int:property_id>/inquire", methods=["POST"])
@login_required
def send_inquiry(property_id):
    details_url = url_for("property_details", property_id=property_id)

    if current_user.role == "landlord":
        flash("Landlords cannot send property inquiries.", "error")
        return redirect(details_url)

    message = request.form.get("message", "").strip()

    if not message:
        flash("Please enter a message before sending your inquiry.", "error")
        return redirect(details_url)

    if len(message) > 2000:
        flash(
            "Your message is too long. Please keep it below 2,000 characters.",
            "error"
        )
        return redirect(details_url)

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                p.id, p.landlord_id, p.title, p.available, p.status,
                p.total_units, p.vacant_units, p.occupied_units,
                u.full_name AS landlord_name
            FROM properties p
            LEFT JOIN users u ON p.landlord_id::text = u.id::text
            WHERE p.id = %s
            LIMIT 1
            """,
            (property_id,)
        )
        property_data = cursor.fetchone()

        if not property_data:
            flash("Property not found.", "error")
            return redirect(url_for("home"))

        if property_data["status"] != "active" or not property_data["available"]:
            flash("This property is currently unavailable.", "error")
            return redirect(details_url)

        if (property_data["vacant_units"] or 0) <= 0:
            flash("This property currently has no vacant units.", "error")
            return redirect(details_url)

        if str(property_data["landlord_id"]) == str(current_user.id):
            flash("You cannot send an inquiry about your own property.", "error")
            return redirect(details_url)

        cursor.execute(
            """
            SELECT id
            FROM inquiries
            WHERE student_id = %s
              AND property_id = %s
              AND status IN ('new', 'read')
            LIMIT 1
            """,
            (current_user.id, property_id)
        )
        if cursor.fetchone():
            flash("You already have an active inquiry for this property.", "info")
            return redirect(details_url)

        cursor.execute(
            """
            INSERT INTO inquiries (student_id, property_id, message, status, created_at)
            VALUES (%s, %s, %s, 'new', NOW())
            """,
            (current_user.id, property_id, message)
        )
        connection.commit()

        # Telegram lead alert (never blocks the inquiry)
        try:
            notify_tenant_lead(
                property_title=property_data["title"],
                landlord_name=property_data.get("landlord_name") or "Landlord",
                contact_method="IN-APP INQUIRY FORM",
                tenant_info=f"{current_user.full_name} ({current_user.email})",
                tenant_phone=current_user.phone,
                message_text=message
            )
        except Exception:
            app.logger.exception("TELEGRAM INQUIRY NOTIFICATION ERROR")

        flash("Your inquiry has been sent to the landlord.", "success")
        return redirect(details_url)

    except Exception:
        if connection:
            try:
                connection.rollback()
            except Exception:
                pass
        app.logger.exception("SEND INQUIRY ERROR")
        flash("Unable to send your inquiry right now.", "error")
        return redirect(details_url)

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# =========================================================
# ADD PROPERTY
# =========================================================

def render_listing_form(status=200):
    connection = get_db_connection()
    try:
        cur = connection.cursor(dictionary=True)
        cur.execute("SELECT id, name FROM amenities ORDER BY name ASC")
        amenities = cur.fetchall()
        cur.close()
    finally:
        connection.close()
    saved = (
        {k: request.form.getlist(k) for k in request.form}
        if request.method == "POST" else {}
    )
    return render_template("sell.html", amenities=amenities, saved=saved, towns=SUPPORTED_TOWNS), status



@app.route("/landlord/add-property", methods=["GET", "POST"])
@login_required
def add_property():
    if current_user.role not in ("landlord", "admin"):
        flash(
            "Listing is for landlords. Register or sign in with a landlord account.",
            "error"
        )
        return redirect(url_for("home"))

    if request.method == "GET":
        return render_listing_form()

    def fail(message):
        flash(message, "error")
        return render_listing_form(400)

    def cleanup_uploads(photo_urls, proof_url=None):
        """Never let a cleanup failure hide the original error."""
        try:
            remove_uploads(photo_urls, proof_url)
        except Exception:
            app.logger.exception(
                "Could not clean up uploaded property files."
            )

    form = request.form
    listing_type = form.get("listing_type", "").strip()
    property_type = form.get("property_type", "").strip()
    title = form.get("title", "").strip()
    description = form.get("description", "").strip()
    location = form.get("location", "").strip()
    ownership_role = form.get("ownership_role", "").strip()

    # ---------------- Validate listing ----------------

    if listing_type not in {"rent", "sale"}:
        return fail("Choose whether you are renting out or selling.")

    is_rent = listing_type == "rent"
    is_plot = property_type == "plot"

    allowed_types = RENT_TYPES if is_rent else SALE_TYPES
    if property_type not in allowed_types:
        return fail("Choose a valid property type.")

    if not title or len(title) > 120:
        return fail("Enter a listing title of up to 120 characters.")

    if len(description) < 30:
        return fail("Write a description of at least 30 characters.")

    if location not in SUPPORTED_TOWNS:
        return fail("Please select a valid town from the list.")

    location_other = form.get("location_other", "").strip()[:120]
    if location == "Other":
        if len(location_other) < 3:
            return fail("Enter the town and country for this property.")
    else:
        location_other = None

    if ownership_role not in {"owner", "agent"}:
        return fail(
            "Say whether you are the owner or an authorized agent."
        )

    try:
        price = Decimal(form.get("price", "").strip())
        if (
            not price.is_finite()
            or price <= 0
            or price > Decimal("9999999999")
        ):
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        return fail("Enter a valid price.")

    # ---------------- Optional numeric fields ----------------

    def optional_number(name, cast, label, maximum):
        raw = form.get(name, "").strip()

        if not raw:
            return None, None

        try:
            value = cast(raw)

            if not value >= 0 or value > maximum:
                raise ValueError

            return value, None

        except (ValueError, InvalidOperation, TypeError):
            return None, f"Enter a valid {label}."

    campus = deposit = distance = None
    bedrooms = bathrooms = size_sqm = None
    total_units = vacant_units = 1
    furnished = False

    if is_rent:
        campus = form.get("campus", "").strip()[:200] or None

        deposit, error = optional_number(
            "deposit", Decimal, "deposit", 9999999999
        )
        if error:
            return fail(error)

        distance, error = optional_number(
            "distance_from_campus", float, "campus distance", 1000
        )
        if error:
            return fail(error)

        try:
            total_units = int(form.get("total_units", "1"))
            vacant_units = int(form.get("vacant_units", "1"))
        except (ValueError, TypeError):
            return fail("Unit counts must be whole numbers.")

        if (
            total_units < 1
            or vacant_units < 0
            or vacant_units > total_units
        ):
            return fail(
                "Check the unit counts: vacant units cannot be more "
                "than total units."
            )

        furnished = form.get("furnished") == "on"

    else:
        size_sqm, error = optional_number(
            "size_sqm", Decimal, "size", 100000000
        )
        if error:
            return fail(error)

    if not is_plot:
        bedrooms, error = optional_number(
            "bedrooms", int, "number of bedrooms", 50
        )
        if error:
            return fail(error)

        bathrooms, error = optional_number(
            "bathrooms", int, "number of bathrooms", 50
        )
        if error:
            return fail(error)

    amenity_names = [] if is_plot else form.getlist("amenities")
    occupied_units = total_units - vacant_units
    available = vacant_units > 0

    # ---------------- Validate uploaded files ----------------

    photos = [
        f for f in request.files.getlist("photos")
        if f and f.filename
    ]

    if not photos:
        return fail("Add at least one photo.")

    if len(photos) > MAX_PHOTOS:
        return fail(f"You can add up to {MAX_PHOTOS} photos.")

    if not all(allowed_file(f.filename) for f in photos):
        return fail("Only JPG, PNG and WEBP photos are allowed.")

    proof_file = request.files.get("proof_doc")
    has_proof = bool(proof_file and proof_file.filename)

    if not is_rent and not has_proof:
        return fail(
            "Upload proof of ownership for a property you are selling."
        )

    # ---------------- Upload photos and proof ----------------

    saved_photos = []
    saved_proof = None

    try:
        for photo in photos:
            saved_photos.append(save_photo(photo))

        if has_proof:
            saved_proof = save_proof(proof_file)

    except ValueError as exc:
        cleanup_uploads(saved_photos, saved_proof)
        return fail(str(exc))

    except Exception:
        app.logger.exception(
            "Supabase upload failed while adding a property."
        )
        cleanup_uploads(saved_photos, saved_proof)

        return fail(
            "We could not upload your photos or documents. "
            "Please try again later. If the problem continues, "
            "contact support."
        )

    # ---------------- Save property to database ----------------

    review_status = (
        "active" if current_user.role == "admin" else "pending"
    )

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            INSERT INTO properties (
                landlord_id, title, property_type, description, location,
                location_other, campus, price, deposit, distance_from_campus,
                total_units, vacant_units, occupied_units,
                furnished, available, status,
                listing_type, bedrooms, bathrooms, size_sqm,
                ownership_role, proof_doc, created_at, updated_at
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
            )
            RETURNING id
            """,
            (
                current_user.id,
                title,
                property_type,
                description,
                location,
                location_other,
                campus,
                price,
                deposit,
                distance,
                total_units,
                vacant_units,
                occupied_units,
                furnished,
                available,
                review_status,
                listing_type,
                bedrooms,
                bathrooms,
                size_sqm,
                ownership_role,
                saved_proof,
            )
        )

        property_id = cursor.fetchone()[0]

        # Save selected amenities.
        for name in amenity_names:
            cursor.execute(
                "SELECT id FROM amenities WHERE name = %s",
                (name,)
            )
            row = cursor.fetchone()

            if row:
                cursor.execute(
                    """
                    INSERT INTO property_amenities
                        (property_id, amenity_id)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (property_id, row[0])
                )

        # Save photo URLs in the property_images table.
        for index, photo_url in enumerate(saved_photos):
            cursor.execute(
                """
                INSERT INTO property_images
                    (property_id, filename, is_cover, uploaded_at)
                VALUES (%s, %s, %s, NOW())
                """,
                (property_id, photo_url, index == 0)
            )

        # Commit before sending notifications.
        connection.commit()

    except Exception:
        if connection:
            try:
                connection.rollback()
            except Exception:
                app.logger.exception(
                    "Database rollback failed after listing error."
                )

        app.logger.exception(
            "Failed to save property listing to the database."
        )
        cleanup_uploads(saved_photos, saved_proof)

        return fail(
            "Something went wrong while saving the listing. "
            "Please try again."
        )

    finally:
        if cursor:
            cursor.close()

        if connection:
            connection.close()

    # ---------------- Notify admin after successful save ----------------

    if review_status == "pending":
        try:
            notify_admin_listing(
                property_title=title,
                landlord_name=current_user.full_name,
                location=location_other if location == "Other" else location
            )
        except Exception:
            app.logger.exception(
                "Telegram notification failed for property %s.",
                property_id
            )

    if review_status == "active":
        flash("Your listing is now live.", "success")
    else:
        flash(
            "Your listing was submitted. It will go live once it has been reviewed.",
            "success"
        )

    return redirect(url_for("landlord_dashboard"))

# =========================================================
# SET COVER PHOTO
# =========================================================

@app.route(
    "/landlord/property/<int:property_id>/photo/<int:photo_id>/cover",
    methods=["POST"]
)
@login_required
def set_property_cover(property_id, photo_id):
    if current_user.role not in ("landlord", "admin"):
        flash("Only landlords can change the cover photo.", "error")
        return redirect(url_for("dashboard"))

    connection = None
    cursor = None
    back = redirect(url_for("edit_property", property_id=property_id))

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT pi.id
            FROM property_images pi
            INNER JOIN properties p ON pi.property_id = p.id
            WHERE pi.id = %s
              AND pi.property_id = %s
              AND (p.landlord_id::text = %s OR %s)
            LIMIT 1
            """,
            (photo_id, property_id, str(current_user.id),
             current_user.role == "admin")
        )
        if not cursor.fetchone():
            flash("Photo not found or you do not have permission to change it.", "error")
            return back

        cursor.execute(
            "UPDATE property_images SET is_cover = FALSE WHERE property_id = %s",
            (property_id,)
        )
        cursor.execute(
            "UPDATE property_images SET is_cover = TRUE WHERE id = %s AND property_id = %s",
            (photo_id, property_id)
        )
        connection.commit()
        flash("Cover photo updated.", "success")
        return back

    except Exception:
        if connection:
            try:
                connection.rollback()
            except Exception:
                pass
        app.logger.exception("SET PROPERTY COVER ERROR")
        flash("Unable to change the cover photo.", "error")
        return back

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

# =========================================================
# DELETE PROPERTY PHOTO
# =========================================================

@app.route(
    "/landlord/property/<int:property_id>/photo/<int:photo_id>/delete",
    methods=["POST"]
)
@login_required
def delete_property_photo(property_id, photo_id):
    if current_user.role not in ("landlord", "admin"):
        flash("Only landlords can delete property photos.", "error")
        return redirect(url_for("dashboard"))

    connection = None
    cursor = None
    is_admin = current_user.role == "admin"
    owner_id = str(current_user.id)
    back = redirect(url_for("edit_property", property_id=property_id))

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # Verify the photo belongs to this property and the user may edit it
        cursor.execute(
            """
            SELECT pi.id, pi.filename, pi.is_cover
            FROM property_images pi
            INNER JOIN properties p ON pi.property_id = p.id
            WHERE pi.id = %s
              AND pi.property_id = %s
              AND (p.landlord_id::text = %s OR %s)
            LIMIT 1
            """,
            (photo_id, property_id, owner_id, is_admin)
        )
        photo = cursor.fetchone()

        if not photo:
            flash(
                "Photo not found or you do not have permission to delete it.",
                "error"
            )
            return back

        cursor.execute(
            "SELECT COUNT(*) AS photo_count FROM property_images WHERE property_id = %s",
            (property_id,)
        )
        if cursor.fetchone()["photo_count"] <= 1:
            flash("A property must keep at least one photo.", "error")
            return back

        cursor.execute(
            "DELETE FROM property_images WHERE id = %s AND property_id = %s",
            (photo_id, property_id)
        )

        # If the cover was deleted, promote the oldest remaining photo
        if photo["is_cover"]:
            cursor.execute(
                """
                SELECT id FROM property_images
                WHERE property_id = %s
                ORDER BY id ASC
                LIMIT 1
                """,
                (property_id,)
            )
            new_cover = cursor.fetchone()
            if new_cover:
                cursor.execute(
                    "UPDATE property_images SET is_cover = TRUE WHERE id = %s",
                    (new_cover["id"],)
                )

        connection.commit()

        # Remove the file from Supabase Storage (failure here is not fatal)
        try:
            remove_uploads([photo["filename"]])
        except Exception:
            app.logger.exception("Photo storage delete failed")

        flash("Property photo deleted successfully.", "success")
        return back

    except Exception:
        if connection:
            try:
                connection.rollback()
            except Exception:
                pass
        app.logger.exception("DELETE PROPERTY PHOTO ERROR")
        flash("Unable to delete the property photo.", "error")
        return back

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@app.route("/landlord/property/<int:property_id>/delete", methods=["POST"])
@login_required
def delete_property(property_id):
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:

                # 1. Verify property ownership
                cur.execute(
                    """
                    SELECT id
                    FROM civicnest.properties
                    WHERE id = %s AND landlord_id = %s
                    """,
                    (property_id, current_user.id)
                )

                property_record = cur.fetchone()

                if not property_record:
                    flash(
                        "Property not found or you are not authorized to delete it.",
                        "error"
                    )
                    return redirect(url_for("landlord_dashboard"))

                # 2. Delete related records first
                related_tables = [
                    "property_images",
                    "property_amenities",
                    "inquiries",
                    "property_reports"
                ]

                for table in related_tables:
                    cur.execute(
                        f"""
                        DELETE FROM civicnest.{table}
                        WHERE property_id = %s
                        """,
                        (property_id,)
                    )

                # 3. Delete the property itself
                cur.execute(
                    """
                    DELETE FROM civicnest.properties
                    WHERE id = %s AND landlord_id = %s
                    """,
                    (property_id, current_user.id)
                )

                if cur.rowcount != 1:
                    raise Exception("Property deletion failed.")

            # 4. Commit all deletions together
            conn.commit()

        flash("Property and its related records deleted successfully.", "success")

    except Exception:
        app.logger.exception(
            "Error deleting property ID %s", property_id
        )
        flash(
            "Unable to delete property. Please try again.",
            "error"
        )

    return redirect(url_for("landlord_dashboard"))

# =========================================================
# ADMIN DASHBOARD
# =========================================================
        


@app.route("/roommates")
@login_required
def roommate_finder():
    if current_user.role not in ("student", "admin"):
        flash("Roommate Finder is available to student accounts.", "error")
        return redirect(url_for("dashboard"))

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM roommate_profiles WHERE user_id = %s",
            (current_user.id,)
        )
        my_profile = cursor.fetchone()

        cursor.execute(
            """
            SELECT
                rp.*,
                u.id AS user_id,
                u.full_name,
                u.profile_image,
                u.phone
            FROM roommate_profiles rp
            JOIN users u ON rp.user_id = u.id
            WHERE rp.is_active = TRUE
              AND rp.user_id <> %s
              AND u.role = 'student'
            ORDER BY rp.created_at DESC
            LIMIT 100
            """,
            (current_user.id,)
        )
        roommates = cursor.fetchall()
        for roommate in roommates:
            roommate["whatsapp_phone"] = normalize_whatsapp_number(
                roommate.get("phone")
            )

        return render_template(
            "roommate_finder.html",
            roommates=roommates,
            my_profile=my_profile
        )
    except Exception:
        app.logger.exception("ROOMMATE FINDER ERROR")
        flash("Unable to load Roommate Finder right now.", "error")
        return redirect(url_for("home"))
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@app.route("/roommates/create", methods=["GET", "POST"])
@login_required
def create_roommate_profile():
    if current_user.role != "student":
        flash("Only students can create a roommate profile.", "error")
        return redirect(url_for("roommate_finder"))

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT id FROM roommate_profiles WHERE user_id = %s",
            (current_user.id,)
        )
        if cursor.fetchone():
            flash("You already have a roommate profile. You can edit it here.", "info")
            return redirect(url_for("edit_roommate_profile"))

        if request.method == "GET":
            return render_template(
                "create_roommate_profile.html",
                form={"phone": current_user.phone or ""}
            )

        data, error = parse_roommate_form()
        if error:
            flash(error, "error")
            return render_template(
                "create_roommate_profile.html",
                form=request.form
            ), 400

        cursor.execute(
            "UPDATE users SET phone = %s, updated_at = NOW() WHERE id = %s",
            (data["phone"], current_user.id)
        )
        cursor.execute(
            """
            INSERT INTO roommate_profiles (
                user_id, campus, preferred_location, budget_min, budget_max,
                accommodation_type, move_in_date, people_needed,
                gender_preference, lifestyle_preferences,
                study_preferences, bio, is_active, created_at, updated_at
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE,
                NOW(), NOW()
            )
            """,
            (
                current_user.id,
                data["campus"],
                data["preferred_location"],
                data["budget_min"],
                data["budget_max"],
                data["accommodation_type"],
                data["move_in_date"],
                data["people_needed"],
                data["gender_preference"],
                data["lifestyle_preferences"],
                data["study_preferences"],
                data["bio"],
            )
        )
        connection.commit()
        current_user.phone = data["phone"]
        flash("Your roommate profile is now published.", "success")
        return redirect(url_for("roommate_finder"))
    except Exception as e:
        if connection:
            connection.rollback()
        print("CREATE ROOMMATE PROFILE ERROR:", e)
        flash("Unable to publish your roommate profile right now.", "error")
        return redirect(url_for("roommate_finder"))
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@app.route("/roommates/edit", methods=["GET", "POST"])
@login_required
def edit_roommate_profile():
    if current_user.role != "student":
        flash("Only students can edit a roommate profile.", "error")
        return redirect(url_for("roommate_finder"))

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT *
            FROM roommate_profiles
            WHERE user_id = %s
            """,
            (current_user.id,)
        )
        profile = cursor.fetchone()
        if not profile:
            flash("Create a roommate profile before editing it.", "info")
            return redirect(url_for("create_roommate_profile"))

        if request.method == "GET":
            profile["phone"] = current_user.phone or ""
            return render_template(
                "edit_roommate_profile.html",
                profile=profile,
                form=profile
            )

        data, error = parse_roommate_form()
        if error:
            flash(error, "error")
            profile.update(request.form)
            return render_template(
                "edit_roommate_profile.html",
                profile=profile,
            ), 400

        cursor.execute(
            "UPDATE users SET phone = %s, updated_at = NOW() WHERE id = %s",
            (data["phone"], current_user.id)
        )
        cursor.execute(
            """
            UPDATE roommate_profiles
            SET campus = %s,
                preferred_location = %s,
                budget_min = %s,
                budget_max = %s,
                accommodation_type = %s,
                move_in_date = %s,
                people_needed = %s,
                gender_preference = %s,
                lifestyle_preferences = %s,
                study_preferences = %s,
                bio = %s,
                updated_at = NOW()
            WHERE user_id = %s
            """,
            (
                data["campus"],
                data["preferred_location"],
                data["budget_min"],
                data["budget_max"],
                data["accommodation_type"],
                data["move_in_date"],
                data["people_needed"],
                data["gender_preference"],
                data["lifestyle_preferences"],
                data["study_preferences"],
                data["bio"],
                current_user.id,
            )
        )
        connection.commit()
        current_user.phone = data["phone"]
        flash("Your roommate profile has been updated.", "success")
        return redirect(url_for("roommate_finder"))
    except Exception as e:
        if connection:
            connection.rollback()
        print("EDIT ROOMMATE PROFILE ERROR:", e)
        flash("Unable to update your roommate profile right now.", "error")
        return redirect(url_for("roommate_finder"))
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@app.route("/roommates/profile/<int:profile_id>")
@login_required
def roommate_profile(profile_id):
    if current_user.role not in ("student", "admin"):
        flash("Roommate Finder is available to student accounts.", "error")
        return redirect(url_for("dashboard"))

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT
                rp.*,
                u.id AS user_id,
                u.full_name,
                u.profile_image,
                u.phone
            FROM roommate_profiles rp
            JOIN users u ON rp.user_id = u.id
            WHERE rp.id = %s
              AND u.role = 'student'
              AND (rp.is_active = TRUE OR rp.user_id = %s)
            LIMIT 1
            """,
            (profile_id, current_user.id)
        )
        profile = cursor.fetchone()
        if not profile:
            flash("That roommate profile is unavailable.", "error")
            return redirect(url_for("roommate_finder"))

        profile["whatsapp_phone"] = normalize_whatsapp_number(
            profile.get("phone")
        )
        return render_template("roommate_profile.html", profile=profile)
    except Exception as e:
        print("ROOMMATE PROFILE ERROR:", e)
        flash("Unable to load that roommate profile right now.", "error")
        return redirect(url_for("roommate_finder"))
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@app.route("/roommates/toggle-profile", methods=["POST"])
@login_required
def toggle_roommate_profile():
    if current_user.role != "student":
        flash("Only students can manage a roommate profile.", "error")
        return redirect(url_for("roommate_finder"))

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute(
            """
            UPDATE roommate_profiles
            SET is_active = NOT is_active, updated_at = NOW()
            WHERE user_id = %s
            """,
            (current_user.id,)
        )
        connection.commit()
        if cursor.rowcount:
            flash("Your roommate profile visibility has been updated.", "success")
        else:
            flash("Create a roommate profile before changing its visibility.", "error")
        return redirect(url_for("roommate_finder"))
    except Exception as e:
        if connection:
            connection.rollback()
        print("TOGGLE ROOMMATE PROFILE ERROR:", e)
        flash("Unable to update roommate profile visibility right now.", "error")
        return redirect(url_for("roommate_finder"))
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM users) AS total_users,
                (SELECT COUNT(*) FROM users WHERE role = 'student') AS students,
                (SELECT COUNT(*) FROM users WHERE role = 'landlord') AS landlords,
                (SELECT COUNT(*) FROM properties) AS total_properties,
                (SELECT COUNT(*) FROM properties WHERE status = 'pending') AS pending_properties,
                (SELECT COUNT(*) FROM property_reports WHERE status = 'pending') AS pending_reports
            """
        )
        stats = cursor.fetchone()

        cursor.execute(
            """
            SELECT id, full_name, email, phone, role, is_verified, is_active, created_at
            FROM users
            ORDER BY created_at DESC
            LIMIT 100
            """
        )
        users = cursor.fetchall()

        cursor.execute(
            """
            SELECT
                p.id, p.title, p.listing_type, p.property_type, p.ownership_role,
                p.proof_doc,
                CASE WHEN p.location = 'Other'
                     THEN COALESCE(NULLIF(p.location_other, ''), 'Other')
                     ELSE p.location END AS location,
                p.price, p.status, p.available,
                p.is_verified, p.created_at, u.full_name AS landlord_name
            FROM properties p
            JOIN users u ON u.id::text = p.landlord_id::text
            ORDER BY p.created_at DESC
            LIMIT 100
            """
        )
        properties = cursor.fetchall()

        cursor.execute(
            """
            SELECT
                r.id, r.reason, r.details, r.status, r.created_at,
                u.full_name AS reporter_name,
                p.id AS property_id, p.title AS property_title
            FROM property_reports r
            JOIN users u ON u.id = r.reporter_id
            JOIN properties p ON p.id = r.property_id
            ORDER BY CASE WHEN r.status = 'pending' THEN 0 ELSE 1 END,
                     r.created_at DESC
            LIMIT 100
            """
        )
        reports = cursor.fetchall()

        return render_template(
            "admin_dashboard.html",
            stats=stats,
            users=users,
            properties=properties,
            reports=reports,
        )
    except Exception:
        app.logger.exception("ADMIN DASHBOARD ERROR")
        flash("Unable to load the admin console right now.", "error")
        return render_template(
            "admin_dashboard.html",
            stats=None,
            users=[],
            properties=[],
            reports=[],
            error=True,
        ), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@app.route("/admin/users/<int:user_id>/role", methods=["POST"])
@admin_required
def admin_update_user_role(user_id):
    role = request.form.get("role", "")
    if role not in {"student", "landlord"}:
        flash("Choose a tenant or landlord account type.", "error")
        return redirect(url_for("admin_users"))
    if user_id == int(current_user.id):
        flash("You cannot change your own administrator account.", "error")
        return redirect(url_for("admin_users"))

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute(
            "UPDATE users SET role = %s, updated_at = NOW() WHERE id = %s AND role IN ('student', 'landlord')",
            (role, user_id)
        )
        connection.commit()
        if cursor.rowcount:
            flash("Account type updated.", "success")
        else:
            flash("That user was not found or is an administrator account.", "error")
    except Exception as e:
        if connection:
            connection.rollback()
        print("ADMIN USER ROLE UPDATE ERROR:", e)
        flash("Unable to update that account right now.", "error")
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()
    return redirect(url_for("admin_users"))

@app.route("/admin/properties/<int:property_id>/proof")
@admin_required
def admin_property_proof(property_id):
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT proof_doc FROM properties WHERE id = %s",
            (property_id,)
        )
        row = cursor.fetchone()
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

    if not row or not row["proof_doc"]:
        abort(404)

    proof = row["proof_doc"]

    # New uploads are stored in Supabase Storage as full URLs
    if proof.startswith(("http://", "https://")):
        return redirect(proof)

    # Legacy proofs saved on the server's disk
    return send_from_directory(PRIVATE_FOLDER, proof)


@app.route("/admin/properties/<int:property_id>", methods=["POST"])
@admin_required
def admin_update_property(property_id):
    status = request.form.get("status", "")
    verified = request.form.get("is_verified") == "1"
    available = request.form.get("available")

    if status not in {"active", "unavailable", "pending", "removed", "rejected"}:
        flash("Choose a valid property status.", "error")
        return redirect(url_for("admin_dashboard") + "#properties")
    if available not in {"0", "1"}:
        flash("Choose whether the property is available.", "error")
        return redirect(url_for("admin_dashboard") + "#properties")

    reason = request.form.get("rejection_reason", "").strip()[:255] or None
    if status != "rejected":
        reason = None

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute(
            """
            UPDATE properties
            SET status = %s, available = %s, is_verified = %s,
                rejection_reason = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (status, available == "1", verified, reason, property_id)
        )
        connection.commit()
        if cursor.rowcount:
            flash("Property moderation settings saved.", "success")
        else:
            flash("That property was not found or was unchanged.", "info")
        return redirect(url_for("admin_dashboard") + "#properties")
    except Exception as e:
        if connection:
            connection.rollback()
        print("ADMIN PROPERTY UPDATE ERROR:", e)
        flash("Unable to update that property right now.", "error")
        return redirect(url_for("admin_dashboard") + "#properties")
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@app.route("/admin/users/<int:user_id>/verification", methods=["POST"])
@admin_required
def admin_update_user_verification(user_id):
    verified = request.form.get("is_verified") == "1"
    if user_id == int(current_user.id):
        flash("You cannot change verification for your own administrator account.", "error")
        return redirect(url_for("admin_users"))

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute(
            """
            UPDATE users SET is_verified = %s, updated_at = NOW()
            WHERE id = %s AND role IN ('student', 'landlord')
            """,
            (verified, user_id)
        )
        connection.commit()
        if cursor.rowcount:
            flash("User verification updated.", "success")
        else:
            flash("That user was not found or is an administrator account.", "error")
    except Exception as e:
        if connection:
            connection.rollback()
        print("ADMIN USER VERIFICATION ERROR:", e)
        flash("Unable to update verification right now.", "error")
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()
    return redirect(url_for("admin_users"))

@app.route("/admin/users")
@admin_required
def admin_users():
    q = request.args.get("q", "").strip()
    like = f"%{q}%"
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, full_name, email, phone, role, is_verified, is_active, created_at
            FROM users
            WHERE %s = '' OR full_name ILIKE %s OR email ILIKE %s
                  OR COALESCE(phone, '') ILIKE %s
            ORDER BY created_at DESC
            LIMIT 300
            """,
            (q, like, like, like)
        )
        users = cursor.fetchall()
        return render_template("admin_users.html", users=users, q=q)
    except Exception as e:
        print("ADMIN USERS ERROR:", e)
        flash("Unable to load users right now.", "error")
        return redirect(url_for("admin_dashboard"))
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@app.route("/admin/users/new", methods=["GET", "POST"])
@admin_required
def admin_create_user():
    if request.method == "GET":
        return render_template("admin_user_form.html", form={})

    f = request.form
    full_name = f.get("full_name", "").strip()
    email = f.get("email", "").strip().lower().replace("mailto:", "")
    phone = f.get("phone", "").strip()
    password = f.get("password", "")
    role = f.get("role", "student")
    verified = f.get("is_verified") == "on"

    def fail(message):
        flash(message, "error")
        return render_template("admin_user_form.html", form=f), 400

    if not full_name or len(full_name) > 150:
        return fail("Enter the full name (up to 150 characters).")
    if "@" not in email or " " in email or len(email) > 255:
        return fail("Enter a valid email address.")
    if len(phone) > 30:
        return fail("The phone number is too long.")
    if role not in ("student", "landlord"):
        return fail("Choose tenant or landlord.")
    if len(password) < 8:
        return fail("The password must be at least 8 characters.")

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT id FROM users WHERE LOWER(email) = LOWER(%s)",
            (email,)
        )
        if cursor.fetchone():
            return fail("An account with that email already exists.")

        cursor.execute(
            """
            INSERT INTO users (
                full_name, email, phone, password_hash, role,
                is_verified, is_active, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, TRUE, NOW(), NOW())
            """,
            (full_name, email, phone or None,
             generate_password_hash(password), role, verified)
        )
        connection.commit()
        flash(f"Account created for {email}. Share the password you set with them.", "success")
        return redirect(url_for("admin_users"))
    except Exception as e:
        if connection:
            connection.rollback()
        print("ADMIN CREATE USER ERROR:", e)
        return fail("Unable to create that account right now.")
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@app.route("/admin/users/<int:user_id>/password", methods=["POST"])
@admin_required
def admin_reset_password(user_id):
    new_password = request.form.get("new_password", "")
    if len(new_password) < 8:
        flash("The new password must be at least 8 characters.", "error")
        return redirect(url_for("admin_users"))

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute(
            """
            UPDATE users SET password_hash = %s, updated_at = NOW()
            WHERE id = %s AND role IN ('student', 'landlord')
            """,
            (generate_password_hash(new_password), user_id)
        )
        connection.commit()
        if cursor.rowcount:
            flash("Password changed. Share the new password with the user.", "success")
        else:
            flash("That user was not found or is an administrator account.", "error")
    except Exception as e:
        if connection:
            connection.rollback()
        print("ADMIN RESET PASSWORD ERROR:", e)
        flash("Unable to change that password right now.", "error")
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>/active", methods=["POST"])
@admin_required
def admin_set_user_active(user_id):
    active = request.form.get("is_active") == "1"
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute(
            """
            UPDATE users SET is_active = %s, updated_at = NOW()
            WHERE id = %s AND role IN ('student', 'landlord')
            """,
            (active, user_id)
        )
        connection.commit()
        if cursor.rowcount:
            flash("Account reactivated." if active else "Account suspended. They can no longer log in.", "success")
        else:
            flash("That user was not found or is an administrator account.", "error")
    except Exception as e:
        if connection:
            connection.rollback()
        print("ADMIN SET ACTIVE ERROR:", e)
        flash("Unable to update that account right now.", "error")
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def admin_delete_user(user_id):
    connection = None
    cursor = None
    photo_files = []
    proof_files = []
    uid = str(user_id)
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT id, role FROM users WHERE id = %s", (user_id,))
        target = cursor.fetchone()
        if not target or target["role"] not in ("student", "landlord"):
            flash("That account was not found or cannot be deleted here.", "error")
            return redirect(url_for("admin_users"))

        cursor.execute(
            """
            SELECT pi.filename
            FROM property_images pi
            JOIN properties p ON p.id = pi.property_id
            WHERE p.landlord_id::text = %s
            """,
            (uid,)
        )
        photo_files = [r["filename"] for r in cursor.fetchall()]

        cursor.execute(
            """
            SELECT proof_doc FROM properties
            WHERE landlord_id::text = %s AND proof_doc IS NOT NULL
            """,
            (uid,)
        )
        proof_files = [r["proof_doc"] for r in cursor.fetchall()]

        cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        connection.commit()
    except Exception:
        if connection:
            try:
                connection.rollback()
            except Exception:
                pass
        app.logger.exception("ADMIN DELETE USER ERROR")
        flash("Unable to delete that account right now.", "error")
        return redirect(url_for("admin_users"))
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

    try:
        remove_uploads(photo_files)
        for proof in proof_files:
            remove_uploads([], proof)
    except Exception:
        app.logger.exception("Storage cleanup failed after deleting user")

    flash("Account deleted, together with its listings and photos.", "success")
    return redirect(url_for("admin_users"))

@app.route("/admin/reports/<int:report_id>/status", methods=["POST"])
@admin_required
def admin_update_report_status(report_id):
    status = request.form.get("status", "")
    if status not in {"pending", "reviewed", "resolved", "dismissed"}:
        flash("Choose a valid report status.", "error")
        return redirect(url_for("admin_dashboard") + "#reports")

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute(
            "UPDATE property_reports SET status = %s WHERE id = %s",
            (status, report_id)
        )
        connection.commit()
        if cursor.rowcount:
            flash("Report status updated.", "success")
        else:
            flash("That report was not found or was unchanged.", "info")
        return redirect(url_for("admin_dashboard") + "#reports")
    except Exception as e:
        if connection:
            connection.rollback()
        print("ADMIN REPORT UPDATE ERROR:", e)
        flash("Unable to update that report right now.", "error")
        return redirect(url_for("admin_dashboard") + "#reports")
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

# =========================================================
# TRAVEL WITH US
# =========================================================

BOOKING_STATUSES = ("pending", "confirmed", "paid", "cancelled")
TRIP_STATUSES = ("open", "closed", "cancelled")

KENYA_TZ = timezone(timedelta(hours=3))  # Kenya has no daylight saving


def kenya_today():
    return datetime.now(KENYA_TZ).date()


TRIP_SELECT = """
    SELECT t.*,
           t.seats_total - COALESCE(
               SUM(b.seats) FILTER (WHERE b.status IN ('confirmed', 'paid')), 0
           ) AS seats_left,
           COUNT(b.id) FILTER (WHERE b.status = 'pending') AS pending_count,
           COUNT(b.id) AS booking_count
    FROM civicnest.trips t
    LEFT JOIN civicnest.trip_bookings b ON b.trip_id = t.id
"""


def notify_admin_booking(trip, name, phone, seats, pickup):
    esc = lambda v: html.escape(str(v or ""))
    _send_telegram("\n".join([
        "🚌 <b>New seat request!</b>",
        "",
        f"<b>Trip:</b> {esc(trip['route_from'])} → {esc(trip['route_to'])}",
        f"<b>Date:</b> {esc(trip['departure_date'])} {esc(trip['departure_time'])}",
        f"<b>Name:</b> {esc(name)}",
        f"<b>Phone:</b> {esc(phone)}",
        f"<b>Seats:</b> {seats}",
        f"<b>Pickup:</b> {esc(pickup) or '-'}",
        "",
        "Open /admin/trips to confirm it.",
    ]))


# ---------- Public ----------

@app.route("/travel")
def travel_page():
    return render_template(
        "travel.html",
        trips=[],
        travel_error=False
    )



@app.route("/travel/<int:trip_id>/book", methods=["POST"])
def travel_book(trip_id):
    back = url_for("travel_page") + "#flashes"
    f = request.form

    if f.get("website"):
        return redirect(url_for("travel_page"))

    name = f.get("full_name", "").strip()
    phone = f.get("phone", "").strip()
    pickup = f.get("pickup_point", "").strip()[:120] or None
    wa = normalize_whatsapp_number(phone)

    try:
        seats = int(f.get("seats", "1"))
    except (ValueError, TypeError):
        seats = 0

    def fail(msg):
        flash(msg, "error")
        return redirect(back)

    if not 2 <= len(name) <= 120:
        return fail("Enter your full name.")

    if not wa or len(phone) > 30:
        return fail("Enter a valid phone number we can call or WhatsApp.")

    if not 1 <= seats <= 10:
        return fail("Choose between 1 and 10 seats.")

    trip = None

    try:
        with get_db_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:

                # Lock the trip row first. Admin booking confirmations
                # and trip-capacity edits must use this same lock.
                cur.execute(
                    """
                    SELECT id
                    FROM civicnest.trips
                    WHERE id = %s
                    FOR UPDATE
                    """,
                    (trip_id,),
                )

                locked_trip = cur.fetchone()

                if not locked_trip:
                    flash("That trip is no longer open for booking.", "error")
                    return redirect(back)

                # Now read the trip and calculate its current remaining seats.
                cur.execute(
                    TRIP_SELECT + " WHERE t.id = %s GROUP BY t.id",
                    (trip_id,),
                )

                trip = cur.fetchone()

                if (
                    not trip
                    or not trip["is_active"]
                    or trip["status"] != "open"
                    or trip["departure_date"] < kenya_today()
                ):
                    flash(
                        "That trip is no longer open for booking.",
                        "error",
                    )
                    return redirect(back)

                seats_left = max(trip["seats_left"], 0)

                if seats_left < seats:
                    return fail(
                        f"Only {seats_left} seat(s) left on this trip."
                    )

                # Prevent another active request from the same phone
                # for this particular trip.
                cur.execute(
                    """
                    SELECT 1
                    FROM civicnest.trip_bookings
                    WHERE trip_id = %s
                      AND whatsapp_phone = %s
                      AND status IN ('pending', 'confirmed', 'paid')
                    LIMIT 1
                    """,
                    (trip_id, wa),
                )

                if cur.fetchone():
                    flash(
                        "You already have a request for this trip. "
                        "We will contact you.",
                        "info",
                    )
                    return redirect(back)

                cur.execute(
                    """
                    INSERT INTO civicnest.trip_bookings (
                        trip_id,
                        user_id,
                        full_name,
                        phone,
                        whatsapp_phone,
                        seats,
                        pickup_point
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        trip_id,
                        current_user.id if current_user.is_authenticated else None,
                        name,
                        phone,
                        wa,
                        seats,
                        pickup,
                    ),
                )

    except Exception:
        app.logger.exception("TRAVEL BOOK ERROR")
        return fail("Something went wrong. Please try again.")

    # Notify the admin after the database transaction succeeds.
    try:
        notify_admin_booking(trip, name, phone, seats, pickup)
    except Exception:
        app.logger.exception("Telegram failed for a seat request")

    flash(
        "Request received! We will call or WhatsApp you shortly. "
        "Your seat is only held once your booking is confirmed.",
        "success",
    )

    return redirect(back)


# ---------- Admin ----------

def parse_trip_form(is_new):
    f = request.form
    route_from = f.get("route_from", "").strip()
    route_to = f.get("route_to", "").strip()
    operator_name = f.get("operator_name", "").strip()
    operator_phone = f.get("operator_phone", "").strip()
    pickup_point = f.get("pickup_point", "").strip()
    vehicle_type = f.get("vehicle_type", "").strip()
    notes = f.get("notes", "").strip()
    status = f.get("status", "open")

    if not route_from or not route_to or len(route_from) > 80 or len(route_to) > 80:
        return None, "Enter where the trip starts and where it goes (up to 80 characters each)."
    if route_from.lower() == route_to.lower():
        return None, "The start and the destination must be different."
    if not operator_name or len(operator_name) > 120:
        return None, "Enter the operator name."
    if (len(operator_phone) > 30 or len(pickup_point) > 200
            or len(vehicle_type) > 60 or len(notes) > 1000):
        return None, "One of the fields is too long."
    if status not in TRIP_STATUSES:
        return None, "Choose a valid status."

    try:
        dep_date = date.fromisoformat(f.get("departure_date", ""))
    except ValueError:
        return None, "Enter a valid departure date."
    if is_new and dep_date < kenya_today():
        return None, "The departure date cannot be in the past."

    try:
        dep_time = datetime.strptime(f.get("departure_time", ""), "%H:%M").time()
    except ValueError:
        return None, "Enter a valid departure time."

    try:
        price = Decimal(f.get("price", "").strip())
        if not price.is_finite() or price <= 0 or price > Decimal("1000000"):
            raise InvalidOperation
        raw_op = f.get("operator_price", "").strip()
        operator_price = Decimal(raw_op) if raw_op else None
        if operator_price is not None and (
            not operator_price.is_finite() or operator_price < 0
            or operator_price > Decimal("1000000")
        ):
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        return None, "Enter valid prices."

    try:
        seats_total = int(f.get("seats_total", ""))
        if not 1 <= seats_total <= 200:
            raise ValueError
    except ValueError:
        return None, "Enter the number of seats (1 to 200)."

    return {
        "route_from": route_from, "route_to": route_to,
        "departure_date": dep_date, "departure_time": dep_time,
        "pickup_point": pickup_point or None,
        "operator_name": operator_name,
        "operator_phone": operator_phone or None,
        "operator_verified": f.get("operator_verified") == "on",
        "vehicle_type": vehicle_type or None,
        "price": price, "operator_price": operator_price,
        "seats_total": seats_total, "notes": notes or None,
        "status": status, "is_active": f.get("is_active") == "on",
    }, None


@app.route("/admin/trips")
@admin_required
def admin_trips():
    try:
        with get_db_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                TRIP_SELECT + " GROUP BY t.id ORDER BY t.departure_date DESC, t.departure_time"
            )
            trips = cur.fetchall()
            cur.execute(
                """
                SELECT COUNT(*) AS total_bookings,
                       COUNT(*) FILTER (WHERE status = 'pending') AS pending_bookings,
                       COUNT(*) FILTER (WHERE status = 'confirmed') AS confirmed_bookings,
                       COUNT(*) FILTER (WHERE status = 'paid') AS paid_bookings,
                       COALESCE(SUM(seats) FILTER (
                           WHERE status IN ('confirmed', 'paid')), 0) AS held_seats
                FROM civicnest.trip_bookings
                """
            )
            stats = cur.fetchone()
        return render_template(
            "admin/trips.html", trips=trips, stats=stats, load_error=False
        )
    except Exception:
        app.logger.exception("ADMIN TRIPS ERROR")
        return render_template(
            "admin/trips.html", trips=[], stats=None, load_error=True
        ), 500



def _trip_form_view(trip_id):
    def show(trip=None, form_data=None, status=200):
        return render_template(
            "admin/trip_form.html",
            trip=trip or {},
            form_data=form_data,
            is_edit=bool(trip_id),
            trip_id=trip_id,
            statuses=TRIP_STATUSES,
        ), status

    try:
        with get_db_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                existing = None

                if trip_id:
                    cur.execute(
                        "SELECT * FROM civicnest.trips WHERE id = %s",
                        (trip_id,),
                    )
                    existing = cur.fetchone()

                    if not existing:
                        flash("Trip not found.", "error")
                        return redirect(url_for("admin_trips"))

                if request.method == "GET":
                    if existing:
                        departure_time = existing.get("departure_time")
                        if departure_time and hasattr(departure_time, "strftime"):
                            existing["departure_time"] = departure_time.strftime("%H:%M")

                        existing = {
                            key: ("" if value is None else value)
                            for key, value in existing.items()
                        }

                    return show(
                        existing or {"is_active": True, "status": "open"}
                    )

                data, error = parse_trip_form(is_new=not trip_id)

                if not error and trip_id:
                    # Lock the trip row before checking or changing capacity.
                    cur.execute(
                        """
                        SELECT id
                        FROM civicnest.trips
                        WHERE id = %s
                        FOR UPDATE
                        """,
                        (trip_id,),
                    )

                    locked_trip = cur.fetchone()

                    if not locked_trip:
                        flash("Trip not found.", "error")
                        return redirect(url_for("admin_trips"))

                    # Count seats that are already confirmed or paid.
                    cur.execute(
                        """
                        SELECT COALESCE(SUM(seats), 0) AS booked_seats
                        FROM civicnest.trip_bookings
                        WHERE trip_id = %s
                          AND status IN ('confirmed', 'paid')
                        """,
                        (trip_id,),
                    )

                    booked_seats = cur.fetchone()["booked_seats"]

                    if data["seats_total"] < booked_seats:
                        error = (
                            "Total seats cannot be less than the seats "
                            "already confirmed or paid."
                        )

                if error:
                    flash(error, "error")
                    return show(form_data=request.form, status=400)

                if trip_id:
                    data["id"] = trip_id

                    cur.execute(
                        """
                        UPDATE civicnest.trips SET
                            route_from=%(route_from)s,
                            route_to=%(route_to)s,
                            departure_date=%(departure_date)s,
                            departure_time=%(departure_time)s,
                            pickup_point=%(pickup_point)s,
                            operator_name=%(operator_name)s,
                            operator_phone=%(operator_phone)s,
                            operator_verified=%(operator_verified)s,
                            vehicle_type=%(vehicle_type)s,
                            price=%(price)s,
                            operator_price=%(operator_price)s,
                            seats_total=%(seats_total)s,
                            notes=%(notes)s,
                            status=%(status)s,
                            is_active=%(is_active)s,
                            updated_at=NOW()
                        WHERE id=%(id)s
                        """,
                        data,
                    )

                    flash("Trip updated.", "success")

                else:
                    cur.execute(
                        """
                        INSERT INTO civicnest.trips (
                            route_from,
                            route_to,
                            departure_date,
                            departure_time,
                            pickup_point,
                            operator_name,
                            operator_phone,
                            operator_verified,
                            vehicle_type,
                            price,
                            operator_price,
                            seats_total,
                            notes,
                            status,
                            is_active
                        ) VALUES (
                            %(route_from)s,
                            %(route_to)s,
                            %(departure_date)s,
                            %(departure_time)s,
                            %(pickup_point)s,
                            %(operator_name)s,
                            %(operator_phone)s,
                            %(operator_verified)s,
                            %(vehicle_type)s,
                            %(price)s,
                            %(operator_price)s,
                            %(seats_total)s,
                            %(notes)s,
                            %(status)s,
                            %(is_active)s
                        )
                        """,
                        data,
                    )

                    flash("Trip added.", "success")

        return redirect(url_for("admin_trips"))

    except Exception:
        app.logger.exception("ADMIN TRIP FORM ERROR")
        flash("Unable to save that trip right now.", "error")
        return redirect(url_for("admin_trips"))



@app.route("/admin/trips/new", methods=["GET", "POST"])
@admin_required
def admin_trip_form_new():
    return _trip_form_view(None)


@app.route("/admin/trips/<int:trip_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_trip_form_edit(trip_id):
    return _trip_form_view(trip_id)


@app.route("/admin/trips/<int:trip_id>/delete", methods=["POST"])
@admin_required
def admin_trip_delete(trip_id):
    with get_db_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM civicnest.trip_bookings WHERE trip_id = %s", (trip_id,)
        )
        if cur.fetchone()["n"]:
            flash("This trip has booking requests. Set its status to Cancelled instead of deleting it.", "error")
        else:
            cur.execute("DELETE FROM civicnest.trips WHERE id = %s", (trip_id,))
            flash("Trip deleted.", "success")
    return redirect(url_for("admin_trips"))


@app.route("/admin/trips/<int:trip_id>/bookings")
@admin_required
def admin_trip_bookings(trip_id):
    with get_db_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM civicnest.trips WHERE id = %s", (trip_id,))
        trip = cur.fetchone()
        if not trip:
            abort(404)
        cur.execute(
            """
            SELECT b.*,
                   b.created_at AT TIME ZONE 'Africa/Nairobi' AS created_local
            FROM civicnest.trip_bookings b
            WHERE b.trip_id = %s
            ORDER BY CASE b.status WHEN 'pending' THEN 0 WHEN 'confirmed' THEN 1
                                   WHEN 'paid' THEN 2 ELSE 3 END, b.created_at
            """,
            (trip_id,),
        )
        bookings = cur.fetchall()

    held = sum(b["seats"] for b in bookings if b["status"] in ("confirmed", "paid"))
    paid_seats = sum(b["seats"] for b in bookings if b["status"] == "paid")
    margin = None
    if trip["operator_price"] is not None:
        margin = (trip["price"] - trip["operator_price"]) * paid_seats
    return render_template(
        "admin/trip_bookings.html", trip=trip, bookings=bookings,
        held=held, paid_seats=paid_seats, revenue=trip["price"] * paid_seats,
        margin=margin, booking_statuses=BOOKING_STATUSES,
    )



@app.route("/admin/bookings/<int:booking_id>/status/<status>", methods=["POST"])
@admin_required
def admin_booking_status(booking_id, status):
    if status not in BOOKING_STATUSES:
        abort(400)

    ref = request.form.get("payment_ref", "").strip()[:60]

    allowed_transitions = {
        "pending": {"confirmed", "cancelled"},
        "confirmed": {"paid", "cancelled"},
        "paid": set(),
        "cancelled": set(),
    }

    trip_id = None

    try:
        with get_db_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:

                # First identify the trip associated with this booking.
                cur.execute(
                    """
                    SELECT trip_id
                    FROM civicnest.trip_bookings
                    WHERE id = %s
                    """,
                    (booking_id,),
                )

                initial_booking = cur.fetchone()

                if not initial_booking:
                    abort(404)

                trip_id = initial_booking["trip_id"]

                back = redirect(
                    url_for("admin_trip_bookings", trip_id=trip_id)
                )

                # Lock the trip first. All booking confirmations and
                # capacity edits for this trip must use this same lock.
                cur.execute(
                    """
                    SELECT id, seats_total, status, is_active, departure_date
                    FROM civicnest.trips
                    WHERE id = %s
                    FOR UPDATE
                    """,
                    (trip_id,),
                )

                trip = cur.fetchone()

                if not trip:
                    flash(
                        "The trip associated with this booking no longer exists.",
                        "error",
                    )
                    return back

                # Re-read and lock the booking after acquiring the trip lock.
                # This prevents decisions based on an outdated booking status.
                cur.execute(
                    """
                    SELECT id, trip_id, seats, status
                    FROM civicnest.trip_bookings
                    WHERE id = %s
                    FOR UPDATE
                    """,
                    (booking_id,),
                )

                booking = cur.fetchone()

                if not booking:
                    abort(404)

                current_status = booking["status"]

                if status == current_status:
                    flash(
                        "This booking already has that status.",
                        "info",
                    )
                    return back

                if status not in allowed_transitions.get(current_status, set()):
                    flash(
                        f"This booking cannot be changed from "
                        f"{current_status} to {status}.",
                        "error",
                    )
                    return back

                # Only confirmed/paid bookings consume seats.
                if status in ("confirmed", "paid"):

                    if trip["status"] != "open" or not trip["is_active"]:
                        flash(
                            "This trip is not open for new confirmations.",
                            "error",
                        )
                        return back

                    if trip["departure_date"] < kenya_today():
                        flash(
                            "This trip's departure date has passed.",
                            "error",
                        )
                        return back

                    # Recalculate seats while holding the trip lock.
                    cur.execute(
                        """
                        SELECT COALESCE(SUM(seats), 0) AS held
                        FROM civicnest.trip_bookings
                        WHERE trip_id = %s
                          AND status IN ('confirmed', 'paid')
                        """,
                        (trip_id,),
                    )

                    held = cur.fetchone()["held"]
                    seats_left = trip["seats_total"] - held

                    if booking["seats"] > seats_left:
                        flash(
                            f"Not enough seats left. Only "
                            f"{max(seats_left, 0)} seat(s) remain.",
                            "error",
                        )
                        return back

                # Update only after all checks have passed.
                cur.execute(
                    """
                    UPDATE civicnest.trip_bookings
                    SET status = %s,
                        payment_ref = COALESCE(NULLIF(%s, ''), payment_ref),
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (status, ref, booking_id),
                )

        flash(f"Booking marked {status}.", "success")

    except HTTPException:
        raise

    except Exception:
        app.logger.exception("ADMIN BOOKING STATUS ERROR")
        flash(
            "Unable to update this booking. Please try again.",
            "error",
        )

    if trip_id is not None:
        return redirect(
            url_for("admin_trip_bookings", trip_id=trip_id)
        )

    return redirect(url_for("admin_trips"))


# ============================================================
# CIVICNEST TRANSPORT — NEW ROUTE SEARCH AND BOOKING REQUESTS
# Existing trips and trip_bookings routes remain untouched.
# ============================================================

TRANSPORT_REQUEST_STATUSES = (
    "pending",
    "availability_confirmed",
    "unavailable",
    "booking_confirmed",
    "cancelled",
)



def _transport_customer_required():
    """Only logged-in student/customer accounts can make requests."""
    if not current_user.is_authenticated:
        return False

    role = (
        getattr(current_user, "role", "") or ""
    ).strip().lower()

    return role in {"student", "customer"}



def _transport_admin_required():
    """Use the existing admin role for transport administration."""
    return (
        current_user.is_authenticated
        and getattr(current_user, "role", None) == "admin"
    )


def _transport_rows(cursor):
    """Convert cursor results to dictionaries."""
    rows = cursor.fetchall()
    if not rows:
        return []

    if isinstance(rows[0], dict):
        return rows

    columns = [column.name for column in cursor.description]
    return [dict(zip(columns, row)) for row in rows]

def _transport_fetchone(cursor):
    row = cursor.fetchone()

    if row is None:
        return None

    if isinstance(row, dict):
        return row

    columns = [
        column.name if hasattr(column, "name") else column[0]
        for column in cursor.description
    ]

    return dict(zip(columns, row))    


# ------------------------------------------------------------
# 1. CUSTOMER SEARCH
# GET /travel/search?from=Kisumu&to=Nairobi&date=2026-11-05
# ------------------------------------------------------------


@app.route("/travel/search", methods=["GET"])
def transport_search():
    origin = (request.args.get("from") or "").strip()
    destination = (request.args.get("to") or "").strip()
    travel_date = (request.args.get("date") or "").strip()
    preferred_time = (request.args.get("time") or "").strip()
    passengers = request.args.get("passengers", "1")

    if not origin or not destination or not travel_date:
        return jsonify({
            "success": False,
            "message": "Enter your departure, destination and travel date."
        }), 400

    try:
        selected_date = date.fromisoformat(travel_date)
        passenger_count = int(passengers)

        if selected_date < kenya_today():
            return jsonify({
                "success": False,
                "message": "Travel date cannot be in the past."
            }), 400

        if not 1 <= passenger_count <= 10:
            return jsonify({
                "success": False,
                "message": "Passenger count must be between 1 and 10."
            }), 400

    except (ValueError, TypeError):
        return jsonify({
            "success": False,
            "message": "Check your travel date and passenger count."
        }), 400

    target_time = None

    if preferred_time:
        try:
            target_time = datetime.strptime(
                preferred_time, "%H:%M"
            ).time()
        except ValueError:
            return jsonify({
                "success": False,
                "message": "Enter a valid preferred departure time."
            }), 400

    conn = None

    try:
        conn = get_db_connection()

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    d.id AS departure_id,
                    d.departure_time,
                    d.price_per_passenger,
                    r.id AS route_id,
                    r.route_from,
                    r.route_to,
                    r.intermediate_stops,
                    r.boarding_point,
                    r.dropoff_point,
                    r.vehicle_type,
                    c.id AS company_id,
                    c.company_name,
                    c.logo_url,
                    c.vehicle_image_url
                FROM civicnest.transport_departures d
                INNER JOIN civicnest.transport_routes r
                    ON r.id = d.route_id
                INNER JOIN civicnest.transport_companies c
                    ON c.id = r.company_id
                WHERE
                    c.is_active IS TRUE
                    AND r.is_active IS TRUE
                    AND d.is_active IS TRUE
                    AND LOWER(TRIM(r.route_from)) = LOWER(TRIM(%s))
                    AND LOWER(TRIM(r.route_to)) = LOWER(TRIM(%s))
                ORDER BY
                    c.company_name,
                    d.departure_time
                """,
                (origin, destination),
            )

            departures = _transport_rows(cur)

        # Preferred time changes the order, not which departures appear.
        if target_time and departures:

            target_minutes = (
                target_time.hour * 60 + target_time.minute
            )

            def time_distance(item):
                departure = item["departure_time"]

                if isinstance(departure, str):
                    departure = datetime.strptime(
                        departure, "%H:%M:%S"
                    ).time()

                departure_minutes = (
                    departure.hour * 60 + departure.minute
                )

                difference = abs(
                    departure_minutes - target_minutes
                )

                return min(difference, 1440 - difference)

            departures.sort(key=time_distance)

        results = []

        for item in departures:
            departure_time = item["departure_time"]

            if isinstance(departure_time, str):
                departure_time = datetime.strptime(
                    departure_time, "%H:%M:%S"
                ).time()

            price = float(item["price_per_passenger"])

            results.append({
                "departure_id": item["departure_id"],
                "company": item["company_name"],
                "logo_url": item["logo_url"],
                "vehicle_image_url": item["vehicle_image_url"],
                "from": item["route_from"],
                "to": item["route_to"],
                "departure_time": departure_time.strftime("%H:%M"),
                "price": price,
                "estimated_total": price * passenger_count,
                "boarding_point": item["boarding_point"],
                "dropoff_point": item["dropoff_point"],
                "intermediate_stops": item["intermediate_stops"],
                "vehicle_type": item["vehicle_type"],
            })

        return jsonify({
            "success": True,
            "travel_date": selected_date.isoformat(),
            "passengers": passenger_count,
            "departures": results,
            "count": len(results),
            "message": (
                "Departures found."
                if results
                else "No registered departures were found for this route."
            )
        })

    except Exception:
        app.logger.exception("TRANSPORT SEARCH ERROR")

        return jsonify({
            "success": False,
            "message": "Unable to search transport departures right now. Please try again."
        }), 500

    finally:
        if conn is not None:
            conn.close()

# ------------------------------------------------------------
# 2. CUSTOMER SUBMITS A BOOKING / AVAILABILITY REQUEST
# POST /travel/request
# ------------------------------------------------------------


@app.route("/travel/request", methods=["POST"])
def transport_submit_request():

    # --------------------------------------------------
    # 1. Authentication and customer permissions
    # --------------------------------------------------
    if not current_user.is_authenticated:
        flash(
            "Please sign in before submitting a travel request.",
            "error"
        )
        return redirect(url_for("login"))

    if not _transport_customer_required():
        abort(403)

    # --------------------------------------------------
    # 2. Read submitted form fields
    # --------------------------------------------------
    departure_id = request.form.get("departure_id", type=int)
    travel_date = (request.form.get("travel_date") or "").strip()
    passenger_count = request.form.get("passengers", type=int)

    full_name = (request.form.get("full_name") or "").strip()
    phone = (request.form.get("phone") or "").strip()

    whatsapp_phone = (
        request.form.get("whatsapp_phone") or phone
    ).strip()

    original_request_id = request.form.get(
        "original_request_id",
        type=int
    )

    # --------------------------------------------------
    # 3. Validate required fields
    # --------------------------------------------------
    if not all([
        departure_id,
        travel_date,
        passenger_count,
        full_name,
        phone,
        whatsapp_phone
    ]):
        flash(
            "Please complete all required booking details.",
            "error"
        )
        return redirect(url_for("travel_page"))

    if not 2 <= len(full_name) <= 120:
        flash("Enter your full name.", "error")
        return redirect(url_for("travel_page"))

    if len(phone) > 30 or len(whatsapp_phone) > 30:
        flash("Please enter valid phone numbers.", "error")
        return redirect(url_for("travel_page"))

    # --------------------------------------------------
    # 4. Validate travel date and passenger count
    # --------------------------------------------------
    try:
        selected_date = date.fromisoformat(travel_date)

        if selected_date < kenya_today():
            raise ValueError("Travel date cannot be in the past.")

        if not 1 <= passenger_count <= 10:
            raise ValueError("Passenger count must be between 1 and 10.")

    except (ValueError, TypeError):
        flash(
            "Please check your travel date and passenger count.",
            "error"
        )
        return redirect(url_for("travel_page"))

    # --------------------------------------------------
    # 5. Normalize WhatsApp number
    # --------------------------------------------------
    try:
        normalized_phone = normalize_whatsapp_number(
            whatsapp_phone
        )
    except Exception:
        normalized_phone = None

    if not normalized_phone:
        flash("Enter a valid WhatsApp number.", "error")
        return redirect(url_for("travel_page"))

    conn = None
    request_id = None

    try:
        # --------------------------------------------------
        # 6. Connect to database
        # --------------------------------------------------
        conn = get_db_connection()

        with conn.cursor() as cur:

            # --------------------------------------------------
            # 7. Verify selected departure is active
            # --------------------------------------------------
            cur.execute(
                """
                SELECT
                    d.id AS departure_id,
                    d.departure_time,
                    d.price_per_passenger,

                    r.id AS route_id,
                    r.route_from,
                    r.route_to,
                    r.boarding_point,
                    r.dropoff_point,
                    r.vehicle_type,

                    c.id AS company_id,
                    c.company_name

                FROM civicnest.transport_departures d

                INNER JOIN civicnest.transport_routes r
                    ON r.id = d.route_id

                INNER JOIN civicnest.transport_companies c
                    ON c.id = r.company_id

                WHERE
                    d.id = %s
                    AND d.is_active IS TRUE
                    AND r.is_active IS TRUE
                    AND c.is_active IS TRUE

                LIMIT 1
                """,
                (departure_id,)
            )

            departure = _transport_fetchone(cur)

            if not departure:
                flash(
                    "That departure is no longer available for requests.",
                    "error"
                )
                return redirect(url_for("travel_page"))

            # --------------------------------------------------
            # 8. Verify original request for alternatives
            # --------------------------------------------------
            if original_request_id:

                cur.execute(
                    """
                    SELECT id
                    FROM civicnest.transport_booking_requests
                    WHERE
                        id = %s
                        AND user_id = %s
                        AND status = 'unavailable'
                    LIMIT 1
                    """,
                    (
                        original_request_id,
                        current_user.id
                    )
                )

                original_request = cur.fetchone()

                if not original_request:
                    abort(403)

            # --------------------------------------------------
            # 9. Calculate estimated total
            # --------------------------------------------------
            price = Decimal(
                str(departure["price_per_passenger"])
            )

            estimated_total = (
                price * passenger_count
            ).quantize(Decimal("0.01"))

            # --------------------------------------------------
            # 10. Save customer request
            # --------------------------------------------------
            cur.execute(
                """
                INSERT INTO civicnest.transport_booking_requests (
                    user_id,
                    departure_id,
                    original_request_id,

                    travel_date,
                    passenger_count,

                    full_name,
                    phone,
                    whatsapp_phone,

                    company_name_snapshot,
                    route_from_snapshot,
                    route_to_snapshot,
                    departure_time_snapshot,

                    price_per_passenger_snapshot,
                    boarding_point_snapshot,
                    dropoff_point_snapshot,
                    vehicle_type_snapshot,

                    estimated_total
                )

                VALUES (
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s
                )

                RETURNING id
                """,
                (
                    current_user.id,
                    departure_id,
                    original_request_id,

                    selected_date,
                    passenger_count,

                    full_name,
                    phone,
                    normalized_phone,

                    departure["company_name"],
                    departure["route_from"],
                    departure["route_to"],
                    departure["departure_time"],

                    price,
                    departure["boarding_point"],
                    departure["dropoff_point"],
                    departure["vehicle_type"],

                    estimated_total
                )
            )

            inserted = cur.fetchone()

            if not inserted:
                raise RuntimeError(
                    "The transport request could not be saved."
                )

            request_id = inserted[0]

        # --------------------------------------------------
        # 11. Commit successful request
        # --------------------------------------------------
        conn.commit()

        app.logger.info(
            "Transport request %s submitted by user %s",
            request_id,
            current_user.id
        )

        flash(
            "Your travel request has been submitted. "
            "We will check availability and update your account.",
            "success"
        )

        return redirect(
            url_for("my_transport_requests")
        )

    except HTTPException:
        if conn:
            conn.rollback()
        raise

    except Exception:
        if conn:
            conn.rollback()

        app.logger.exception(
            "TRANSPORT REQUEST SUBMISSION ERROR"
        )

        flash(
            "We could not submit your request. Please try again.",
            "error"
        )

        return redirect(url_for("travel_page"))

    finally:
        if conn:
            conn.close()



# ------------------------------------------------------------
# 3. CUSTOMER'S OWN REQUEST HISTORY
# GET /my-travel-requests
# ------------------------------------------------------------

def _fmt_time(value):
    """Return HH:MM for a time object or an 'HH:MM:SS' string."""
    if value is None:
        return None
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")
    return str(value)[:5]


@app.route("/my-travel-requests", methods=["GET"])
def my_transport_requests():
    if not current_user.is_authenticated:
        return redirect(url_for("login"))

    if not _transport_customer_required():
        abort(403)

    conn = None
    try:
        conn = get_db_connection()

        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    id,
                    original_request_id,
                    travel_date,
                    passenger_count,
                    full_name,
                    phone,
                    company_name_snapshot AS company_name,
                    route_from_snapshot AS route_from,
                    route_to_snapshot AS route_to,
                    departure_time_snapshot AS departure_time,
                    price_per_passenger_snapshot AS price_per_passenger,
                    estimated_total,
                    boarding_point_snapshot AS boarding_point,
                    dropoff_point_snapshot AS dropoff_point,
                    vehicle_type_snapshot AS vehicle_type,
                    status,
                    admin_note,
                    availability_checked_at,
                    final_confirmed_at,
                    created_at
                FROM civicnest.transport_booking_requests
                WHERE user_id = %s
                ORDER BY created_at DESC
            """, (current_user.id,))

            request_rows = _transport_rows(cur)

        for item in request_rows:
            item["departure_time"] = _fmt_time(item["departure_time"])

        return render_template(
            "my_transport_requests.html",
            requests=request_rows
        )

    except Exception:
        app.logger.exception("Could not load customer transport requests.")
        flash("Could not load your travel requests. Please try again.", "error")
        return redirect(url_for("travel_page"))

    finally:
        if conn:
            conn.close()


# ------------------------------------------------------------
# 4. ADMIN: VIEW ALL TRANSPORT REQUESTS
# GET /admin/transport/requests
# ------------------------------------------------------------

@app.route("/admin/transport/requests", methods=["GET"])
@admin_required
def admin_transport_requests():

    conn = get_db_connection()

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    r.*,
                    u.email AS customer_email
                FROM civicnest.transport_booking_requests r
                JOIN civicnest.users u ON u.id = r.user_id
                ORDER BY
                    CASE WHEN r.status = 'pending' THEN 0 ELSE 1 END,
                    r.created_at DESC
            """)

            requests = _transport_rows(cur)

        return render_template(
            "admin/transport_requests.html",
            requests=requests
        )

    finally:
        conn.close()


# ------------------------------------------------------------
# 5. ADMIN: AVAILABLE / UNAVAILABLE DECISION
# POST /admin/transport/request/<id>/availability
# ------------------------------------------------------------

@app.route(
    "/admin/transport/request/<int:request_id>/availability",
    methods=["POST"]
)
@admin_required
def admin_transport_availability(request_id):
    app.logger.info(
    "TRANSPORT AVAILABILITY FORM: %r",
    request.form.to_dict()
)

    decision = (
    request.form.get("decision")
    or request.form.get("availability")
    or ""
).strip().lower()
    admin_note = (request.form.get("admin_note") or "").strip()

    if decision not in ("available", "unavailable"):
        abort(400)

    new_status = (
        "availability_confirmed"
        if decision == "available"
        else "unavailable"
    )

    conn = get_db_connection()

    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE civicnest.transport_booking_requests
                SET
                    status = %s,
                    admin_note = %s,
                    checked_by_user_id = %s,
                    availability_checked_at = NOW(),
                    updated_at = NOW()
                WHERE id = %s
                  AND status = 'pending'
                RETURNING id
            """, (
                new_status,
                admin_note or None,
                current_user.id,
                request_id
            ))

            updated = cur.fetchone()

            if not updated:
                conn.rollback()
                flash(
                    "This request has already been reviewed or does not exist.",
                    "error"
                )
                return redirect(url_for("admin_transport_requests"))

        conn.commit()

        flash(
            "Availability decision saved.",
            "success"
        )

    except Exception:
        conn.rollback()
        app.logger.exception("Transport availability update failed.")
        flash("Could not update availability.", "error")

    finally:
        conn.close()

    return redirect(url_for("admin_transport_requests"))

@app.route(
    "/admin/transport/request/<int:request_id>/confirm",
    methods=["POST"]
)
@admin_required
def admin_transport_confirm_booking(request_id):
    import html

    conn = get_db_connection()
    confirmed_request = None

    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE civicnest.transport_booking_requests
                SET
                    status = 'booking_confirmed',
                    checked_by_user_id = %s,
                    final_confirmed_at = NOW(),
                    updated_at = NOW()
                WHERE id = %s
                  AND status = 'availability_confirmed'
                RETURNING
                    id,
                    full_name,
                    phone,
                    company_name_snapshot,
                    route_from_snapshot,
                    route_to_snapshot,
                    travel_date,
                    departure_time_snapshot,
                    passenger_count,
                    price_per_passenger_snapshot,
                    estimated_total
            """, (current_user.id, request_id))

            rows = _transport_rows(cur)

            if not rows:
                conn.rollback()
                flash(
                    "This request is not awaiting final confirmation, or it does not exist.",
                    "error"
                )
                return redirect(url_for("admin_transport_requests"))

            confirmed_request = rows[0]

        conn.commit()

        # Notify the administrator through Telegram.
        try:
            r = confirmed_request

            message = (
                "✅ <b>TRANSPORT BOOKING CONFIRMED</b>\n\n"
                f"<b>Reference:</b> CN-{r['id']}\n"
                f"<b>Company:</b> {html.escape(str(r['company_name_snapshot'] or 'N/A'))}\n"
                f"<b>Route:</b> {html.escape(str(r['route_from_snapshot']))} "
                f"→ {html.escape(str(r['route_to_snapshot']))}\n"
                f"<b>Travel date:</b> {html.escape(str(r['travel_date']))}\n"
                f"<b>Departure:</b> {html.escape(str(r['departure_time_snapshot']))}\n"
                f"<b>Passenger:</b> {html.escape(str(r['full_name']))}\n"
                f"<b>Phone:</b> {html.escape(str(r['phone']))}\n"
                f"<b>Passengers:</b> {r['passenger_count']}\n"
                f"<b>Fare each:</b> KSh {float(r['price_per_passenger_snapshot']):,.2f}\n"
                f"<b>Total:</b> KSh {float(r['estimated_total']):,.2f}\n\n"
                "The booking is finally confirmed on CivicNest."
            )

            _send_telegram(message)

        except Exception:
            app.logger.exception(
                "Booking confirmed, but Telegram notification failed."
            )

        flash(
            "Booking confirmed successfully.",
            "success"
        )

    except Exception:
        conn.rollback()
        app.logger.exception("Transport booking confirmation failed.")
        flash("Could not confirm this booking.", "error")

    finally:
        conn.close()

    return redirect(url_for("admin_transport_requests"))   

@app.route("/my-travel-requests/<int:request_id>/receipt")
@login_required
def my_transport_receipt(request_id):

    if not _transport_customer_required():
        abort(403)

    conn = None
    try:
        conn = get_db_connection()

        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    id,
                    full_name,
                    phone,
                    company_name_snapshot,
                    route_from_snapshot,
                    route_to_snapshot,
                    travel_date,
                    departure_time_snapshot,
                    passenger_count,
                    price_per_passenger_snapshot,
                    estimated_total,
                    boarding_point_snapshot,
                    dropoff_point_snapshot,
                    vehicle_type_snapshot,
                    final_confirmed_at
                FROM civicnest.transport_booking_requests
                WHERE id = %s
                  AND user_id = %s
                  AND status = 'booking_confirmed'
                LIMIT 1
            """, (request_id, current_user.id))

            booking = _transport_fetchone(cur)

        if not booking:
            flash(
                "Receipt is available only for your finally confirmed bookings.",
                "error"
            )
            return redirect(url_for("my_transport_requests"))

        booking["departure_time_snapshot"] = _fmt_time(
            booking["departure_time_snapshot"]
        )
        booking["reference"] = f"CN-{booking['id']}"

        return render_template(
            "transport_receipt.html",
            booking=booking
        )

    except Exception:
        app.logger.exception("Could not load transport receipt.")
        flash("Could not load your receipt.", "error")
        return redirect(url_for("my_transport_requests"))

    finally:
        if conn:
            conn.close()


# =========================================================
# ADMIN: TRANSPORT COMPANY, ROUTE AND DEPARTURE MANAGEMENT
# =========================================================

@app.route("/admin/transport", methods=["GET"])
def admin_transport_page():
    if not _transport_admin_required():
        return "Forbidden", 403

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        id,
                        company_name,
                        company_phone,
                        main_boarding_station,
                        logo_url,
                        vehicle_image_url,
                        is_active
                    FROM civicnest.transport_companies
                    ORDER BY company_name
                """)
                companies = _transport_rows(cur)

                cur.execute("""
                    SELECT
                        r.id,
                        r.company_id,
                        c.company_name,
                        r.route_from,
                        r.route_to,
                        r.intermediate_stops,
                        r.boarding_point,
                        r.dropoff_point,
                        r.vehicle_type,
                        r.is_active
                    FROM civicnest.transport_routes r
                    JOIN civicnest.transport_companies c
                      ON c.id = r.company_id
                    ORDER BY c.company_name, r.route_from, r.route_to
                """)
                routes = _transport_rows(cur)

                cur.execute("""
                    SELECT
                        d.id,
                        d.route_id,
                        c.company_name,
                        r.route_from,
                        r.route_to,
                        d.departure_time,
                        d.price_per_passenger,
                        d.is_active
                    FROM civicnest.transport_departures d
                    JOIN civicnest.transport_routes r
                      ON r.id = d.route_id
                    JOIN civicnest.transport_companies c
                      ON c.id = r.company_id
                    ORDER BY c.company_name, r.route_from,
                             r.route_to, d.departure_time
                """)
                departures = _transport_rows(cur)

        return render_template(
            "admin_transport.html",
            companies=companies,
            routes=routes,
            departures=departures
        )

    except Exception:
        app.logger.exception("ADMIN TRANSPORT PAGE ERROR")
        return "Unable to load transport management.", 500


@app.route("/admin/transport/company", methods=["POST"])
def admin_add_transport_company():
    if not _transport_admin_required():
        return "Forbidden", 403

    company_name = request.form.get("company_name", "").strip()
    company_phone = request.form.get("company_phone", "").strip()
    main_boarding_station = request.form.get(
        "main_boarding_station", ""
    ).strip()
    logo_url = request.form.get("logo_url", "").strip()
    vehicle_image_url = request.form.get(
        "vehicle_image_url", ""
    ).strip()

    if not company_name:
        flash("Enter the transport company name.", "error")
        return redirect(url_for("admin_transport_page"))

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO civicnest.transport_companies (
                        company_name,
                        company_phone,
                        main_boarding_station,
                        logo_url,
                        vehicle_image_url
                    )
                    VALUES (%s, %s, %s, %s, %s)
                """, (
                    company_name,
                    company_phone or None,
                    main_boarding_station or None,
                    logo_url or None,
                    vehicle_image_url or None
                ))

        flash("Transport company registered successfully.", "success")

    except Exception:
        app.logger.exception("ADD TRANSPORT COMPANY ERROR")
        flash("Could not register the company.", "error")

    return redirect(url_for("admin_transport_page"))


@app.route("/admin/transport/route", methods=["POST"])
def admin_add_transport_route():
    if not _transport_admin_required():
        return "Forbidden", 403

    try:
        company_id = int(request.form.get("company_id", ""))
    except (TypeError, ValueError):
        flash("Select a valid transport company.", "error")
        return redirect(url_for("admin_transport_page"))

    route_from = request.form.get("route_from", "").strip()
    route_to = request.form.get("route_to", "").strip()
    intermediate_stops = request.form.get(
        "intermediate_stops", ""
    ).strip()
    boarding_point = request.form.get("boarding_point", "").strip()
    dropoff_point = request.form.get("dropoff_point", "").strip()
    vehicle_type = request.form.get("vehicle_type", "").strip()

    if not route_from or not route_to:
        flash("Enter both departure and destination towns.", "error")
        return redirect(url_for("admin_transport_page"))

    if route_from.casefold() == route_to.casefold():
        flash("Departure and destination cannot be the same.", "error")
        return redirect(url_for("admin_transport_page"))

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO civicnest.transport_routes (
                        company_id,
                        route_from,
                        route_to,
                        intermediate_stops,
                        boarding_point,
                        dropoff_point,
                        vehicle_type
                    )
                    SELECT
                        id, %s, %s, %s, %s, %s, %s
                    FROM civicnest.transport_companies
                    WHERE id = %s AND is_active = TRUE
                    RETURNING id
                """, (
                    route_from,
                    route_to,
                    intermediate_stops or None,
                    boarding_point or None,
                    dropoff_point or None,
                    vehicle_type or None,
                    company_id
                ))

                created = cur.fetchone()

                if not created:
                    flash("The selected company was not found or is inactive.", "error")
                    return redirect(url_for("admin_transport_page"))

        flash("Transport route added successfully.", "success")

    except Exception:
        app.logger.exception("ADD TRANSPORT ROUTE ERROR")
        flash("Could not add the transport route.", "error")

    return redirect(url_for("admin_transport_page"))


@app.route("/admin/transport/departure", methods=["POST"])
def admin_add_transport_departure():
    if not _transport_admin_required():
        return "Forbidden", 403

    try:
        route_id = int(request.form.get("route_id", ""))
        departure_time = request.form.get("departure_time", "").strip()
        price = float(request.form.get("price_per_passenger", ""))

        if not departure_time:
            raise ValueError("Departure time is required.")

        if price < 0:
            raise ValueError("Fare cannot be negative.")

    except (TypeError, ValueError):
        flash("Enter a valid route, departure time and fare.", "error")
        return redirect(url_for("admin_transport_page"))

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO civicnest.transport_departures (
                        route_id,
                        departure_time,
                        price_per_passenger
                    )
                    SELECT id, %s, %s
                    FROM civicnest.transport_routes
                    WHERE id = %s AND is_active = TRUE
                    RETURNING id
                """, (
                    departure_time,
                    price,
                    route_id
                ))

                created = cur.fetchone()

                if not created:
                    flash("The selected route was not found or is inactive.", "error")
                    return redirect(url_for("admin_transport_page"))

        flash("Departure time and fare added successfully.", "success")

    except Exception:
        app.logger.exception("ADD TRANSPORT DEPARTURE ERROR")
        flash("Could not add the departure.", "error")

    return redirect(url_for("admin_transport_page"))  


@app.route("/admin/transport/routes/bulk", methods=["POST"])
def admin_add_transport_routes_bulk():
    if not _transport_admin_required():
        return "Forbidden", 403

    try:
        company_id = int(request.form.get("company_id", ""))
        routes = json.loads(request.form.get("routes_json", "[]"))

        if not isinstance(routes, list) or not routes:
            raise ValueError("Add at least one route.")

        if len(routes) > 100:
            raise ValueError("You can add up to 100 routes per batch.")

        cleaned_routes = []

        for index, route in enumerate(routes, start=1):
            if not isinstance(route, dict):
                raise ValueError(f"Route {index} is invalid.")

            route_from = str(route.get("route_from", "")).strip()
            route_to = str(route.get("route_to", "")).strip()

            if not route_from or not route_to:
                raise ValueError(
                    f"Route {index}: departure and destination are required."
                )

            if route_from.casefold() == route_to.casefold():
                raise ValueError(
                    f"Route {index}: departure and destination cannot be the same."
                )

            departures = route.get("departures", [])

            if not isinstance(departures, list) or not departures:
                raise ValueError(
                    f"Route {index}: add at least one departure time and fare."
                )

            cleaned_departures = []

            for departure in departures:
                if not isinstance(departure, dict):
                    raise ValueError(f"Route {index}: invalid departure.")

                departure_time = str(
                    departure.get("departure_time", "")
                ).strip()

                price = float(departure.get("price_per_passenger", ""))

                if not departure_time:
                    raise ValueError(
                        f"Route {index}: departure time is required."
                    )

                # Accept HTML time input format HH:MM.
                import re
                if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", departure_time):
                    raise ValueError(
                        f"Route {index}: enter a valid departure time."
                    )

                if price < 0:
                    raise ValueError(
                        f"Route {index}: fare cannot be negative."
                    )

                cleaned_departures.append((departure_time, price))

            cleaned_routes.append({
                "route_from": route_from,
                "route_to": route_to,
                "intermediate_stops": str(
                    route.get("intermediate_stops", "")
                ).strip() or None,
                "boarding_point": str(
                    route.get("boarding_point", "")
                ).strip() or None,
                "dropoff_point": str(
                    route.get("dropoff_point", "")
                ).strip() or None,
                "vehicle_type": str(
                    route.get("vehicle_type", "")
                ).strip() or None,
                "departures": cleaned_departures
            })

        with get_db_connection() as conn:
            with conn.cursor() as cur:

                # Confirm that the company exists and is active.
                cur.execute("""
                    SELECT id
                    FROM civicnest.transport_companies
                    WHERE id = %s AND is_active = TRUE
                """, (company_id,))

                if not cur.fetchone():
                    raise ValueError(
                        "The selected company does not exist or is inactive."
                    )

                total_departures = 0

                # Save all routes and departures in this transaction.
                for route in cleaned_routes:
                    cur.execute("""
                        INSERT INTO civicnest.transport_routes (
                            company_id,
                            route_from,
                            route_to,
                            intermediate_stops,
                            boarding_point,
                            dropoff_point,
                            vehicle_type
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (
                        company_id,
                        route["route_from"],
                        route["route_to"],
                        route["intermediate_stops"],
                        route["boarding_point"],
                        route["dropoff_point"],
                        route["vehicle_type"]
                    ))

                    created_route = cur.fetchone()
                    route_id = created_route[0]

                    for departure_time, price in route["departures"]:
                        cur.execute("""
                            INSERT INTO civicnest.transport_departures (
                                route_id,
                                departure_time,
                                price_per_passenger
                            )
                            VALUES (%s, %s, %s)
                        """, (
                            route_id,
                            departure_time,
                            price
                        ))

                        total_departures += 1

        flash(
            f"Successfully added {len(cleaned_routes)} routes "
            f"and {total_departures} departure times.",
            "success"
        )

    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        flash(str(exc), "error")

    except Exception:
        app.logger.exception("BULK TRANSPORT ROUTE ERROR")
        flash(
            "Could not save the routes. No partial batch should have been saved.",
            "error"
        )

    return redirect(url_for("admin_transport_page"))

@app.route("/about")
def about_page():
    return render_template("about.html", current_year=datetime.utcnow().year)    



# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
@login_required
def logout():

    logout_user()

    return redirect(
        url_for("home")
    )
# =========================================================
# DATABASE TEST
# =========================================================

@app.route("/test-db")
def test_db():

    try:

        connection = get_db_connection()

        cursor = connection.cursor()

        cursor.execute(
            "SELECT DATABASE();"
        )

        database = cursor.fetchone()

        cursor.close()

        connection.close()

        return f"""
            <h1>Civic Nest Database Connected</h1>
            <p>Database: {database[0]}</p>
        """

    except Exception as e:

        return f"""
            <h1>Database Connection Failed</h1>
            <p>{e}</p>
        """, 500


# =========================================================
# RUN APPLICATION
# =========================================================

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )