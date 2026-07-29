# -*- coding: utf-8 -*-
"""
Αρχείο Αποδείξεων  —  Ψηφιακό αρχείο παραστατικών
=================================================
Τοπική εφαρμογή για την αρχειοθέτηση αποδείξεων δύο (ή περισσότερων)
επιχειρήσεων, με ξεχωριστό αρχείο για την καθεμία.

Λειτουργίες:
  - Καταχώρηση απόδειξης από φωτογραφία / σκαναρισμένο αρχείο (εικόνα ή PDF)
  - Αυτόματη λήψη αποδείξεων από το email (IMAP) με έλεγχο πριν την αρχειοθέτηση
  - Αναζήτηση / φιλτράρισμα ανά προμηθευτή, κατηγορία, έτος
  - Δημιουργία επίσημου PDF για κάθε απόδειξη (για την εφορία)
"""

import os
import io
import re
import sys
import json
import time
import base64
import shutil
import sqlite3
import threading
import datetime as dt
from email.header import decode_header
from email.utils import parsedate_to_datetime, parseaddr

from flask import Flask, request, jsonify, render_template, send_file, abort

# ---------------------------------------------------------------------------
#  Ρυθμίσεις / σταθερές
# ---------------------------------------------------------------------------

APP_TITLE = "Αρχείο Αποδείξεων"

# Οι επιχειρήσεις που τηρούν ξεχωριστό αρχείο (κλειδί -> εμφανιζόμενο όνομα).
# Αλλάξτε ελεύθερα τα ονόματα — ή προσθέστε/αφαιρέστε γραμμές.
# ΠΡΟΣΟΧΗ: το κλειδί (αριστερά) χρησιμοποιείται στη βάση και στα ονόματα
# φακέλων· αν το αλλάξετε αφού έχετε καταχωρήσει αποδείξεις, οι παλιές δεν θα
# εμφανίζονται. Το εμφανιζόμενο όνομα (δεξιά) αλλάζει άφοβα οποτεδήποτε.
BUSINESSES = {
    "business_a": "Επιχείρηση Α",
    "business_b": "Επιχείρηση Β",
}

# Προτεινόμενες κατηγορίες (ο χρήστης μπορεί να γράψει και δική του)
CATEGORIES = [
    "Καύσιμα",
    "Επισκευές & Συντήρηση",
    "Ανταλλακτικά",
    "Προμήθειες & Υλικά",
    "Λογαριασμοί (ΔΕΗ/Νερό/Τηλέφωνο)",
    "Ασφάλιστρα",
    "Ενοίκιο",
    "Φόροι & Τέλη",
    "Μισθοδοσία",
    "Άλλο",
]

# Πού αποθηκεύονται όλα τα δεδομένα (εύκολο backup: αντιγράφεις τον φάκελο)
DATA_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Αρχείο Αποδείξεων")
ARCHIVE_DIR = os.path.join(DATA_DIR, "Αποδείξεις")       # τα αρχεία PDF
PENDING_DIR = os.path.join(DATA_DIR, "Προς Έλεγχο")      # προσωρινά από email
EXPORT_DIR = os.path.join(DATA_DIR, "Εξαγωγές PDF")      # επίσημα PDF προς εκτύπωση
DB_PATH = os.path.join(DATA_DIR, "receipts.db")

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp"}
PDF_EXTS = {".pdf"}

for d in (DATA_DIR, ARCHIVE_DIR, PENDING_DIR, EXPORT_DIR):
    os.makedirs(d, exist_ok=True)

# Το native παράθυρο (ορίζεται στο main()) — για διαλόγους επιλογής φακέλου.
WEBVIEW_WINDOW = None

# Βρες τα templates/static — και όταν τρέχει από .exe (PyInstaller)
if getattr(sys, "frozen", False):
    RES_DIR = sys._MEIPASS  # φάκελος όπου το PyInstaller ξεπακετάρει τα αρχεία
else:
    RES_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(RES_DIR, "templates"),
    static_folder=os.path.join(RES_DIR, "static"),
)


