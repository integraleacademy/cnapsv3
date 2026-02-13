from flask import Flask, render_template, request, redirect, make_response, send_file, session, flash, url_for
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


DB_NAME = "/mnt/data/cnaps.db"


def init_db():
    """Crée les structures nécessaires pour historiser les statuts CNAPS."""
    os.makedirs(os.path.dirname(DB_NAME), exist_ok=True)
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
        statuts_disponibles=statuts_disponibles
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
            conn.execute("UPDATE dossiers SET statut_cnaps = ? WHERE id = ?", (nouveau_statut, id))
            _record_statut_cnaps_history(conn, id, nouveau_statut)
        return ("", 204)   # aucun rechargement de page

    # --- Mode ancien formulaire (fallback) ---
    nouveau_statut = request.form.get("statut_cnaps", "")
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("UPDATE dossiers SET statut_cnaps = ? WHERE id = ?", (nouveau_statut, id))
        _record_statut_cnaps_history(conn, id, nouveau_statut)
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
