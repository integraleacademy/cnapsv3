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
DRACAR_AUTH_URL = "https://espace-usagers.cnaps.interieur.gouv.fr/auth/realms/personne-physique/protocol/openid-connect/auth?client_id=cnaps&redirect_uri=https%3A%2F%2Fespace-usagers.cnaps.interieur.gouv.fr%2Fusager%2Fapp&state=e5d9b066-1e63-4147-b169-862be8c082e9&response_mode=fragment&response_type=code&scope=openid%20profile&nonce=2fb2bea0-8e33-4c8c-b6b4-fc906e587b66&code_challenge=UVZRu6sC--Y5Ypc6O2WfJfwtXo_pbb8LCoQzvB7ouHo&code_challenge_method=S256"
DRACAR_APP_URL = "https://espace-usagers.cnaps.interieur.gouv.fr/usager/app/accueil"

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
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (dossier_id) REFERENCES dossiers(id) ON DELETE SET NULL
            )
        """)

        columns = {row[1] for row in conn.execute("PRAGMA table_info(public_requests)").fetchall()}
        if "espace_cnaps" not in columns:
            conn.execute("ALTER TABLE public_requests ADD COLUMN espace_cnaps TEXT NOT NULL DEFAULT 'A créer'")

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
    formation = stagiaire["formation"]
    if formation not in ["APS", "A3P"]:
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
    """Retourne le nombre de dossiers en instruction pour le suivi CNAPS"""
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cur = conn.execute("SELECT COUNT(*) FROM dossiers WHERE statut_cnaps = 'INSTRUCTION'")
            count = cur.fetchone()[0]

        headers = {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        }
        return {"instruction": count}, 200, headers

    except Exception as e:
        print("⚠️ Erreur data.json:", e)
        return {"instruction": -1, "error": str(e)}, 500, {
            "Access-Control-Allow-Origin": "*"
        }

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
        return

    if not SMS_WEBHOOK_URL:
        if BREVO_API_KEY and BREVO_SMS_SENDER:
            payload = json.dumps(
                {
                    "sender": BREVO_SMS_SENDER,
                    "recipient": to_phone,
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
            with urllib_request.urlopen(req, timeout=10):
                pass
            return

        print(f"[SMS MOCK] to={to_phone}")
        print(message)
        return

    payload = json.dumps({"to": to_phone, "message": message}).encode("utf-8")
    req = urllib_request.Request(
        SMS_WEBHOOK_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib_request.urlopen(req, timeout=10):
        pass


def _formation_full_name(formation: str):
    return {
        "APS": "Agent de sécurité privée",
        "A3P": "Agent de protection physique des personnes",
    }.get(formation or "", formation or "votre formation")


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
    if request.method == "GET":
        return render_template("public_form.html")

    nom = (request.form.get("nom") or "").strip()
    prenom = (request.form.get("prenom") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    email_confirm = (request.form.get("email_confirm") or "").strip().lower()
    date_naissance = (request.form.get("date_naissance") or "").strip()
    heberge = 1 if request.form.get("heberge") == "on" else 0
    non_francais = 1 if request.form.get("non_francais") == "on" else 0

    if not all([nom, prenom, email, email_confirm, date_naissance]):
        flash("Tous les champs personnels sont obligatoires.", "error")
        return redirect(url_for("public_form"))

    if email != email_confirm:
        flash("L'email et sa confirmation doivent être identiques.", "error")
        return redirect(url_for("public_form"))

    try:
        datetime.strptime(date_naissance, "%d/%m/%Y")
    except ValueError:
        flash("La date de naissance doit être au format DD/MM/YYYY.", "error")
        return redirect(url_for("public_form"))

    for item in CHECKLIST_LABELS:
        if request.form.get(item) != "on":
            flash("Vous devez cocher toutes les cases de conformité.", "error")
            return redirect(url_for("public_form"))

    required = _required_doc_types(heberge, non_francais)
    uploaded = {}
    for doc_type in required:
        files = request.files.getlist(doc_type)
        cleaned = [f for f in files if f and f.filename]
        if not cleaned:
            flash(f"Document manquant : {DOC_LABELS[doc_type]}", "error")
            return redirect(url_for("public_form"))
        for f in cleaned:
            filename = (f.filename or "").lower()
            if not filename.endswith(".pdf"):
                flash(f"Le document {f.filename} doit être au format PDF.", "error")
                return redirect(url_for("public_form"))
            if _file_size_bytes(f) > MAX_DOCUMENT_SIZE_BYTES:
                flash(f"Le document {f.filename} dépasse 5 Mo. Taille maximale autorisée : 5 Mo.", "error")
                return redirect(url_for("public_form"))
        uploaded[doc_type] = cleaned

    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
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
            INSERT INTO public_requests (dossier_id, nom, prenom, email, date_naissance, heberge, non_francais)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (dossier_id, nom, prenom, email, date_naissance, heberge, non_francais),
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

    email_html = render_template("emails/confirmation_depot.html", prenom=prenom)
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
        telephone_expr = "d.telephone" if _table_has_column(conn, "dossiers", "telephone") else "NULL"
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

    return render_template(
        "a_traiter.html",
        requests=rows,
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
        telephone_expr = "d.telephone" if _table_has_column(conn, "dossiers", "telephone") else "NULL"
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
        conn.execute(
            "UPDATE public_requests SET espace_cnaps = ?, updated_at = datetime('now','localtime') WHERE id = ?",
            (nouvel_etat, request_id),
        )

    if old_status != "Créé" and nouvel_etat == "Créé":
        formation_name = _formation_full_name(req["formation"])
        html = render_template(
            "emails/espace_cnaps_cree.html",
            prenom=req["prenom"],
            formation_name=formation_name,
        )
        _send_email_html(req["email"], "Votre Espace Particulier CNAPS est créé", html)

        sms = (
            f"Bonjour {req['prenom']}, votre Espace Particulier CNAPS pour la formation {formation_name} "
            "vient d'être créé. Merci de valider votre compte via le lien reçu du CNAPS. "
            "Le lien expire sous 12h."
        )
        _send_sms(req["telephone"], sms)

    return ("", 204)


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
        telephone_expr = "d.telephone" if _table_has_column(conn, "dossiers", "telephone") else "NULL"
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
        html = render_template("emails/non_conformite.html", prenom=req["prenom"], docs=docs, labels=DOC_LABELS, replace_url=replace_url)

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

        if request.method == "POST":
            invalids = conn.execute(
                """
                SELECT * FROM request_documents
                WHERE request_id = ?
                  AND is_active = 1
                  AND (review_status = 'notified_expected' OR (is_conforme = 0 AND review_status = 'non_conforme'))
                """,
                (request_id,),
            ).fetchall()
            replaced = 0
            for doc in invalids:
                incoming = request.files.get(f"replace_{doc['id']}")
                if incoming and incoming.filename:
                    if _file_size_bytes(incoming) > MAX_DOCUMENT_SIZE_BYTES:
                        flash(f"Le document {incoming.filename} dépasse 5 Mo. Taille maximale autorisée : 5 Mo.", "error")
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

        invalids = conn.execute(
            """
            SELECT * FROM request_documents
            WHERE request_id = ?
              AND is_active = 1
              AND (review_status = 'notified_expected' OR (is_conforme = 0 AND review_status = 'non_conforme'))
            """,
            (request_id,),
        ).fetchall()

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

        if dossier and dossier["formation"] in ["APS", "A3P"]:
            html = render_template(f"attestation_{dossier['formation'].lower()}.html", stagiaire=dossier)
            pdf = HTML(string=html, base_url=os.getcwd()).write_pdf()
            zf.writestr(f"attestation_preinscription_{safe_nom}.pdf", pdf)

    memory_file.seek(0)
    return send_file(memory_file, as_attachment=True, download_name=f"dossier_cnaps_{safe_nom}.zip", mimetype="application/zip")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