# ---------------------------------------------------------------------------
#  Βάση δεδομένων
# ---------------------------------------------------------------------------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db():
    conn = get_db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS receipts (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            business      TEXT NOT NULL,
            vendor        TEXT,
            receipt_date  TEXT,
            amount        REAL,
            category      TEXT,
            notes         TEXT,
            file_path     TEXT,
            thumb_path    TEXT,
            source        TEXT,
            email_uid     TEXT,
            created_at    TEXT
        );

        CREATE TABLE IF NOT EXISTS pending (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            business       TEXT NOT NULL,
            from_addr      TEXT,
            subject        TEXT,
            email_date     TEXT,
            suggested_vendor TEXT,
            temp_path      TEXT,
            original_name  TEXT,
            email_uid      TEXT,
            created_at     TEXT
        );

        CREATE TABLE IF NOT EXISTS seen_email (
            business  TEXT NOT NULL,
            uid       TEXT NOT NULL,
            PRIMARY KEY (business, uid)
        );

        CREATE TABLE IF NOT EXISTS settings (
            key    TEXT PRIMARY KEY,
            value  TEXT
        );
        """
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
#  Βοηθητικά
# ---------------------------------------------------------------------------

def now_iso():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_iso():
    return dt.date.today().strftime("%Y-%m-%d")


def safe_name(text, fallback="apodeixi"):
    text = (text or "").strip()
    text = re.sub(r"[^\w\-.]+", "_", text, flags=re.UNICODE)
    text = text.strip("_")
    return text or fallback


def ext_of(filename):
    return os.path.splitext(filename or "")[1].lower()


def is_image(filename):
    return ext_of(filename) in IMAGE_EXTS


def is_pdf(filename):
    return ext_of(filename) in PDF_EXTS


def year_of(date_str):
    if date_str and len(date_str) >= 4 and date_str[:4].isdigit():
        return date_str[:4]
    return "Χωρίς ημερομηνία"


# ---------------------------------------------------------------------------
#  Αποθήκευση αρχείου απόδειξης  (εικόνα ή PDF -> αποθηκευμένο PDF + thumbnail)
# ---------------------------------------------------------------------------

def store_files(src_path, business, receipt_id, original_name, receipt_date=None):
    """Μετατρέπει το αρχείο σε PDF, δημιουργεί thumbnail. Επιστρέφει (pdf_path, thumb_path)."""
    from PIL import Image, ImageOps

    # Αρχειοθέτηση με βάση το έτος της ΑΠΟΔΕΙΞΗΣ (όχι της ημέρας καταχώρησης).
    year = year_of(receipt_date)
    if not year.isdigit():
        year = str(dt.date.today().year)
    business_dir = os.path.join(ARCHIVE_DIR, BUSINESSES.get(business, business))
    dest_dir = os.path.join(business_dir, year)
    thumbs_dir = os.path.join(business_dir, "thumbs")
    os.makedirs(dest_dir, exist_ok=True)
    os.makedirs(thumbs_dir, exist_ok=True)

    pdf_path = os.path.join(dest_dir, f"{receipt_id}.pdf")
    thumb_path = None

    if is_pdf(original_name) or is_pdf(src_path):
        shutil.copyfile(src_path, pdf_path)
        # Προσπάθεια για thumbnail από την 1η σελίδα (αν λείπει, δείχνουμε εικονίδιο)
        thumb_path = _pdf_thumbnail(pdf_path, thumbs_dir, receipt_id)
    else:
        import img2pdf
        im = Image.open(src_path)
        im = ImageOps.exif_transpose(im)  # διόρθωση προσανατολισμού από κινητό
        if im.mode != "RGB":
            im = im.convert("RGB")

        tmp_jpg = os.path.join(dest_dir, f"{receipt_id}_tmp.jpg")
        im.save(tmp_jpg, "JPEG", quality=90)
        with open(pdf_path, "wb") as f:
            f.write(img2pdf.convert(tmp_jpg))
        os.remove(tmp_jpg)

        # thumbnail
        th = im.copy()
        th.thumbnail((500, 500))
        thumb_path = os.path.join(thumbs_dir, f"{receipt_id}.jpg")
        th.save(thumb_path, "JPEG", quality=80)

    return pdf_path, thumb_path


def _pdf_thumbnail(pdf_path, thumbs_dir, receipt_id):
    """Best-effort thumbnail από PDF. Αν δεν γίνεται, επιστρέφει None."""
    return None  # (αποφυγή βαριάς εξάρτησης· τα PDF δείχνουν εικονίδιο)


# ---------------------------------------------------------------------------
#  Δημιουργία επίσημου PDF (σελίδα στοιχείων + η απόδειξη)
# ---------------------------------------------------------------------------

_FONTS_READY = False


def _ensure_fonts():
    global _FONTS_READY
    if _FONTS_READY:
        return
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    win_fonts = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    try:
        pdfmetrics.registerFont(TTFont("GreekFont", os.path.join(win_fonts, "arial.ttf")))
        pdfmetrics.registerFont(TTFont("GreekFont-Bold", os.path.join(win_fonts, "arialbd.ttf")))
    except Exception:
        # fallback: Helvetica (χωρίς πλήρη υποστήριξη ελληνικών)
        pass
    _FONTS_READY = True


def fmt_money(amount):
    """54321.5 -> '54.321,50 €' (ελληνική μορφή). None -> '—'."""
    if amount is None:
        return "—"
    return f"{amount:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def _pdf_fonts():
    _ensure_fonts()
    try:
        from reportlab.pdfbase import pdfmetrics
        names = pdfmetrics.getRegisteredFontNames()
        font = "GreekFont" if "GreekFont" in names else "Helvetica"
        font_b = "GreekFont-Bold" if "GreekFont-Bold" in names else "Helvetica-Bold"
    except Exception:
        font, font_b = "Helvetica", "Helvetica-Bold"
    return font, font_b


def _draw_receipt_page(c, receipt, font, font_b):
    """Σχεδιάζει μία σελίδα στοιχείων για μια απόδειξη (και κλείνει τη σελίδα)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm

    width, height = A4
    y = height - 30 * mm

    business_name = BUSINESSES.get(receipt["business"], receipt["business"])
    c.setFont(font_b, 20)
    c.drawString(25 * mm, y, business_name)
    y -= 8 * mm
    c.setFont(font, 12)
    c.setFillGray(0.35)
    c.drawString(25 * mm, y, "Παραστατικό / Απόδειξη — αρχειοθετημένο αντίγραφο")
    c.setFillGray(0)
    y -= 6 * mm
    c.setStrokeGray(0.8)
    c.line(25 * mm, y, width - 25 * mm, y)
    y -= 14 * mm

    def row(label, value):
        nonlocal y
        c.setFont(font_b, 12)
        c.drawString(25 * mm, y, label)
        c.setFont(font, 12)
        c.drawString(70 * mm, y, value if value not in (None, "") else "—")
        y -= 10 * mm

    row("Προμηθευτής:", receipt["vendor"])
    row("Ημερομηνία:", receipt["receipt_date"])
    row("Ποσό:", fmt_money(receipt["amount"]))
    row("Κατηγορία:", receipt["category"])
    if receipt["notes"]:
        row("Σημειώσεις:", receipt["notes"])

    c.setFont(font, 9)
    c.setFillGray(0.5)
    c.drawString(25 * mm, 18 * mm, f"Αρχειοθετήθηκε: {receipt['created_at']}   ·   Κωδικός: #{receipt['id']}")
    c.setFillGray(0)
    c.showPage()


