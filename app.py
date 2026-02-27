from flask import Flask, render_template, request, redirect, make_response, send_file, session, flash, url_for, jsonify, send_from_directory, abort
from weasyprint import HTML
import sqlite3
import os
import shutil
import csv
from io import StringIO
from datetime import datetime, timedelta
from functools import wraps
from werkzeug.security import check_password_hash
import unicodedata
import uuid
import zipfile
from zoneinfo import ZoneInfo
from io import BytesIO
from email.message import EmailMessage
import smtplib
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError
import json




# ⚠️ IMPORTANT : en prod (Render), NE PAS recopier une base automatiquement
# Ça peut restaurer une vieille base et faire "disparaître" des dossiers.
# if os.path.exists("cnaps.db") and not os.path.exists("/mnt/data/cnaps.db"):
#     shutil.copy("cnaps.db", "/mnt/data/cnaps.db")

app = Flask(__name__)

# --- Sécurité + session persistante (cookie) ---
app.secret_key = os.getenv("SECRET_KEY", "change-me")  # ⚠️ Sur Render: mets un vrai SECRET_KEY

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=True,            # Render = HTTPS
    PERMANENT_SESSION_LIFETIME=timedelta(days=30)  # garde le login 30 jours
)

# Identifiants admin (via variables Render)
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "").lower().strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
PUBLIC_FORM_URL = os.getenv("PUBLIC_FORM_URL", "https://cnapsv3.onrender.com/public-form")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER or "no-reply@integrale-academy.fr")
BREVO_API_KEY = os.getenv("BREVO_API_KEY", "").strip()
BREVO_SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL", "").strip()
BREVO_SENDER_NAME = os.getenv("BREVO_SENDER_NAME", "").strip() or "Intégrale Academy"
BREVO_SMS_SENDER = os.getenv("BREVO_SMS_SENDER", "").strip()
SMS_WEBHOOK_URL = os.getenv("SMS_WEBHOOK_URL", "").strip()
ALLOW_SMS_MOCK = os.getenv("ALLOW_SMS_MOCK", "0").strip() == "1"
DRACAR_AUTH_URL = "https://espace-usagers.cnaps.interieur.gouv.fr/auth/realms/personne-physique/protocol/openid-connect/auth?client_id=cnaps&redirect_uri=https%3A%2F%2Fespace-usagers.cnaps.interieur.gouv.fr%2Fusager%2Fapp&state=e5d9b066-1e63-4147-b169-862be8c082e9&response_mode=fragment&response_type=code&scope=openid%20profile&nonce=2fb2bea0-8e33-4c8c-b6b4-fc906e587b66&code_challenge=UVZRu6sC--Y5Ypc6O2WfJfwtXo_pbb8LCoQzvB7ouHo&code_challenge_method=S256"
DRACAR_APP_URL = "https://espace-usagers.cnaps.interieur.gouv.fr/usager/app/accueil"
PUBLIC_APP_BASE_URL = os.getenv("PUBLIC_APP_BASE_URL", "https://cnapsv3.onrender.com").rstrip("/")

FORMATION_SESSIONS = {
    "APS": [
        "Du 5 janvier au 6 février 2026",
        "Du 23 mars au 27 avril 2026",
        "Du 26 mai au 29 juin 2026",
        "Du 8 juillet au 12 août 2026",
        "Du 7 septembre au 9 octobre 2026",
        "Du 3 novembre au 8 décembre 2026",
    ],
    "A3P": [
        "Du 14 octobre au 9 décembre 2025",
        "Du 5 janvier au 16 mars 2026",
        "Du 30 mars au 2 juin 2026",
        "Du 8 juin au 4 août 2026",
        "Du 1er septembre au 27 octobre 2026",
        "Du 9 novembre 2026 au 19 janvier 2027",
    ],
}

DB_NAME = "/mnt/data/cnaps.db"
UPLOAD_DIR = "/mnt/data/uploads"
MAX_DOCUMENT_SIZE_BYTES = 5 * 1024 * 1024
FRANCE_TZ = ZoneInfo("Europe/Paris")


def _now_france():
    return datetime.now(FRANCE_TZ)


def _to_db_datetime(dt: datetime):
    return dt.astimezone(FRANCE_TZ).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")


def _parse_db_datetime(value):
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                parsed = datetime.strptime(raw, fmt)
                break
            except ValueError:
                parsed = None
        if parsed is None:
            return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=FRANCE_TZ)
    return parsed.astimezone(FRANCE_TZ)


def _cnaps_expiration_label(expiration_dt):
    return expiration_dt.strftime("%d/%m/%Y à %Hh%M")


def _compute_cnaps_timing(req):
    created_at = _parse_db_datetime(req.get("espace_cnaps_created_at"))
    if created_at is None and (req.get("espace_cnaps") or "") == "Créé":
        created_at = _parse_db_datetime(req.get("updated_at"))

    if created_at is None:
        return {
            "cnaps_expiration_dt": None,
            "cnaps_expiration_label": None,
            "cnaps_reminder_4h_label": None,
            "cnaps_reminder_2h_label": None,
            "cnaps_is_expired": False,
            "cnaps_remaining": None,
        }

    expiration_dt = created_at + timedelta(hours=12)
    reminder_4h_dt = expiration_dt - timedelta(hours=4)
    reminder_2h_dt = expiration_dt - timedelta(hours=2)
    remaining = expiration_dt - _now_france()
    return {
        "cnaps_expiration_dt": expiration_dt,
        "cnaps_expiration_label": _cnaps_expiration_label(expiration_dt),
        "cnaps_reminder_4h_label": _cnaps_expiration_label(reminder_4h_dt),
        "cnaps_reminder_2h_label": _cnaps_expiration_label(reminder_2h_dt),
        "cnaps_is_expired": remaining.total_seconds() <= 0,
        "cnaps_remaining": remaining,
    }


def init_db():
    """Crée les structures nécessaires pour historiser les statuts CNAPS."""
    os.makedirs(os.path.dirname(DB_NAME), exist_ok=True)
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS statut_cnaps_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dossier_id INTEGER NOT NULL,
                statut_cnaps TEXT NOT NULL,
                changed_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (dossier_id) REFERENCES dossiers(id) ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS public_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dossier_id INTEGER,
                nom TEXT NOT NULL,
                prenom TEXT NOT NULL,
                email TEXT NOT NULL,
                date_naissance TEXT NOT NULL,
                heberge INTEGER NOT NULL DEFAULT 0,
                non_francais INTEGER NOT NULL DEFAULT 0,
                formation TEXT,
                session_date TEXT,
                espace_cnaps TEXT NOT NULL DEFAULT 'A créer',
                espace_cnaps_validation_token TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (dossier_id) REFERENCES dossiers(id) ON DELETE SET NULL
            )
        """)

        columns = {row[1] for row in conn.execute("PRAGMA table_info(public_requests)").fetchall()}
        if "espace_cnaps" not in columns:
            conn.execute("ALTER TABLE public_requests ADD COLUMN espace_cnaps TEXT NOT NULL DEFAULT 'A créer'")
        if "espace_cnaps_validation_token" not in columns:
            conn.execute("ALTER TABLE public_requests ADD COLUMN espace_cnaps_validation_token TEXT")
        if "espace_cnaps_created_at" not in columns:
            conn.execute("ALTER TABLE public_requests ADD COLUMN espace_cnaps_created_at TEXT")
        if "cnaps_reminder_4h_sent_at" not in columns:
            conn.execute("ALTER TABLE public_requests ADD COLUMN cnaps_reminder_4h_sent_at TEXT")
        if "cnaps_reminder_2h_sent_at" not in columns:
            conn.execute("ALTER TABLE public_requests ADD COLUMN cnaps_reminder_2h_sent_at TEXT")
        if "espace_cnaps_created_sms_sent_at" not in columns:
            conn.execute("ALTER TABLE public_requests ADD COLUMN espace_cnaps_created_sms_sent_at TEXT")
        if "telephone" not in columns:
            conn.execute("ALTER TABLE public_requests ADD COLUMN telephone TEXT")

        if _table_has_column(conn, "dossiers", "telephone"):
            conn.execute(
                """
                UPDATE public_requests
                SET telephone = (
                    SELECT d.telephone
                    FROM dossiers d
                    WHERE d.id = public_requests.dossier_id
                )
                WHERE (telephone IS NULL OR TRIM(telephone) = '')
                """
            )

        missing_tokens = conn.execute(
            "SELECT id FROM public_requests WHERE espace_cnaps_validation_token IS NULL OR espace_cnaps_validation_token = ''"
        ).fetchall()
        for row in missing_tokens:
            conn.execute(
                "UPDATE public_requests SET espace_cnaps_validation_token = ? WHERE id = ?",
                (str(uuid.uuid4()), row[0]),
            )

        conn.execute("""
            CREATE TABLE IF NOT EXISTS request_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id INTEGER NOT NULL,
                doc_type TEXT NOT NULL,
                original_name TEXT NOT NULL,
                stored_name TEXT NOT NULL,
                storage_path TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                is_conforme INTEGER,
                non_conformite_reason TEXT,
                uploaded_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                reviewed_at TEXT,
                FOREIGN KEY (request_id) REFERENCES public_requests(id) ON DELETE CASCADE
            )
        """)

        if not _table_has_column(conn, "request_documents", "review_status"):
            conn.execute("ALTER TABLE request_documents ADD COLUMN review_status TEXT NOT NULL DEFAULT 'pending'")

        conn.execute(
            """
            UPDATE request_documents
            SET review_status = CASE
                WHEN review_status IS NOT NULL AND review_status != '' THEN review_status
                WHEN is_conforme = 1 THEN 'conforme'
                WHEN is_conforme = 0 THEN 'non_conforme'
                ELSE 'pending'
            END
            """
        )

        conn.execute("""
            CREATE TABLE IF NOT EXISTS request_non_conformity_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id INTEGER NOT NULL,
                sent_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (request_id) REFERENCES public_requests(id) ON DELETE CASCADE
            )
        """)


def _record_statut_cnaps_history(conn, dossier_id, nouveau_statut):
    """Enregistre la date/heure précise d'un changement de statut CNAPS."""
    if not nouveau_statut:
        return

    conn.execute(
        """
        INSERT INTO statut_cnaps_history (dossier_id, statut_cnaps)
        VALUES (?, ?)
        """,
        (dossier_id, nouveau_statut),
    )