def _merge_receipt_content(out, receipt):
    """Προσθέτει στο out (pikepdf) τις σελίδες του πρωτότυπου αρχείου της απόδειξης."""
    import pikepdf
    content_path = receipt["file_path"]
    if content_path and os.path.exists(content_path):
        try:
            with pikepdf.open(content_path) as content:
                out.pages.extend(content.pages)
        except Exception:
            pass


def build_official_pdf(receipt):
    """Επιστρέφει bytes ενός PDF: σελίδα στοιχείων + οι σελίδες της απόδειξης."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    import pikepdf

    font, font_b = _pdf_fonts()
    header_buf = io.BytesIO()
    c = canvas.Canvas(header_buf, pagesize=A4)
    _draw_receipt_page(c, receipt, font, font_b)
    c.save()
    header_buf.seek(0)

    out = pikepdf.Pdf.new()
    with pikepdf.open(header_buf) as h:
        out.pages.extend(h.pages)
    _merge_receipt_content(out, receipt)
    result = io.BytesIO()
    out.save(result)
    result.seek(0)
    return result.read()


def build_bulk_pdf(business, rows, filter_desc):
    """Ένα ενιαίο PDF: εξώφυλλο-σύνοψη + όλες οι αποδείξεις (στοιχεία + πρωτότυπο)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    import pikepdf

    font, font_b = _pdf_fonts()
    width, height = A4

    # --- Εξώφυλλο / σύνοψη ---
    cover = io.BytesIO()
    c = canvas.Canvas(cover, pagesize=A4)
    y = height - 28 * mm
    c.setFont(font_b, 22)
    c.drawString(25 * mm, y, BUSINESSES.get(business, business))
    y -= 9 * mm
    c.setFont(font, 13)
    c.setFillGray(0.35)
    c.drawString(25 * mm, y, "Συγκεντρωτικό αρχείο παραστατικών")
    c.setFillGray(0)
    y -= 7 * mm
    c.setStrokeGray(0.8)
    c.line(25 * mm, y, width - 25 * mm, y)
    y -= 12 * mm

    c.setFont(font, 12)
    c.drawString(25 * mm, y, f"Επιλογή: {filter_desc}")
    y -= 8 * mm
    total = sum((r["amount"] or 0) for r in rows)
    c.drawString(25 * mm, y, f"Πλήθος παραστατικών: {len(rows)}")
    y -= 8 * mm
    c.setFont(font_b, 13)
    c.drawString(25 * mm, y, f"Συνολικό ποσό: {fmt_money(total)}")
    y -= 12 * mm

    # Υποσύνολα ανά κατηγορία
    by_cat = {}
    for r in rows:
        cat = (r["category"] or "Χωρίς κατηγορία")
        by_cat[cat] = by_cat.get(cat, 0) + (r["amount"] or 0)
    if by_cat:
        c.setFont(font_b, 12)
        c.drawString(25 * mm, y, "Ανά κατηγορία:")
        y -= 8 * mm
        c.setFont(font, 11)
        for cat in sorted(by_cat, key=lambda k: by_cat[k], reverse=True):
            if y < 30 * mm:
                c.showPage(); y = height - 28 * mm; c.setFont(font, 11)
            c.drawString(30 * mm, y, f"• {cat}")
            c.drawRightString(width - 25 * mm, y, fmt_money(by_cat[cat]))
            y -= 7 * mm

    c.setFont(font, 9)
    c.setFillGray(0.5)
    c.drawString(25 * mm, 15 * mm, f"Δημιουργήθηκε: {now_iso()}")
    c.setFillGray(0)
    c.showPage()

    # Σελίδα στοιχείων για κάθε απόδειξη (πριν το αντίστοιχο πρωτότυπο)
    for r in rows:
        _draw_receipt_page(c, r, font, font_b)
    c.save()
    cover.seek(0)

    # Χτίζουμε το τελικό: [εξώφυλλο] + για κάθε απόδειξη [σελίδα στοιχείων] + [πρωτότυπο]
    # (Το cover PDF έχει: σελίδα 1 = εξώφυλλο, μετά 1 σελίδα στοιχείων ανά απόδειξη.)
    out = pikepdf.Pdf.new()
    with pikepdf.open(cover) as cov:
        cov_pages = list(cov.pages)
        out.pages.append(cov_pages[0])  # εξώφυλλο
        for idx, r in enumerate(rows):
            out.pages.append(cov_pages[1 + idx])   # σελίδα στοιχείων
            _merge_receipt_content(out, r)          # το πρωτότυπο αρχείο
        result = io.BytesIO()
        out.save(result)
    result.seek(0)
    return result.read()


# ---------------------------------------------------------------------------
#  Δημιουργία εγγραφής απόδειξης
# ---------------------------------------------------------------------------

def create_receipt(business, vendor, date, amount, category, notes,
                   src_path, original_name, source, email_uid=None):
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO receipts
           (business, vendor, receipt_date, amount, category, notes,
            file_path, thumb_path, source, email_uid, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (business, vendor, date, amount, category, notes,
         "", None, source, email_uid, now_iso()),
    )
    rid = cur.lastrowid
    conn.commit()

    pdf_path, thumb_path = store_files(src_path, business, rid, original_name, receipt_date=date)
    conn.execute(
        "UPDATE receipts SET file_path=?, thumb_path=? WHERE id=?",
        (pdf_path, thumb_path, rid),
    )
    conn.commit()
    conn.close()
    return rid


# ---------------------------------------------------------------------------
#  API — Ρυθμίσεις / λίστες
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/config")
def api_config():
    return jsonify({
        "businesses": [{"key": k, "name": v} for k, v in BUSINESSES.items()],
        "categories": CATEGORIES,
        "data_dir": DATA_DIR,
    })


SORTS = {
    "date_desc": ("receipt_date", "id", True),
    "date_asc":  ("receipt_date", "id", False),
    "amount_desc": ("amount", "id", True),
    "amount_asc":  ("amount", "id", False),
    "vendor_asc":  ("vendor", "id", False),
}


def filter_receipts(business, q="", category="", year="", sort="date_desc"):
    """Επιστρέφει (rows_φιλτραρισμένες, όλα_τα_έτη) για μια επιχείρηση."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM receipts WHERE business=?", (business,)
    ).fetchall()
    conn.close()

    q = (q or "").strip().lower()
    years = set()
    out = []
    for r in rows:
        years.add(year_of(r["receipt_date"]))
        if category and (r["category"] or "") != category:
            continue
        if year and year_of(r["receipt_date"]) != year:
            continue
        if q:
            hay = " ".join(str(r[k] or "") for k in ("vendor", "category", "notes", "receipt_date")).lower()
            if q not in hay:
                continue
        out.append(r)

    key, tiebreak, reverse = SORTS.get(sort, SORTS["date_desc"])

    def sort_key(r):
        v = r[key]
        if key == "amount":
            v = v if v is not None else -1
        else:
            v = (v or "")
        return (v, r[tiebreak])

    out.sort(key=sort_key, reverse=reverse)
    return out, years


@app.route("/api/receipts")
def api_receipts():
    business = request.args.get("business", "")
    rows, years = filter_receipts(
        business,
        request.args.get("q") or "",
        request.args.get("category") or "",
        request.args.get("year") or "",
        request.args.get("sort") or "date_desc",
    )

    items = [{
        "id": r["id"],
        "vendor": r["vendor"],
        "receipt_date": r["receipt_date"],
        "amount": r["amount"],
        "category": r["category"],
        "notes": r["notes"],
        "source": r["source"],
        "has_thumb": bool(r["thumb_path"] and os.path.exists(r["thumb_path"])),
    } for r in rows]

    # ανάλυση ανά κατηγορία (για τον πίνακα σύνοψης)
    by_cat = {}
    for r in rows:
        cat = r["category"] or "Χωρίς κατηγορία"
        by_cat[cat] = by_cat.get(cat, 0) + (r["amount"] or 0)
    by_category = [{"category": k, "total": v}
                   for k, v in sorted(by_cat.items(), key=lambda kv: kv[1], reverse=True)]

    total = sum((i["amount"] or 0) for i in items)
    return jsonify({
        "items": items,
        "years": sorted(years, reverse=True),
        "count": len(items),
        "total": total,
        "by_category": by_category,
    })


@app.route("/api/counts")
def api_counts():
    """Πλήθος αποδείξεων ανά επιχείρηση (για τα σήματα στις καρτέλες)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT business, COUNT(*) AS n FROM receipts GROUP BY business"
    ).fetchall()
    conn.close()
    return jsonify({r["business"]: r["n"] for r in rows})