def _get_statuts_dates(conn, dossier_id):
    """Retourne pour un dossier la dernière date connue pour chaque statut CNAPS."""
    rows = conn.execute(
        """
        SELECT statut_cnaps, MAX(changed_at) AS changed_at
        FROM statut_cnaps_history
        WHERE dossier_id = ?
        GROUP BY statut_cnaps
        ORDER BY changed_at ASC
        """,
        (dossier_id,),
    ).fetchall()
    return {row["statut_cnaps"]: row["changed_at"] for row in rows}


def _table_has_column(conn, table_name, column_name):
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    return column_name in columns


def _request_phone_select_expr(conn):
    has_public_request_phone = _table_has_column(conn, "public_requests", "telephone")
    has_dossier_phone = _table_has_column(conn, "dossiers", "telephone")

    if has_public_request_phone and has_dossier_phone:
        return "COALESCE(NULLIF(pr.telephone, ''), NULLIF(d.telephone, ''))"
    if has_public_request_phone:
        return "NULLIF(pr.telephone, '')"
    if has_dossier_phone:
        return "NULLIF(d.telephone, '')"
    return "NULL"


def _new_validation_token():
    return str(uuid.uuid4())


init_db()

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        # Si pas connecté -> redirection vers /login
        if not session.get("user"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@app.before_request
def make_session_persistent():
    # Si l’utilisateur est déjà loggé, on garde une session persistante (cookie)
    if session.get("user"):
        session.permanent = True



def get_stagiaire_by_id(id):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    stagiaire = conn.execute("SELECT * FROM dossiers WHERE id = ?", (id,)).fetchone()
    conn.close()
    return stagiaire

@app.route("/")
@login_required
def index():
    # 👉 Filtre sélectionné par l’utilisateur (ou filtre par défaut)
    filtre_cnaps = request.args.get('filtre_cnaps', 'SansAcceptes')

    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row

        # Liste des statuts disponibles
        cur_statuts = conn.execute("SELECT DISTINCT statut_cnaps FROM dossiers")
        statuts_disponibles = sorted([row['statut_cnaps'] for row in cur_statuts if row['statut_cnaps']])

        # 👉 Logique du filtre
        if filtre_cnaps == 'SansAcceptes':
            # ⛔️ On masque ACCEPTÉ et REFUSÉ
            cur = conn.execute("""
                SELECT * FROM dossiers
                WHERE statut_cnaps NOT IN ('ACCEPTÉ', 'REFUSÉ')
                ORDER BY id DESC
            """)
        elif filtre_cnaps != 'Tous':
            # Filtre précis choisi par l'utilisateur
            cur = conn.execute("""
                SELECT * FROM dossiers
                WHERE statut_cnaps = ?
                ORDER BY id DESC
            """, (filtre_cnaps,))
        else:
            # Tout afficher
            cur = conn.execute("SELECT * FROM dossiers ORDER BY id DESC")

        dossiers = cur.fetchall()

        a_traiter_count = conn.execute("SELECT COUNT(*) FROM public_requests").fetchone()[0]

        # (Tu peux laisser ta partie recent_acceptes ici si tu veux)
        sept_jours = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        cur_acceptes = conn.execute("""
            SELECT nom, prenom, session
            FROM dossiers
            WHERE statut_cnaps = 'ACCEPTE'
            AND (session >= ?)
            ORDER BY session DESC
        """, (sept_jours,))
        recent_acceptes = cur_acceptes.fetchall()

    return render_template(
        "index.html",
        dossiers=dossiers,
        recent_acceptes=recent_acceptes,
        filtre_cnaps=filtre_cnaps,
        statuts_disponibles=statuts_disponibles,
        public_form_url=PUBLIC_FORM_URL,
        a_traiter_count=a_traiter_count,
        formation_sessions=FORMATION_SESSIONS,
    )



@app.route("/add", methods=["POST"])
@login_required
def add():
    nom = request.form["nom"]
    prenom = request.form["prenom"]
    formation = request.form["formation"]
    session = request.form["session"]
    lien = request.form["lien"]
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("INSERT INTO dossiers (nom, prenom, formation, session, lien, statut) VALUES (?, ?, ?, ?, ?, ?)",
                    (nom, prenom, formation, session, lien, "INCOMPLET"))
    return redirect("/")

@app.route("/edit/<int:id>", methods=["POST"])
@login_required
def edit(id):


    # --- Mode auto-save : fetch JSON ---
    if request.is_json:
        data = request.get_json(silent=True) or {}
        lien = data.get("lien", "")
        with sqlite3.connect(DB_NAME) as conn:
            conn.execute("UPDATE dossiers SET lien = ? WHERE id = ?", (lien, id))
        return ("", 204)  # aucune redirection

    # --- Mode ancien formulaire (fallback sécurité) ---
    lien = request.form.get("lien", "")
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("UPDATE dossiers SET lien = ? WHERE id = ?", (lien, id))
    return redirect("/")


@app.route("/delete/<int:id>", methods=["POST"])
@login_required
def delete(id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("DELETE FROM dossiers WHERE id = ?", (id,))
    return redirect("/")

@app.route("/commentaire/<int:id>", methods=["POST"])
@login_required
def update_commentaire(id):

    # --- Mode auto-save (fetch JSON) ---
    if request.is_json:
        data = request.get_json(silent=True) or {}
        commentaire = data.get("commentaire", "")

        with sqlite3.connect(DB_NAME) as conn:
            conn.execute("UPDATE dossiers SET commentaire = ? WHERE id = ?", (commentaire, id))

        return ("", 204)

    # --- Mode formulaire classique ---
    commentaire = request.form.get("commentaire", "")

    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("UPDATE dossiers SET commentaire = ? WHERE id = ?", (commentaire, id))

    return redirect("/")


@app.route("/a-traiter/<int:request_id>/telephone", methods=["POST"])
@login_required
def update_request_telephone(request_id):
    if request.is_json:
        data = request.get_json(silent=True) or {}
        telephone = (data.get("telephone") or "").strip()
    else:
        telephone = (request.form.get("telephone") or "").strip()

    if telephone and not _normalize_phone_number(telephone):
        return jsonify({"ok": False, "error": "Numéro de téléphone invalide"}), 400

    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        req = conn.execute(
            "SELECT id, dossier_id FROM public_requests WHERE id = ?",
            (request_id,),
        ).fetchone()
        if not req:
            return jsonify({"ok": False, "error": "Demande introuvable"}), 404

        conn.execute(
            """
            UPDATE public_requests
            SET telephone = ?, updated_at = datetime('now','localtime')
            WHERE id = ?
            """,
            (telephone, request_id),
        )

        if req["dossier_id"] and _table_has_column(conn, "dossiers", "telephone"):
            conn.execute(
                "UPDATE dossiers SET telephone = ? WHERE id = ?",
                (telephone, req["dossier_id"]),
            )

    return jsonify({"ok": True})


@app.route("/statut/<int:id>/<string:new_status>", methods=["POST"])
@login_required
def update_statut(id, new_status):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("UPDATE dossiers SET statut = ? WHERE id = ?", (new_status, id))
    return ("", 204)

@app.route("/statut_cnaps/<int:id>", methods=["POST"])
@login_required
def update_statut_cnaps(id):

    # --- Mode auto-save (JS fetch en JSON) ---
    if request.is_json:
        data = request.get_json(silent=True) or {}
        nouveau_statut = data.get("statut_cnaps", "")
        with sqlite3.connect(DB_NAME) as conn:
            conn.row_factory = sqlite3.Row
            dossier = conn.execute(
                """
                SELECT d.*, pr.email AS request_email, pr.date_naissance
                FROM dossiers d
                LEFT JOIN public_requests pr ON pr.dossier_id = d.id
                WHERE d.id = ?
                ORDER BY pr.id DESC
                LIMIT 1
                """,
                (id,),
            ).fetchone()
            old_statut = dossier["statut_cnaps"] if dossier else ""
            conn.execute("UPDATE dossiers SET statut_cnaps = ? WHERE id = ?", (nouveau_statut, id))
            _record_statut_cnaps_history(conn, id, nouveau_statut)

        if dossier and old_statut != "TRANSMIS" and nouveau_statut == "TRANSMIS":
            email = (dossier["request_email"] or "").strip().lower()
            if email:
                formation_name = _formation_full_name(dossier["formation"])
                html = render_template(
                    "emails/statut_transmis.html",
                    prenom=dossier["prenom"],
                    formation_name=formation_name,
                    login=email,
                    password=_dracar_password(dossier["nom"], dossier["date_naissance"]),
                    dracar_app_url=DRACAR_APP_URL,
                )
                _send_email_html(email, "Votre dossier CNAPS a été transmis", html)
        return ("", 204)   # aucun rechargement de page

    # --- Mode ancien formulaire (fallback) ---
    nouveau_statut = request.form.get("statut_cnaps", "")
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        dossier = conn.execute(
            """
            SELECT d.*, pr.email AS request_email, pr.date_naissance
            FROM dossiers d
            LEFT JOIN public_requests pr ON pr.dossier_id = d.id
            WHERE d.id = ?
            ORDER BY pr.id DESC
            LIMIT 1
            """,
            (id,),
        ).fetchone()
        old_statut = dossier["statut_cnaps"] if dossier else ""
        conn.execute("UPDATE dossiers SET statut_cnaps = ? WHERE id = ?", (nouveau_statut, id))
        _record_statut_cnaps_history(conn, id, nouveau_statut)

    if dossier and old_statut != "TRANSMIS" and nouveau_statut == "TRANSMIS":
        email = (dossier["request_email"] or "").strip().lower()
        if email:
            formation_name = _formation_full_name(dossier["formation"])
            html = render_template(
                "emails/statut_transmis.html",
                prenom=dossier["prenom"],
                formation_name=formation_name,
                login=email,
                password=_dracar_password(dossier["nom"], dossier["date_naissance"]),
                dracar_app_url=DRACAR_APP_URL,
            )
            _send_email_html(email, "Votre dossier CNAPS a été transmis", html)
    return redirect("/")


@app.route('/attestation/<int:id>')
@login_required
def attestation_pdf(id):
    stagiaire = get_stagiaire_by_id(id)
    if not stagiaire:
        return "Stagiaire introuvable", 404
    formation = _formation_code(stagiaire["formation"])
    if not formation:
        return "Type de formation non pris en charge", 400
    template_name = f"attestation_{formation.lower()}.html"
    html = render_template(template_name, stagiaire=stagiaire)
    pdf = HTML(string=html, base_url=os.getcwd()).write_pdf()  # ✅ Signature fonctionnelle
    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=attestation_{formation}_{stagiaire["nom"]}.pdf'
    return response

@app.route("/export")
@login_required
def export_csv():
    si = StringIO()
    writer = csv.writer(si)
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.execute("SELECT id, nom, prenom, formation, session, lien, statut, commentaire, statut_cnaps FROM dossiers")
        writer.writerow([col[0] for col in cur.description])
        writer.writerows(cur.fetchall())
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=export_cnaps.csv"
    output.headers["Content-type"] = "text/csv"
    return output

@app.route("/import", methods=["GET", "POST"])
@login_required
def import_csv():
    if request.method == "POST":
        file = request.files["file"]
        if file:
            stream = StringIO(file.stream.read().decode("utf-8"))
            reader = csv.DictReader(stream)
            with sqlite3.connect(DB_NAME) as conn:
                conn.execute("DELETE FROM dossiers")  # On remplace tout
                for row in reader:
                    conn.execute("""
                        INSERT INTO dossiers (id, nom, prenom, formation, session, lien, statut, commentaire, statut_cnaps)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        row.get("id"),
                        row.get("nom"),
                        row.get("prenom"),
                        row.get("formation"),
                        row.get("session"),
                        row.get("lien"),
                        row.get("statut"),
                        row.get("commentaire"),
                        row.get("statut_cnaps"),
                    ))
        return redirect("/")
    return '''
    <!doctype html>
    <title>Importer CSV</title>
    <h1>Importer un fichier CSV</h1>
    <form action="/import" method=post enctype=multipart/form-data>
    <input type=file name=file>
    <input type=submit value=Importer>
    </form>
    '''

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").lower().strip()
        password = request.form.get("password") or ""

        # Si les variables Render ne sont pas en place, on bloque
        if not ADMIN_EMAIL or not ADMIN_PASSWORD:
            flash("Login non configuré (variables Render manquantes).", "error")
            return render_template("login.html")

        # Vérification
        if email == ADMIN_EMAIL and password == ADMIN_PASSWORD:
            session["user"] = email
            session.permanent = True  # ✅ cookie persistant
            next_url = request.args.get("next") or "/"
            return redirect(next_url)

        flash("Identifiants incorrects.", "error")
        return render_template("login.html")

    return render_template("login.html")



@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# ------------------------------------------------------------
# ✅ Route publique pour le suivi sur la plateforme principale
# ------------------------------------------------------------
@app.route("/data.json")
def data_json():
    """Retourne les compteurs du suivi CNAPS pour la plateforme de gestion."""
    try:
        with sqlite3.connect(DB_NAME) as conn:
            instruction_count = conn.execute(
                "SELECT COUNT(*) FROM dossiers WHERE statut_cnaps = 'INSTRUCTION'"
            ).fetchone()[0]

            demande_a_faire_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM public_requests pr
                LEFT JOIN dossiers d ON d.id = pr.dossier_id
                WHERE LOWER(TRIM(REPLACE(REPLACE(COALESCE(pr.espace_cnaps, 'A créer'), 'é', 'e'), 'É', 'E'))) = 'valide'
                  AND TRIM(COALESCE(d.statut_cnaps, '')) IN ('', '--')
                """
            ).fetchone()[0]

            documents_a_controler_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM request_documents rd
                JOIN public_requests pr ON pr.id = rd.request_id
                WHERE rd.is_active = 1
                  AND rd.is_conforme IS NULL
                """
            ).fetchone()[0]

            dossiers_documents_a_controler_count = conn.execute(
                """
                SELECT COUNT(DISTINCT rd.request_id)
                FROM request_documents rd
                JOIN public_requests pr ON pr.id = rd.request_id
                WHERE rd.is_active = 1
                  AND rd.is_conforme IS NULL
                """
            ).fetchone()[0]

        headers = {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        }
        return {
            "instruction": instruction_count,
            "demande_a_faire": demande_a_faire_count,
            "documents_a_controler": documents_a_controler_count,
            "dossiers_documents_a_controler": dossiers_documents_a_controler_count,
            "has_demande_a_faire": demande_a_faire_count > 0,
            "has_documents_a_controler": documents_a_controler_count > 0,
        }, 200, headers

    except Exception as e:
        print("⚠️ Erreur data.json:", e)
        return {
            "instruction": -1,
            "demande_a_faire": -1,
            "documents_a_controler": -1,
            "dossiers_documents_a_controler": -1,
            "has_demande_a_faire": False,
            "has_documents_a_controler": False,
            "error": str(e),
        }, 500, {
            "Access-Control-Allow-Origin": "*"
        }

@app.route('/notifications_espace_cnaps_a_valider.json')
def notifications_espace_cnaps_a_valider_json():
    """Retourne les comptes CNAPS créés qui doivent être validés côté gestionstagiaires."""
    headers = {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"}

    try:
        with sqlite3.connect(DB_NAME) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT
                    pr.id,
                    pr.nom,
                    pr.prenom,
                    pr.email,
                    pr.date_naissance,
                    pr.telephone,
                    pr.espace_cnaps,
                    pr.updated_at
                FROM public_requests pr
                LEFT JOIN dossiers d ON d.id = pr.dossier_id
                WHERE LOWER(TRIM(REPLACE(REPLACE(COALESCE(pr.espace_cnaps, 'A créer'), 'é', 'e'), 'É', 'E'))) = 'cree'
                  AND LOWER(TRIM(REPLACE(REPLACE(COALESCE(d.statut_cnaps, ''), 'é', 'e'), 'É', 'E'))) != 'valide'
                ORDER BY pr.id DESC
                """
            ).fetchall()

        notifications = [
            {
                "request_id": row["id"],
                "nom": row["nom"],
                "prenom": row["prenom"],
                "telephone": row["telephone"],
                "login": (row["email"] or "").strip().lower(),
                "password": _dracar_password(row["nom"], row["date_naissance"]),
                "espace_dracar_url": DRACAR_AUTH_URL,
                "espace_cnaps": row["espace_cnaps"],
                "updated_at": row["updated_at"],
                "title": "Notification Compte CNAPS à valider",
                "message": (
                    "Le compte CNAPS de cette personne a été créé. "
                    "Il faut l'appeler pour lui dire de valider son compte et lui communiquer : "
                    f"Login : {(row['email'] or '').strip().lower()} | "
                    f"Mot de passe : {_dracar_password(row['nom'], row['date_naissance'])} | "
                    f"Téléphone : {row['telephone'] or 'Non renseigné'} | "
                    f"Lien vers Espace DRACAR : {DRACAR_AUTH_URL}"
                ),
            }
            for row in rows
        ]

        return {"ok": True, "count": len(notifications), "notifications": notifications}, 200, headers
    except Exception as e:
        return {"ok": False, "count": 0, "notifications": [], "error": str(e)}, 500, headers


# --- à mettre en bas de l'app cnapsv3 (après les autres routes) ---
from datetime import datetime, timedelta

@app.route("/recent_acceptes.json")
def recent_acceptes_json():
    """Retourne les 10 derniers dossiers ACCEPTÉS avec date approximative de validation."""
    try:
        with sqlite3.connect(DB_NAME) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT nom, prenom, session,
                       datetime('now', '-'||(ABS(RANDOM()) % 7)||' day') AS date_acceptation
                FROM dossiers
                WHERE LOWER(REPLACE(REPLACE(statut_cnaps, 'É', 'E'), 'é', 'e')) LIKE '%accepte%'
                ORDER BY id DESC
                LIMIT 5
            """).fetchall()

        data = [dict(r) for r in rows]
        headers = {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"}
        return {"recent_acceptes": data}, 200, headers

    except Exception as e:
        print("⚠️ Erreur /recent_acceptes.json :", e)
        return {"recent_acceptes": [], "error": str(e)}, 500, {"Access-Control-Allow-Origin": "*"}

def _normalize(txt: str) -> str:
    if txt is None:
        return ""
    normalized = "".join(
        c for c in unicodedata.normalize("NFD", txt)
        if unicodedata.category(c) != "Mn"
    ).lower()
    return "".join(c for c in normalized if c.isalnum())


@app.route("/lookup_cnaps.json")
def lookup_cnaps():
    nom = (request.args.get("nom") or "").strip()
    prenom = (request.args.get("prenom") or "").strip()

    if not nom or not prenom:
        return {"ok": False, "error": "missing nom or prenom"}, 400, {"Access-Control-Allow-Origin": "*"}

    try:
        with sqlite3.connect(DB_NAME) as conn:
            conn.row_factory = sqlite3.Row
            conn.create_function("norm", 1, _normalize)
            row = conn.execute(f"""
                SELECT id, nom, prenom, statut_cnaps
                FROM dossiers
                WHERE norm(nom) = norm(?)
                  AND norm(prenom) = norm(?)
                ORDER BY id DESC
                LIMIT 1
            """, (nom, prenom)).fetchone()

            if not row:
                row = conn.execute(f"""
                    SELECT id, nom, prenom, statut_cnaps
                    FROM dossiers
                    WHERE norm(nom) = norm(?)
                      AND norm(prenom) = norm(?)
                    ORDER BY id DESC
                    LIMIT 1
                """, (prenom, nom)).fetchone()

            if not row:
                return {"ok": True, "nom": nom, "prenom": prenom, "statut_cnaps": "INCONNU"}, 200, {"Access-Control-Allow-Origin": "*"}

            statuts_dates = _get_statuts_dates(conn, row["id"])

            return {
                "ok": True,
                "id": row["id"],
                "nom": row["nom"],
                "prenom": row["prenom"],
                "statut_cnaps": row["statut_cnaps"] or "INCONNU",
                "statuts_cnaps_dates": statuts_dates
            }, 200, {"Access-Control-Allow-Origin": "*"}

    except Exception as e:
        return {"ok": False, "error": str(e)}, 500, {"Access-Control-Allow-Origin": "*"}

DOC_LABELS = {
    "identity": "Pièce d'identité (recto/verso) ou passeport",
    "proof_address": "Justificatif de domicile de moins de 3 mois",
    "host_identity": "Pièce d'identité de l'hébergeant",
    "hosting_certificate": "Attestation d'hébergement signée",
    "criminal_record": "Casier judiciaire traduit",
    "french_diploma_tcf": "Diplôme français supérieur au brevet ou TCF",
}

CHECKLIST_LABELS = [
    "J'ai bien fourni ma carte d'identité RECTO et VERSO (face avant, face arrière) ou mon passeport.",
    "Les documents que j'ai fourni sont bien LISIBLES et ne sont pas flous.",
    "Mon justificatif de domicile a bien MOINS DE 3 MOIS.",
    "Mon justificatif de domicile N'EST PAS UNE FACTURE DE TÉLÉPHONE.",
    "Si je suis hébergé, j'ai bien fourni la pièce d'identité de mon hébergeant RECTO et VERSO (face avant, face arrière).",
    "Si je suis hébergé, j'ai vérifié que l'attestation d'hébergement est bien signée.",
]


def _send_email_html(to_email: str, subject: str, html: str):
    text_content = "Votre client mail ne supporte pas le HTML."

    if SMTP_HOST and SMTP_USER and SMTP_PASSWORD:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = SMTP_FROM
        msg["To"] = to_email
        msg.set_content(text_content)
        msg.add_alternative(html, subtype="html")

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        return

    if BREVO_API_KEY and BREVO_SENDER_EMAIL:
        payload = json.dumps(
            {
                "sender": {"name": BREVO_SENDER_NAME, "email": BREVO_SENDER_EMAIL},
                "to": [{"email": to_email}],
                "subject": subject,
                "htmlContent": html,
                "textContent": text_content,
            }
        ).encode("utf-8")
        req = urllib_request.Request(
            "https://api.brevo.com/v3/smtp/email",
            data=payload,
            headers={
                "accept": "application/json",
                "api-key": BREVO_API_KEY,
                "content-type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib_request.urlopen(req, timeout=10):
                pass
        except HTTPError as exc:
            error_body = ""
            if exc.fp is not None:
                error_body = exc.fp.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Brevo email rejected request with status={exc.code}: {error_body}"
            ) from exc
        except URLError as exc:
            raise RuntimeError(f"Brevo email request failed: {exc.reason}") from exc
        return

    print(f"[EMAIL MOCK] to={to_email} subject={subject}")
    print(html)


def _send_sms(to_phone: str, message: str):
    if not to_phone:
        raise RuntimeError("Numéro de téléphone manquant pour l'envoi SMS")

    normalized_phone = _normalize_phone_number(to_phone)
    if not normalized_phone:
        raise RuntimeError(f"Numéro de téléphone invalide: {to_phone!r}")

    if not SMS_WEBHOOK_URL:
        if BREVO_API_KEY and BREVO_SMS_SENDER:
            payload = json.dumps(
                {
                    "sender": BREVO_SMS_SENDER,
                    "recipient": normalized_phone,
                    "content": message,
                    "type": "transactional",
                }
            ).encode("utf-8")
            req = urllib_request.Request(
                "https://api.brevo.com/v3/transactionalSMS/sms",
                data=payload,
                headers={
                    "accept": "application/json",
                    "api-key": BREVO_API_KEY,
                    "content-type": "application/json",
                },
                method="POST",
            )
            try:
                with urllib_request.urlopen(req, timeout=10) as resp:
                    response_body = resp.read().decode("utf-8", errors="replace")
                app.logger.info(
                    "SMS Brevo accepté phone=%s sender=%r response=%s",
                    normalized_phone,
                    BREVO_SMS_SENDER,
                    response_body,
                )
            except HTTPError as exc:
                error_body = ""
                if exc.fp is not None:
                    error_body = exc.fp.read().decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"Brevo SMS rejected request status={exc.code} phone={normalized_phone} sender={BREVO_SMS_SENDER!r} response={error_body}"
                ) from exc
            except URLError as exc:
                raise RuntimeError(
                    f"Brevo SMS request failed phone={normalized_phone} sender={BREVO_SMS_SENDER!r} reason={exc.reason}"
                ) from exc
            return

        if ALLOW_SMS_MOCK:
            print(f"[SMS MOCK] to={normalized_phone}")
            print(message)
            return

        raise RuntimeError(
            "Configuration SMS incomplète: renseigner SMS_WEBHOOK_URL "
            "ou le couple BREVO_API_KEY + BREVO_SMS_SENDER"
        )

    payload = json.dumps({"to": normalized_phone, "message": message}).encode("utf-8")
    req = urllib_request.Request(
        SMS_WEBHOOK_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=10) as resp:
            response_body = resp.read().decode("utf-8", errors="replace")
        app.logger.info(
            "SMS webhook accepté phone=%s url=%r response=%s",
            normalized_phone,
            SMS_WEBHOOK_URL,
            response_body,
        )
    except HTTPError as exc:
        error_body = ""
        if exc.fp is not None:
            error_body = exc.fp.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"SMS webhook rejected request status={exc.code} phone={normalized_phone} url={SMS_WEBHOOK_URL!r} response={error_body}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(
            f"SMS webhook request failed phone={normalized_phone} url={SMS_WEBHOOK_URL!r} reason={exc.reason}"
        ) from exc


def _build_espace_cnaps_created_sms(prenom: str, formation_name: str, validation_url: str):
    safe_prenom = (prenom or "").strip() or ""
    safe_formation = (formation_name or "").strip() or "votre formation"
    return (
        "⚠️ Formation sécurité — Intégrale Academy\n"
        "INFO IMPORTANTE\n\n"
        f"Bonjour {safe_prenom},\n\n"
        f"Concernant la formation {safe_formation} :\n"
        "1) Vous avez dû recevoir un e-mail du CNAPS (Ministère de l'Intérieur).\n"
        "2) Ouvrez cet e-mail et cliquez sur le lien pour valider votre adresse e-mail.\n"
        "3) Cette validation finalise la création de votre compte CNAPS.\n\n"
        "⏳ Attention : le lien expire dans moins de 12 heures.\n"
        "Passé ce délai, nous devrons recommencer toute la procédure.\n\n"
        "Merci,\n"
        "Intégrale Academy"
    )

def _normalize_phone_number(phone: str):
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if not digits:
        return ""

    if digits.startswith("00"):
        return f"+{digits[2:]}"

    if digits.startswith("33"):
        return f"+{digits}"

    if digits.startswith("0") and len(digits) == 10:
        return f"+33{digits[1:]}"

    if phone.startswith("+") and len(digits) >= 9:
        return f"+{digits}"

    if len(digits) >= 9:
        return f"+{digits}"

    return ""


def _formation_full_name(formation: str):
    return {
        "APS": "Agent de sécurité privée",
        "A3P": "Agent de protection physique des personnes",
    }.get(formation or "", formation or "votre formation")


def _formation_code(formation: str):
    normalized = (formation or "").strip().upper()
    if normalized in {"APS", "A3P"}:
        return normalized

    if "A3P" in normalized:
        return "A3P"
    if "APS" in normalized:
        return "APS"

    return ""


def _dracar_password(lastname: str, birth_date: str):
    nom = (lastname or "").strip()
    if nom:
        nom = nom[:1].upper() + nom[1:].lower()
    digits = "".join(ch for ch in (birth_date or "") if ch.isdigit())
    return f"{nom}{digits}@"


def _required_doc_types(heberge: int, non_francais: int):
    required = ["identity", "proof_address"]
    if heberge:
        required.extend(["host_identity", "hosting_certificate"])
    if non_francais:
        required.extend(["criminal_record", "french_diploma_tcf"])
    return required


def _send_cnaps_reminders(conn, requests_rows):
    for req in requests_rows:
        if (req.get("espace_cnaps") or "") != "Créé":
            continue

        timing = _compute_cnaps_timing(req)
        remaining = timing["cnaps_remaining"]
        if remaining is None or timing["cnaps_is_expired"]:
            continue

        remaining_seconds = remaining.total_seconds()
        first_due = remaining_seconds <= 4 * 3600 and not req.get("cnaps_reminder_4h_sent_at")
        second_due = remaining_seconds <= 2 * 3600 and not req.get("cnaps_reminder_2h_sent_at")
        if not first_due and not second_due:
            continue

        formation_name = _formation_full_name(req.get("formation"))
        expiration_label = timing["cnaps_expiration_label"]
        recipient_email = (req.get("email") or "").strip()
        now_db = _to_db_datetime(_now_france())

        if first_due:
            if recipient_email:
                html = render_template(
                    "emails/espace_cnaps_rappel_4h.html",
                    formation_name=formation_name,
                    logo_url=url_for("static", filename="logo.png", _external=True),
                    dracar_url=url_for("static", filename="dracar.png", _external=True),
                )
                _send_email_html(recipient_email, "⚠️ Validation CNAPS à faire avant expiration", html)
            _send_sms(
                req.get("telephone"),
                f"Rappel CNAPS: votre lien expire le {expiration_label}. Merci de valider votre espace CNAPS.",
            )
            conn.execute(
                "UPDATE public_requests SET cnaps_reminder_4h_sent_at = ? WHERE id = ?",
                (now_db, req["id"]),
            )

        if second_due:
            if recipient_email:
                html = render_template(
                    "emails/espace_cnaps_rappel_2h.html",
                    formation_name=formation_name,
                    logo_url=url_for("static", filename="logo.png", _external=True),
                    dracar_url=url_for("static", filename="dracar.png", _external=True),
                )
                _send_email_html(recipient_email, "🚨 URGENT – Validation CNAPS avant expiration", html)
            _send_sms(
                req.get("telephone"),
                f"ATTENTION CNAPS: votre lien expire le {expiration_label}. Il reste moins de 2h.",
            )
            conn.execute(
                "UPDATE public_requests SET cnaps_reminder_2h_sent_at = ? WHERE id = ?",
                (now_db, req["id"]),
            )


def _send_cnaps_manual_reminder(conn, req, reminder_kind: str):
    if reminder_kind not in {"4h", "2h"}:
        raise ValueError("Type de rappel invalide")

    timing = _compute_cnaps_timing(req)
    expiration_label = timing["cnaps_expiration_label"] or _cnaps_expiration_label(_now_france() + timedelta(hours=12))
    formation_name = _formation_full_name(req.get("formation"))
    recipient_email = (req.get("email") or "").strip()
    now_db = _to_db_datetime(_now_france())

    if reminder_kind == "4h":
        if recipient_email:
            html = render_template(
                "emails/espace_cnaps_rappel_4h.html",
                formation_name=formation_name,
                logo_url=url_for("static", filename="logo.png", _external=True),
                dracar_url=url_for("static", filename="dracar.png", _external=True),
            )
            _send_email_html(recipient_email, "⚠️ Validation CNAPS à faire avant expiration", html)

        _send_sms(
            req.get("telephone"),
            f"Rappel CNAPS: votre lien expire le {expiration_label}. Merci de valider votre espace CNAPS.",
        )
        conn.execute(
            "UPDATE public_requests SET cnaps_reminder_4h_sent_at = ? WHERE id = ?",
            (now_db, req["id"]),
        )
    else:
        if recipient_email:
            html = render_template(
                "emails/espace_cnaps_rappel_2h.html",
                formation_name=formation_name,
                logo_url=url_for("static", filename="logo.png", _external=True),
                dracar_url=url_for("static", filename="dracar.png", _external=True),
            )
            _send_email_html(recipient_email, "🚨 URGENT – Validation CNAPS avant expiration", html)

        _send_sms(
            req.get("telephone"),
            f"ATTENTION CNAPS: votre lien expire le {expiration_label}. Il reste moins de 2h.",
        )
        conn.execute(
            "UPDATE public_requests SET cnaps_reminder_2h_sent_at = ? WHERE id = ?",
            (now_db, req["id"]),
        )

    return _cnaps_expiration_label(_parse_db_datetime(now_db))


def _sanitize_zip_component(value: str) -> str:
    """Évite les séparateurs de dossiers dans les noms de fichiers du ZIP."""
    cleaned = (value or "document").replace("/", "-").replace("\\", "-")
    return "_".join(cleaned.split())


def _secure_store(file_storage, subfolder):
    original = file_storage.filename or "document"
    ext = os.path.splitext(original)[1]
    safe_name = f"{uuid.uuid4().hex}{ext}"
    target_dir = os.path.join(UPLOAD_DIR, subfolder)
    os.makedirs(target_dir, exist_ok=True)
    absolute_path = os.path.join(target_dir, safe_name)
    file_storage.save(absolute_path)
    return original, safe_name, os.path.relpath(absolute_path, UPLOAD_DIR)


def _file_size_bytes(file_storage):
    stream = file_storage.stream
    current_pos = stream.tell()
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(current_pos)
    return size


@app.route("/public-form", methods=["GET", "POST"])
def public_form():
    def _render_with_error(message: str):
        flash(message, "public_error")
        return render_template("public_form.html", form_data=request.form)

    if request.method == "GET":
        return render_template("public_form.html")

    nom = (request.form.get("nom") or "").strip()
    prenom = (request.form.get("prenom") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    email_confirm = (request.form.get("email_confirm") or "").strip().lower()
    telephone = (request.form.get("telephone") or "").strip()
    date_naissance = (request.form.get("date_naissance") or "").strip()
    heberge = 1 if request.form.get("heberge") == "on" else 0
    non_francais = 1 if request.form.get("non_francais") == "on" else 0

    if not all([nom, prenom, email, email_confirm, telephone, date_naissance]):
        return _render_with_error("Tous les champs personnels sont obligatoires.")

    if email != email_confirm:
        return _render_with_error("L'email et sa confirmation doivent être identiques.")

    if not _normalize_phone_number(telephone):
        return _render_with_error("Le numéro de téléphone portable est invalide.")

    try:
        datetime.strptime(date_naissance, "%d/%m/%Y")
    except ValueError:
        return _render_with_error("La date de naissance doit être au format DD/MM/YYYY.")

    for item in CHECKLIST_LABELS:
        if request.form.get(item) != "on":
            return _render_with_error("Vous devez cocher toutes les cases de conformité.")

    required = _required_doc_types(heberge, non_francais)
    uploaded = {}
    for doc_type in required:
        files = request.files.getlist(doc_type)
        cleaned = [f for f in files if f and f.filename]
        if not cleaned:
            return _render_with_error(f"Document manquant : {DOC_LABELS[doc_type]}")
        for f in cleaned:
            filename = (f.filename or "").lower()
            if not filename.endswith(".pdf"):
                return _render_with_error(f"Le document {f.filename} doit être au format PDF.")
            if _file_size_bytes(f) > MAX_DOCUMENT_SIZE_BYTES:
                return _render_with_error(f"Le document {f.filename} dépasse 5 Mo. Taille maximale autorisée : 5 Mo.")
        uploaded[doc_type] = cleaned

    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        if _table_has_column(conn, "dossiers", "telephone"):
            cur = conn.execute(
                """
                INSERT INTO dossiers (nom, prenom, formation, session, lien, statut, commentaire, statut_cnaps, telephone)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (nom, prenom, "", "", "", "INCOMPLET", "Dossier reçu via formulaire public", "A TRAITER", telephone),
            )
        else:
            cur = conn.execute(
                """
                INSERT INTO dossiers (nom, prenom, formation, session, lien, statut, commentaire, statut_cnaps)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (nom, prenom, "", "", "", "INCOMPLET", "Dossier reçu via formulaire public", "A TRAITER"),
            )
        dossier_id = cur.lastrowid

        cur = conn.execute(
            """
            INSERT INTO public_requests (dossier_id, nom, prenom, email, date_naissance, heberge, non_francais, telephone, espace_cnaps_validation_token)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (dossier_id, nom, prenom, email, date_naissance, heberge, non_francais, telephone, _new_validation_token()),
        )
        request_id = cur.lastrowid

        for doc_type, files in uploaded.items():
            for f in files:
                original, stored, rel_path = _secure_store(f, str(request_id))
                conn.execute(
                    """
                    INSERT INTO request_documents (request_id, doc_type, original_name, stored_name, storage_path)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (request_id, doc_type, original, stored, rel_path),
                )

    email_html = render_template(
        "emails/confirmation_depot.html",
        prenom=prenom,
        logo_url=url_for("static", filename="logo.png", _external=True),
        dracar_url=url_for("static", filename="dracar.png", _external=True),
    )
    _send_email_html(
        email,
        "Confirmation de dépôt dossier CNAPS",
        email_html,
    )

    return render_template("public_form_success.html", prenom=prenom)


@app.route("/a-traiter")
@login_required
def a_traiter():
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        telephone_expr = _request_phone_select_expr(conn)
        rows = conn.execute(
            f"""
            SELECT
                pr.*,
                d.statut_cnaps,
                d.commentaire,
                {telephone_expr} AS telephone,
                COALESCE(doc_stats.total_docs, 0) AS total_docs,
                COALESCE(doc_stats.conformes, 0) AS conformes,
                COALESCE(doc_stats.non_conformes, 0) AS non_conformes,
                COALESCE(doc_stats.en_attente, 0) AS en_attente
            FROM public_requests pr
            LEFT JOIN dossiers d ON d.id = pr.dossier_id
            LEFT JOIN (
                SELECT
                    request_id,
                    COUNT(*) AS total_docs,
                    SUM(CASE WHEN is_conforme = 1 THEN 1 ELSE 0 END) AS conformes,
                    SUM(CASE WHEN is_conforme = 0 THEN 1 ELSE 0 END) AS non_conformes,
                    SUM(CASE WHEN is_conforme IS NULL THEN 1 ELSE 0 END) AS en_attente
                FROM request_documents
                WHERE is_active = 1
                GROUP BY request_id
            ) doc_stats ON doc_stats.request_id = pr.id
            ORDER BY pr.id DESC
            """
        ).fetchall()

        rows_dict = [dict(row) for row in rows]
        _send_cnaps_reminders(conn, rows_dict)
        for row in rows_dict:
            timing = _compute_cnaps_timing(row)
            row.update(timing)
            if row.get("espace_cnaps") == "Validé":
                row["cnaps_is_expired"] = False

    return render_template(
        "a_traiter.html",
        requests=rows_dict,
        formation_sessions=FORMATION_SESSIONS,
        dracar_auth_url=DRACAR_AUTH_URL,
    )


@app.route("/a-traiter/<int:request_id>/espace-cnaps", methods=["POST"])
@login_required
def update_espace_cnaps(request_id):
    if request.is_json:
        data = request.get_json(silent=True) or {}
        nouvel_etat = (data.get("espace_cnaps") or "").strip()
    else:
        nouvel_etat = (request.form.get("espace_cnaps") or "").strip()

    if nouvel_etat not in {"A créer", "Créé", "Validé"}:
        return jsonify({"ok": False, "error": "Valeur invalide"}), 400

    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        telephone_expr = _request_phone_select_expr(conn)
        req = conn.execute(
            f"""
            SELECT pr.*, {telephone_expr} AS telephone
            FROM public_requests pr
            LEFT JOIN dossiers d ON d.id = pr.dossier_id
            WHERE pr.id = ?
            """,
            (request_id,),
        ).fetchone()
        if not req:
            return jsonify({"ok": False, "error": "Demande introuvable"}), 404

        old_status = req["espace_cnaps"] or "A créer"
        app.logger.warning(
            "Transition espace CNAPS request_id=%s old=%r new=%r",
            request_id,
            old_status,
            nouvel_etat,
        )
        token = (req["espace_cnaps_validation_token"] or "").strip() if "espace_cnaps_validation_token" in req.keys() else ""
        if not token:
            token = _new_validation_token()
            conn.execute(
                "UPDATE public_requests SET espace_cnaps_validation_token = ? WHERE id = ?",
                (token, request_id),
            )

        update_fields = ["espace_cnaps = ?", "updated_at = datetime('now','localtime')"]
        params = [nouvel_etat]

        if old_status != "Créé" and nouvel_etat == "Créé":
            update_fields.append("espace_cnaps_created_at = ?")
            update_fields.append("cnaps_reminder_4h_sent_at = NULL")
            update_fields.append("cnaps_reminder_2h_sent_at = NULL")
            update_fields.append("espace_cnaps_created_sms_sent_at = NULL")
            params.append(_to_db_datetime(_now_france()))
        elif nouvel_etat == "A créer":
            update_fields.append("espace_cnaps_created_at = NULL")
            update_fields.append("cnaps_reminder_4h_sent_at = NULL")
            update_fields.append("cnaps_reminder_2h_sent_at = NULL")
            update_fields.append("espace_cnaps_created_sms_sent_at = NULL")

        params.append(request_id)
        conn.execute(
            f"UPDATE public_requests SET {', '.join(update_fields)} WHERE id = ?",
            tuple(params),
        )

    if old_status != "Créé" and nouvel_etat == "Créé":
        formation_name = _formation_full_name(req["formation"])
        expiration_time = _cnaps_expiration_label(_now_france() + timedelta(hours=12)).split(" à ")[-1]
        html = render_template(
            "emails/espace_cnaps_cree.html",
            prenom=req["prenom"],
            formation_name=formation_name,
            logo_url=url_for("static", filename="logo.png", _external=True),
            dracar2_url=url_for("static", filename="dracar.png", _external=True),
            validation_url=f"{PUBLIC_APP_BASE_URL}{url_for('validate_espace_cnaps', token=token)}",
            expiration_time=expiration_time,
            dracar_auth_url=DRACAR_AUTH_URL,
        )
        recipient_email = (req["email"] or "").strip()
        if recipient_email:
            try:
                _send_email_html(recipient_email, "⚠️ Formation sécurité Validation de votre compte CNAPS", html)
            except Exception:
                app.logger.exception(
                    "Échec envoi email espace CNAPS request_id=%s email=%r",
                    request_id,
                    recipient_email,
                )
        else:
            app.logger.warning(
                "Email manquant pour l'envoi espace CNAPS request_id=%s",
                request_id,
            )

        can_send_sms = False
        with sqlite3.connect(DB_NAME) as conn_sms:
            claimed = conn_sms.execute(
                """
                UPDATE public_requests
                SET espace_cnaps_created_sms_sent_at = ?
                WHERE id = ?
                  AND (espace_cnaps_created_sms_sent_at IS NULL OR TRIM(espace_cnaps_created_sms_sent_at) = '')
                """,
                (_to_db_datetime(_now_france()), request_id),
            )
            can_send_sms = claimed.rowcount > 0

        if can_send_sms:
            validation_url = f"{PUBLIC_APP_BASE_URL}{url_for('validate_espace_cnaps', token=token)}"
            sms = _build_espace_cnaps_created_sms(req["prenom"], formation_name, validation_url)
            try:
                _send_sms(req["telephone"], sms)
            except Exception as exc:
                with sqlite3.connect(DB_NAME) as conn_sms:
                    conn_sms.execute(
                        "UPDATE public_requests SET espace_cnaps_created_sms_sent_at = NULL WHERE id = ?",
                        (request_id,),
                    )
                app.logger.exception(
                    "Échec envoi SMS espace CNAPS request_id=%s telephone=%r error=%s",
                    request_id,
                    req["telephone"],
                    exc,
                )
        else:
            app.logger.warning(
                "SMS deja envoye pour request_id=%s, envoi ignore pour eviter doublon",
                request_id,
            )
    else:
        app.logger.warning(
            "SMS non declenche pour request_id=%s (condition old!=Créé && new==Créé non satisfaite) old=%r new=%r",
            request_id,
            old_status,
            nouvel_etat,
        )

    return ("", 204)


@app.route("/a-traiter/<int:request_id>/cnaps-reminder", methods=["POST"])
@login_required
def send_cnaps_manual_reminder(request_id):
    data = request.get_json(silent=True) or {}
    reminder_kind = (data.get("reminder_kind") or "").strip()
    if reminder_kind not in {"4h", "2h"}:
        return jsonify({"ok": False, "error": "Type de rappel invalide"}), 400

    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        telephone_expr = _request_phone_select_expr(conn)
        req = conn.execute(
            f"""
            SELECT pr.*, {telephone_expr} AS telephone
            FROM public_requests pr
            LEFT JOIN dossiers d ON d.id = pr.dossier_id
            WHERE pr.id = ?
            """,
            (request_id,),
        ).fetchone()

        if not req:
            return jsonify({"ok": False, "error": "Demande introuvable"}), 404

        if (req["espace_cnaps"] or "") != "Créé":
            return jsonify({"ok": False, "error": "Le rappel est disponible uniquement pour les espaces CNAPS créés"}), 400

        try:
            sent_label = _send_cnaps_manual_reminder(conn, dict(req), reminder_kind)
        except Exception as exc:
            app.logger.exception(
                "Echec envoi rappel manuel CNAPS request_id=%s reminder=%s error=%s",
                request_id,
                reminder_kind,
                exc,
            )
            return jsonify({"ok": False, "error": "Échec de l'envoi du rappel"}), 500

    return jsonify({"ok": True, "sent_label": sent_label})


@app.route("/espace-cnaps/validation/<token>", methods=["GET"])
def validate_espace_cnaps(token):
    clean_token = (token or "").strip()
    if not clean_token:
        abort(404)

    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        req = conn.execute(
            "SELECT id, prenom, espace_cnaps FROM public_requests WHERE espace_cnaps_validation_token = ?",
            (clean_token,),
        ).fetchone()
        if not req:
            abort(404)

        already_validated = (req["espace_cnaps"] or "") == "Validé"
        if not already_validated:
            conn.execute(
                "UPDATE public_requests SET espace_cnaps = 'Validé', updated_at = datetime('now','localtime') WHERE id = ?",
                (req["id"],),
            )

    return render_template(
        "public_espace_cnaps_valide.html",
        prenom=req["prenom"],
        already_validated=already_validated,
    )


@app.route("/a-traiter/<int:request_id>/assign", methods=["POST"])
@login_required
def assign_formation(request_id):
    formation = (request.form.get("formation") or "").strip()
    session_date = (request.form.get("session_date") or "").strip()
    if formation not in FORMATION_SESSIONS or session_date not in FORMATION_SESSIONS.get(formation, []):
        return jsonify({"ok": False, "error": "Paramètres invalides"}), 400

    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        req = conn.execute("SELECT dossier_id FROM public_requests WHERE id = ?", (request_id,)).fetchone()
        if not req:
            return jsonify({"ok": False, "error": "Demande introuvable"}), 404

        conn.execute(
            "UPDATE public_requests SET formation = ?, session_date = ?, updated_at = datetime('now','localtime') WHERE id = ?",
            (formation, session_date, request_id),
        )
        if req["dossier_id"]:
            conn.execute(
                "UPDATE dossiers SET formation = ?, session = ? WHERE id = ?",
                (formation, session_date, req["dossier_id"]),
            )

    if request.is_json:
        return jsonify({"ok": True})
    return redirect(url_for("a_traiter"))


@app.route("/a-traiter/<int:request_id>/delete", methods=["POST"])
@login_required
def delete_a_traiter_line(request_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row

        req = conn.execute(
            "SELECT dossier_id FROM public_requests WHERE id = ?",
            (request_id,),
        ).fetchone()

        if req is None:
            return redirect(url_for("a_traiter"))

        conn.execute("DELETE FROM request_documents WHERE request_id = ?", (request_id,))
        conn.execute(
            "DELETE FROM request_non_conformity_notifications WHERE request_id = ?",
            (request_id,),
        )
        conn.execute("DELETE FROM public_requests WHERE id = ?", (request_id,))

        if req["dossier_id"]:
            conn.execute("DELETE FROM statut_cnaps_history WHERE dossier_id = ?", (req["dossier_id"],))
            conn.execute("DELETE FROM dossiers WHERE id = ?", (req["dossier_id"],))

    return redirect(url_for("a_traiter"))


@app.route("/a-traiter/<int:request_id>/documents")
@login_required
def request_documents(request_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        req = conn.execute("SELECT * FROM public_requests WHERE id = ?", (request_id,)).fetchone()
        if not req:
            abort(404)

        docs = conn.execute(
            """
            SELECT * FROM request_documents
            WHERE request_id = ? AND is_active = 1
            ORDER BY doc_type, id DESC
            """,
            (request_id,),
        ).fetchall()

    grouped = {}
    for d in docs:
        grouped.setdefault(d["doc_type"], []).append(d)

    return render_template("documents_review.html", req=req, grouped=grouped, doc_labels=DOC_LABELS)


@app.route("/uploads/<int:request_id>/<path:filename>")
@login_required
def serve_upload(request_id, filename):
    folder = os.path.join(UPLOAD_DIR, str(request_id))
    return send_from_directory(folder, filename, as_attachment=False)


@app.route("/a-traiter/<int:request_id>/documents/review", methods=["POST"])
@login_required
def review_documents(request_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        docs = conn.execute("SELECT id FROM request_documents WHERE request_id = ? AND is_active = 1", (request_id,)).fetchall()
        for d in docs:
            doc_id = d["id"]
            status = request.form.get(f"status_{doc_id}")
            reason = (request.form.get(f"reason_{doc_id}") or "").strip()
            is_conforme = None
            review_status = "pending"
            reviewed_at = None
            if status == "conforme":
                is_conforme = 1
                review_status = "conforme"
                reason = ""
                reviewed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            elif status == "non_conforme":
                is_conforme = 0
                review_status = "non_conforme"
                reviewed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            elif status == "notified_expected":
                is_conforme = 0
                review_status = "notified_expected"
                reviewed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            else:
                reason = ""
            conn.execute(
                "UPDATE request_documents SET is_conforme = ?, review_status = ?, non_conformite_reason = ?, reviewed_at = ? WHERE id = ?",
                (is_conforme, review_status, reason, reviewed_at, doc_id),
            )

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return ("", 204)

    return redirect(url_for("request_documents", request_id=request_id))


@app.route("/a-traiter/<int:request_id>/notify", methods=["POST"])
@login_required
def notify_non_conformities(request_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        telephone_expr = _request_phone_select_expr(conn)
        req = conn.execute(
            f"""
            SELECT pr.*, {telephone_expr} AS telephone
            FROM public_requests pr
            LEFT JOIN dossiers d ON d.id = pr.dossier_id
            WHERE pr.id = ?
            """,
            (request_id,),
        ).fetchone()
        docs = conn.execute(
            """
            SELECT * FROM request_documents
            WHERE request_id = ? AND is_active = 1 AND review_status = 'non_conforme'
            ORDER BY doc_type, id DESC
            """,
            (request_id,),
        ).fetchall()

        if not req or not docs:
            return redirect(url_for("request_documents", request_id=request_id))

        replace_url = url_for("replace_documents", request_id=request_id, _external=True)
        formation_name = _formation_full_name(req["formation"])
        html = render_template(
            "emails/non_conformite.html",
            prenom=req["prenom"],
            formation_name=formation_name,
            docs=docs,
            labels=DOC_LABELS,
            replace_url=replace_url,
            logo_url=url_for("static", filename="logo.png", _external=True),
        )

        try:
            _send_email_html(req["email"], "Documents non conformes - dossier CNAPS", html)
        except RuntimeError:
            app.logger.exception("Échec envoi email non-conformités request_id=%s", request_id)
            flash(
                "Impossible d'envoyer l'email de non-conformité. Vérifie la configuration email (Brevo/SMTP) et réessaie.",
                "error",
            )
            return redirect(url_for("request_documents", request_id=request_id))

        try:
            sms = (
                f"Bonjour {req['prenom']}, certains documents de votre dossier CNAPS sont non conformes. "
                f"Merci de les remplacer ici : {replace_url}"
            )
            _send_sms(req["telephone"], sms)
        except Exception:
            app.logger.exception("Échec envoi SMS non-conformités request_id=%s", request_id)

        conn.execute("INSERT INTO request_non_conformity_notifications (request_id) VALUES (?)", (request_id,))
        doc_ids = [doc["id"] for doc in docs]
        conn.executemany(
            "UPDATE request_documents SET review_status = 'notified_expected' WHERE id = ?",
            [(doc_id,) for doc_id in doc_ids],
        )

    return redirect(url_for("request_documents", request_id=request_id))


@app.route("/replace-documents/<int:request_id>", methods=["GET", "POST"])
def replace_documents(request_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        req = conn.execute("SELECT * FROM public_requests WHERE id = ?", (request_id,)).fetchone()
        if not req:
            abort(404)

        invalids = conn.execute(
            """
            SELECT * FROM request_documents
            WHERE request_id = ?
              AND is_active = 1
              AND (review_status = 'notified_expected' OR (is_conforme = 0 AND review_status = 'non_conforme'))
            """,
            (request_id,),
        ).fetchall()

        if request.method == "POST":
            if not invalids:
                return render_template("replace_documents_already_sent.html")

            replaced = 0
            for doc in invalids:
                incoming = request.files.get(f"replace_{doc['id']}")
                if incoming and incoming.filename:
                    if not incoming.filename.lower().endswith(".pdf"):
                        flash(f"Le document {incoming.filename} doit être au format PDF.", "error")
                        return redirect(url_for("replace_documents", request_id=request_id))
                    if _file_size_bytes(incoming) > MAX_DOCUMENT_SIZE_BYTES:
                        flash(f"Le document {incoming.filename} dépasse 5 Mo. Taille maximale autorisée : 5 Mo.", "public_error")
                        return redirect(url_for("replace_documents", request_id=request_id))
                    conn.execute("UPDATE request_documents SET is_active = 0 WHERE id = ?", (doc["id"],))
                    original, stored, rel_path = _secure_store(incoming, str(request_id))
                    conn.execute(
                        """
                        INSERT INTO request_documents (request_id, doc_type, original_name, stored_name, storage_path)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (request_id, doc["doc_type"], original, stored, rel_path),
                    )
                    replaced += 1
            if replaced:
                conn.execute("UPDATE public_requests SET updated_at = datetime('now','localtime') WHERE id = ?", (request_id,))
            return render_template("replace_documents_success.html", replaced=replaced)

    if not invalids:
        return render_template("replace_documents_already_sent.html")

    return render_template("replace_documents.html", req=req, invalids=invalids, labels=DOC_LABELS)