@app.route("/api/check-duplicate")
def api_check_duplicate():
    """Προειδοποίηση αν υπάρχει ήδη απόδειξη με ίδια επιχείρηση/ημερομηνία/ποσό."""
    business = request.args.get("business", "")
    date = (request.args.get("date") or "").strip()
    amount_raw = (request.args.get("amount") or "").strip().replace(",", ".")
    if not date or not amount_raw:
        return jsonify({"duplicate": False})
    try:
        amount = float(amount_raw)
    except ValueError:
        return jsonify({"duplicate": False})
    conn = get_db()
    r = conn.execute(
        "SELECT vendor FROM receipts WHERE business=? AND receipt_date=? AND amount=? LIMIT 1",
        (business, date, amount),
    ).fetchone()
    conn.close()
    if r:
        return jsonify({"duplicate": True, "vendor": r["vendor"] or ""})
    return jsonify({"duplicate": False})


@app.route("/api/suggest-category")
def api_suggest_category():
    """Προτείνει κατηγορία με βάση την πιο πρόσφατη απόδειξη του ίδιου προμηθευτή."""
    business = request.args.get("business", "")
    vendor = (request.args.get("vendor") or "").strip()
    if not vendor:
        return jsonify({"category": ""})
    # Η σύγκριση γίνεται στην Python: το LOWER() της SQLite δεν πιάνει ελληνικά.
    target = vendor.casefold()
    conn = get_db()
    rows = conn.execute(
        "SELECT vendor, category FROM receipts "
        "WHERE business=? AND category IS NOT NULL AND category<>'' "
        "ORDER BY id DESC",
        (business,),
    ).fetchall()
    conn.close()
    for r in rows:
        if (r["vendor"] or "").strip().casefold() == target:
            return jsonify({"category": r["category"]})
    return jsonify({"category": ""})


@app.route("/api/receipts", methods=["POST"])
def api_create_receipt():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "Δεν επιλέχθηκε αρχείο."}), 400
    if not (is_image(f.filename) or is_pdf(f.filename)):
        return jsonify({"error": "Επιτρέπονται μόνο εικόνες (JPG/PNG) ή αρχεία PDF."}), 400

    business = request.form.get("business", "")
    if business not in BUSINESSES:
        return jsonify({"error": "Άκυρη επιχείρηση."}), 400

    vendor = (request.form.get("vendor") or "").strip()
    date = (request.form.get("date") or today_iso()).strip()
    amount_raw = (request.form.get("amount") or "").strip().replace(",", ".")
    amount = None
    if amount_raw:
        try:
            amount = float(amount_raw)
        except ValueError:
            return jsonify({"error": "Το ποσό δεν είναι έγκυρος αριθμός."}), 400
    category = (request.form.get("category") or "").strip()
    notes = (request.form.get("notes") or "").strip()

    tmp = os.path.join(PENDING_DIR, f"upload_{int(time.time()*1000)}{ext_of(f.filename)}")
    f.save(tmp)
    try:
        rid = create_receipt(business, vendor, date, amount, category, notes,
                             tmp, f.filename, source="upload")
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return jsonify({"ok": True, "id": rid})