@app.route("/a-traiter/<int:request_id>/download")
@login_required
def download_full_bundle(request_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        req = conn.execute("SELECT * FROM public_requests WHERE id = ?", (request_id,)).fetchone()
        if not req:
            abort(404)

        docs = conn.execute(
            "SELECT * FROM request_documents WHERE request_id = ? AND is_active = 1",
            (request_id,),
        ).fetchall()

        if not docs or any(d["is_conforme"] != 1 for d in docs):
            return "Tous les documents doivent être conformes avant téléchargement.", 400

        oversized_docs = []
        for d in docs:
            source = os.path.join(UPLOAD_DIR, d["storage_path"])
            if os.path.exists(source) and os.path.getsize(source) > MAX_DOCUMENT_SIZE_BYTES:
                oversized_docs.append(d["original_name"])

        if oversized_docs:
            return (
                "Téléchargement impossible : chaque document doit faire 5 Mo maximum. "
                f"Document(s) à remplacer : {', '.join(oversized_docs)}",
                400,
            )

        dossier = conn.execute("SELECT * FROM dossiers WHERE id = ?", (req["dossier_id"],)).fetchone()

    memory_file = BytesIO()
    safe_nom = f"{req['prenom']}_{req['nom']}".replace(" ", "_")

    with zipfile.ZipFile(memory_file, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, doc in enumerate(docs, start=1):
            source = os.path.join(UPLOAD_DIR, doc["storage_path"])
            label = _sanitize_zip_component(DOC_LABELS.get(doc["doc_type"], doc["doc_type"]))
            ext = os.path.splitext(doc["original_name"])[1]
            arcname = _sanitize_zip_component(f"{i:02d}_{label}_{safe_nom}{ext}")
            if os.path.exists(source):
                zf.write(source, arcname)

        formation = _formation_code(dossier["formation"] if dossier else req["formation"])
        if formation:
            html = render_template(f"attestation_{formation.lower()}.html", stagiaire=dossier or req)
            pdf = HTML(string=html, base_url=os.getcwd()).write_pdf()
            zf.writestr(f"attestation_preinscription_{safe_nom}.pdf", pdf)

    memory_file.seek(0)
    return send_file(memory_file, as_attachment=True, download_name=f"dossier_cnaps_{safe_nom}.zip", mimetype="application/zip")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