@app.route("/api/receipts/<int:rid>", methods=["POST"])
def api_update_receipt(rid):
    data = request.get_json(force=True)
    conn = get_db()
    r = conn.execute("SELECT * FROM receipts WHERE id=?", (rid,)).fetchone()
    if not r:
        conn.close()
        return jsonify({"error": "Δεν βρέθηκε."}), 404
    amount = data.get("amount")
    if amount in ("", None):
        amount = None
    else:
        try:
            amount = float(str(amount).replace(",", "."))
        except ValueError:
            conn.close()
            return jsonify({"error": "Άκυρο ποσό."}), 400
    conn.execute(
        "UPDATE receipts SET vendor=?, receipt_date=?, amount=?, category=?, notes=? WHERE id=?",
        (data.get("vendor", "").strip(), data.get("date", "").strip(), amount,
         data.get("category", "").strip(), data.get("notes", "").strip(), rid),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/receipts/<int:rid>", methods=["DELETE"])
def api_delete_receipt(rid):
    conn = get_db()
    r = conn.execute("SELECT * FROM receipts WHERE id=?", (rid,)).fetchone()
    if not r:
        conn.close()
        return jsonify({"error": "Δεν βρέθηκε."}), 404
    for p in (r["file_path"], r["thumb_path"]):
        if p and os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass
    conn.execute("DELETE FROM receipts WHERE id=?", (rid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/receipts/<int:rid>/thumb")
def api_thumb(rid):
    conn = get_db()
    r = conn.execute("SELECT thumb_path FROM receipts WHERE id=?", (rid,)).fetchone()
    conn.close()
    if r and r["thumb_path"] and os.path.exists(r["thumb_path"]):
        return send_file(r["thumb_path"], mimetype="image/jpeg")
    abort(404)


@app.route("/api/open-data-folder", methods=["POST"])
def api_open_data_folder():
    """Ανοίγει τον φάκελο με τα δεδομένα του χρήστη στην Εξερεύνηση των Windows."""
    try:
        os.startfile(DATA_DIR)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


@app.route("/api/backup", methods=["POST"])
def api_backup():
    """Αντιγράφει ΟΛΑ τα δεδομένα σε φάκελο/USB που επιλέγει ο χρήστης."""
    import webview

    dest_root = None
    if WEBVIEW_WINDOW is not None:
        try:
            result = WEBVIEW_WINDOW.create_file_dialog(webview.FOLDER_DIALOG)
        except Exception as e:
            return jsonify({"error": f"Δεν άνοιξε ο διάλογος επιλογής φακέλου: {e}"}), 500
        if result:
            dest_root = result[0] if isinstance(result, (list, tuple)) else result
    if not dest_root:
        return jsonify({"cancelled": True})

    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    dest = os.path.join(dest_root, f"Αρχείο Αποδείξεων - Αντίγραφο {stamp}")
    try:
        shutil.copytree(DATA_DIR, dest)
    except Exception as e:
        return jsonify({"error": f"Αποτυχία αντιγραφής: {e}"}), 500

    # πόσα παραστατικά αντιγράφηκαν (για επιβεβαίωση στον χρήστη)
    try:
        conn = get_db()
        n = conn.execute("SELECT COUNT(*) AS n FROM receipts").fetchone()["n"]
        conn.close()
    except Exception:
        n = None
    return jsonify({"ok": True, "path": dest, "count": n})


@app.route("/api/receipts/<int:rid>/open", methods=["POST"])
def api_open(rid):
    conn = get_db()
    r = conn.execute("SELECT file_path FROM receipts WHERE id=?", (rid,)).fetchone()
    conn.close()
    if not r or not r["file_path"] or not os.path.exists(r["file_path"]):
        return jsonify({"error": "Το αρχείο δεν βρέθηκε."}), 404
    try:
        os.startfile(r["file_path"])  # ανοίγει στον προεπιλεγμένο προβολέα (Windows)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


@app.route("/api/receipts/<int:rid>/export", methods=["POST"])
def api_export(rid):
    conn = get_db()
    r = conn.execute("SELECT * FROM receipts WHERE id=?", (rid,)).fetchone()
    conn.close()
    if not r:
        return jsonify({"error": "Δεν βρέθηκε."}), 404
    pdf_bytes = build_official_pdf(r)
    fname = f"{safe_name(BUSINESSES.get(r['business'], r['business']))}_{safe_name(r['vendor'])}_{r['receipt_date']}_#{r['id']}.pdf"
    out_path = os.path.join(EXPORT_DIR, fname)
    with open(out_path, "wb") as fh:
        fh.write(pdf_bytes)
    try:
        os.startfile(out_path)
    except Exception:
        pass
    return jsonify({"ok": True, "path": out_path})


@app.route("/api/export-bulk", methods=["POST"])
def api_export_bulk():
    """Ένα ενιαίο PDF με όλες τις αποδείξεις της τρέχουσας επιλογής (φίλτρα)."""
    data = request.get_json(force=True) or {}
    business = data.get("business", "")
    if business not in BUSINESSES:
        return jsonify({"error": "Άκυρη επιχείρηση."}), 400

    q = data.get("q") or ""
    category = data.get("category") or ""
    year = data.get("year") or ""
    rows, _ = filter_receipts(business, q, category, year, "date_asc")
    if not rows:
        return jsonify({"error": "Δεν υπάρχουν αποδείξεις για εξαγωγή με αυτά τα φίλτρα."}), 400

    # Περιγραφή επιλογής (για το εξώφυλλο)
    parts = []
    if year:
        parts.append(f"Έτος {year}")
    if category:
        parts.append(f"Κατηγορία: {category}")
    if q:
        parts.append(f"Αναζήτηση: «{q}»")
    filter_desc = " · ".join(parts) if parts else "Όλες οι αποδείξεις"

    pdf_bytes = build_bulk_pdf(business, rows, filter_desc)
    label = safe_name("_".join(p for p in (year, category) if p)) or "ola"
    fname = f"Συγκεντρωτικό_{safe_name(BUSINESSES.get(business, business))}_{label}_{today_iso()}.pdf"
    out_path = os.path.join(EXPORT_DIR, fname)
    with open(out_path, "wb") as fh:
        fh.write(pdf_bytes)
    try:
        os.startfile(out_path)
    except Exception:
        pass
    return jsonify({"ok": True, "path": out_path, "count": len(rows)})


# ---------------------------------------------------------------------------
#  API — Ρυθμίσεις email
# ---------------------------------------------------------------------------

#  Ο κωδικός του email ΔΕΝ αποθηκεύεται στη βάση. Πηγαίνει στο Windows
#  Credential Locker (μέσω keyring), που τον κρυπτογραφεί με το DPAPI του
#  λογαριασμού σας — δηλαδή μόνο ο δικός σας χρήστης Windows μπορεί να τον
#  διαβάσει. Στη βάση μένουν μόνο host / θύρα / όνομα χρήστη / φάκελος.
KEYRING_SERVICE = "ArxeioApodeixeon"


def get_password(business):
    """Ο κωδικός email της επιχείρησης, ή None αν δεν έχει καταχωρηθεί."""
    try:
        import keyring
        return keyring.get_password(KEYRING_SERVICE, business)
    except Exception:
        return None


def set_password(business, password):
    """Αποθηκεύει τον κωδικό. Επιστρέφει μήνυμα σφάλματος, ή None αν πέτυχε."""
    try:
        import keyring
        keyring.set_password(KEYRING_SERVICE, business, password)
        return None
    except Exception as e:
        return str(e)


def get_email_settings(business):
    conn = get_db()
    r = conn.execute("SELECT value FROM settings WHERE key=?", (f"email_{business}",)).fetchone()
    conn.close()
    if not r:
        return {}
    cfg = json.loads(r["value"])

    # Μετάβαση από παλαιότερη έκδοση: ο κωδικός ήταν αποθηκευμένος (κωδικοποιημένος
    # σε base64) μέσα στη βάση. Τον μεταφέρουμε μία φορά στο Credential Locker
    # και τον σβήνουμε από εκεί.
    legacy = cfg.pop("password", None)
    if legacy:
        try:
            plain = base64.b64decode(legacy).decode("utf-8")
        except Exception:
            plain = None
        if plain and not get_password(business):
            set_password(business, plain)
        save_email_settings(business, cfg)

    return cfg


def save_email_settings(business, cfg):
    cfg = {k: v for k, v in cfg.items() if k != "password"}
    conn = get_db()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (f"email_{business}", json.dumps(cfg)),
    )
    conn.commit()
    conn.close()


@app.route("/api/email-settings")
def api_get_email_settings():
    business = request.args.get("business", "")
    safe = dict(get_email_settings(business))
    safe.pop("password", None)          # ασφάλεια: ποτέ δεν φεύγει κωδικός προς τη διεπαφή
    safe["has_password"] = bool(get_password(business))
    return jsonify(safe)


@app.route("/api/email-settings", methods=["POST"])
def api_save_email_settings():
    data = request.get_json(force=True)
    business = data.get("business", "")
    if business not in BUSINESSES:
        return jsonify({"error": "Άκυρη επιχείρηση."}), 400
    get_email_settings(business)   # ολοκληρώνει τυχόν μετάβαση από παλιά έκδοση
    cfg = {
        "host": data.get("host", "").strip(),
        "port": int(data.get("port") or 993),
        "username": data.get("username", "").strip(),
        "folder": data.get("folder", "INBOX").strip() or "INBOX",
        "since_days": int(data.get("since_days") or 30),
    }
    save_email_settings(business, cfg)

    pw = data.get("password", "")
    if pw:  # αν έμεινε κενό, κρατάμε τον ήδη αποθηκευμένο
        err = set_password(business, pw)
        if err:
            return jsonify({"error": f"Ο κωδικός δεν αποθηκεύτηκε: {err}"}), 500
    return jsonify({"ok": True})


def _decode_hdr(value):
    if not value:
        return ""
    parts = decode_header(value)
    out = ""
    for text, enc in parts:
        if isinstance(text, bytes):
            try:
                out += text.decode(enc or "utf-8", errors="replace")
            except (LookupError, TypeError):
                out += text.decode("utf-8", errors="replace")
        else:
            out += text
    return out


def _extract_attachments(msg):
    attachments = []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        filename = part.get_filename()
        ctype = part.get_content_type()
        disp = (part.get("Content-Disposition") or "").lower()
        is_att = "attachment" in disp or (filename is not None)
        wanted = ctype == "application/pdf" or ctype.startswith("image/")
        if is_att and wanted and filename:
            try:
                payload = part.get_payload(decode=True)
            except Exception:
                payload = None
            if payload:
                attachments.append((_decode_hdr(filename), payload))
    return attachments


@app.route("/api/email-sync", methods=["POST"])
def api_email_sync():
    import imaplib
    import email as email_mod

    business = (request.get_json(force=True) or {}).get("business", "")
    cfg = get_email_settings(business)
    password = get_password(business)
    if not cfg.get("host") or not cfg.get("username") or not password:
        return jsonify({"error": "Λείπουν οι ρυθμίσεις email. Συμπληρώστε τα στοιχεία πρώτα."}), 400

    try:
        M = imaplib.IMAP4_SSL(cfg["host"], int(cfg.get("port", 993)))
        M.login(cfg["username"], password)
    except Exception as e:
        return jsonify({"error": f"Αποτυχία σύνδεσης: {e}"}), 400

    new_count = 0
    try:
        M.select(cfg.get("folder", "INBOX"))
        since = (dt.date.today() - dt.timedelta(days=int(cfg.get("since_days", 30)))).strftime("%d-%b-%Y")
        typ, data = M.uid("search", None, f"(SINCE {since})")
        uids = data[0].split() if data and data[0] else []

        conn = get_db()
        seen = set(row["uid"] for row in conn.execute(
            "SELECT uid FROM seen_email WHERE business=?", (business,)).fetchall())

        for uid in uids[-250:]:
            uid_s = uid.decode()
            if uid_s in seen:
                continue
            typ, msgdata = M.uid("fetch", uid, "(RFC822)")
            if not msgdata or not msgdata[0]:
                continue
            msg = email_mod.message_from_bytes(msgdata[0][1])
            atts = _extract_attachments(msg)
            if atts:
                from_name, from_email = parseaddr(_decode_hdr(msg.get("From", "")))
                subject = _decode_hdr(msg.get("Subject", ""))
                try:
                    edate = parsedate_to_datetime(msg.get("Date"))
                    edate_s = edate.strftime("%Y-%m-%d") if edate else today_iso()
                except Exception:
                    edate_s = today_iso()
                vendor_guess = from_name or (from_email.split("@")[-1] if from_email else "")
                for fn, payload in atts:
                    temp_path = os.path.join(PENDING_DIR, f"{business}_{uid_s}_{safe_name(fn)}")
                    with open(temp_path, "wb") as fh:
                        fh.write(payload)
                    conn.execute(
                        """INSERT INTO pending
                           (business, from_addr, subject, email_date, suggested_vendor,
                            temp_path, original_name, email_uid, created_at)
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                        (business, from_email, subject, edate_s, vendor_guess,
                         temp_path, fn, uid_s, now_iso()),
                    )
                    new_count += 1
            conn.execute(
                "INSERT OR IGNORE INTO seen_email (business, uid) VALUES (?,?)",
                (business, uid_s),
            )
            conn.commit()
        conn.close()
    finally:
        try:
            M.logout()
        except Exception:
            pass

    return jsonify({"ok": True, "new": new_count})


# ---------------------------------------------------------------------------
#  API — Προς έλεγχο (pending από email)
# ---------------------------------------------------------------------------

@app.route("/api/pending")
def api_pending():
    business = request.args.get("business", "")
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM pending WHERE business=? ORDER BY id DESC", (business,)
    ).fetchall()
    conn.close()
    items = [{
        "id": r["id"],
        "from_addr": r["from_addr"],
        "subject": r["subject"],
        "email_date": r["email_date"],
        "suggested_vendor": r["suggested_vendor"],
        "original_name": r["original_name"],
    } for r in rows]
    return jsonify({"items": items, "count": len(items)})


@app.route("/api/pending/<int:pid>/preview")
def api_pending_preview(pid):
    conn = get_db()
    r = conn.execute("SELECT temp_path, original_name FROM pending WHERE id=?", (pid,)).fetchone()
    conn.close()
    if not r or not os.path.exists(r["temp_path"]):
        abort(404)
    if is_pdf(r["original_name"]):
        return send_file(r["temp_path"], mimetype="application/pdf")
    return send_file(r["temp_path"])


@app.route("/api/pending/<int:pid>/approve", methods=["POST"])
def api_pending_approve(pid):
    data = request.get_json(force=True)
    conn = get_db()
    r = conn.execute("SELECT * FROM pending WHERE id=?", (pid,)).fetchone()
    if not r:
        conn.close()
        return jsonify({"error": "Δεν βρέθηκε."}), 404
    conn.close()

    amount = data.get("amount")
    if amount in ("", None):
        amount = None
    else:
        try:
            amount = float(str(amount).replace(",", "."))
        except ValueError:
            return jsonify({"error": "Άκυρο ποσό."}), 400

    create_receipt(
        r["business"],
        (data.get("vendor") or r["suggested_vendor"] or "").strip(),
        (data.get("date") or r["email_date"] or today_iso()).strip(),
        amount,
        (data.get("category") or "").strip(),
        (data.get("notes") or "").strip(),
        r["temp_path"], r["original_name"], source="email", email_uid=r["email_uid"],
    )

    conn = get_db()
    conn.execute("DELETE FROM pending WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    if r["temp_path"] and os.path.exists(r["temp_path"]):
        try:
            os.remove(r["temp_path"])
        except OSError:
            pass
    return jsonify({"ok": True})


@app.route("/api/pending/clear", methods=["POST"])
def api_pending_clear():
    """Απορρίπτει ΟΛΑ τα παραστατικά «προς έλεγχο» μιας επιχείρησης με τη μία."""
    business = (request.get_json(force=True) or {}).get("business", "")
    if business not in BUSINESSES:
        return jsonify({"error": "Άκυρη επιχείρηση."}), 400
    conn = get_db()
    rows = conn.execute(
        "SELECT temp_path FROM pending WHERE business=?", (business,)
    ).fetchall()
    conn.execute("DELETE FROM pending WHERE business=?", (business,))
    conn.commit()
    conn.close()
    for r in rows:
        p = r["temp_path"]
        if p and os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass
    return jsonify({"ok": True, "removed": len(rows)})


@app.route("/api/pending/<int:pid>/discard", methods=["POST"])
def api_pending_discard(pid):
    conn = get_db()
    r = conn.execute("SELECT * FROM pending WHERE id=?", (pid,)).fetchone()
    if not r:
        conn.close()
        return jsonify({"error": "Δεν βρέθηκε."}), 404
    conn.execute("DELETE FROM pending WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    if r["temp_path"] and os.path.exists(r["temp_path"]):
        try:
            os.remove(r["temp_path"])
        except OSError:
            pass
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
#  Εκκίνηση
# ---------------------------------------------------------------------------

def run_flask(port):
    app.run(host="127.0.0.1", port=port, threaded=True, use_reloader=False)


def main():
    import socket
    import webview
    global WEBVIEW_WINDOW

    init_db()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    t = threading.Thread(target=run_flask, args=(port,), daemon=True)
    t.start()

    # μικρή αναμονή να σηκωθεί ο server
    time.sleep(0.8)

    WEBVIEW_WINDOW = webview.create_window(
        APP_TITLE,
        f"http://127.0.0.1:{port}/",
        width=1240,
        height=820,
        min_size=(900, 620),
    )
    webview.start()


if __name__ == "__main__":
    main()
