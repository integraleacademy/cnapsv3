from flask import Flask, render_template, request, redirect, make_response, send_file
from weasyprint import HTML
import sqlite3
import os
import shutil
import csv
from io import StringIO

# Copier l’ancienne base si elle existe encore localement
if os.path.exists("cnaps.db") and not os.path.exists("/mnt/data/cnaps.db"):
    shutil.copy("cnaps.db", "/mnt/data/cnaps.db")

app = Flask(__name__)
DB_NAME = "/mnt/data/cnaps.db"

def get_stagiaire_by_id(id):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    stagiaire = conn.execute("SELECT * FROM dossiers WHERE id = ?", (id,)).fetchone()
    conn.close()
    return stagiaire

@app.route("/")
def index():
    filtre_cnaps = request.args.get('filtre_cnaps', 'Tous')
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cur_statuts = conn.execute("SELECT DISTINCT statut_cnaps FROM dossiers")
        statuts_disponibles = sorted([row['statut_cnaps'] for row in cur_statuts if row['statut_cnaps']])
        if filtre_cnaps != 'Tous':
            cur = conn.execute("SELECT * FROM dossiers WHERE statut_cnaps=?", (filtre_cnaps,))
        else:
            cur = conn.execute("SELECT * FROM dossiers ORDER BY id DESC")  # 🔽 Tri décroissant
        dossiers = cur.fetchall()
    return render_template("index.html", dossiers=dossiers, filtre_cnaps=filtre_cnaps, statuts_disponibles=statuts_disponibles)

@app.route("/add", methods=["POST"])
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
def edit(id):
    lien = request.form.get("lien", "")
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("UPDATE dossiers SET lien = ? WHERE id = ?", (lien, id))
    return redirect("/")

@app.route("/delete/<int:id>")
def delete(id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("DELETE FROM dossiers WHERE id = ?", (id,))
    return redirect("/")

@app.route("/commentaire/<int:id>", methods=["POST"])
def update_commentaire(id):
    commentaire = request.form.get("commentaire", "")
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("UPDATE dossiers SET commentaire = ? WHERE id = ?", (commentaire, id))
    return redirect("/")

@app.route("/statut/<int:id>/<string:new_status>")
def update_statut(id, new_status):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("UPDATE dossiers SET statut = ? WHERE id = ?", (new_status, id))
    return redirect("/")

@app.route("/statut_cnaps/<int:id>", methods=["POST"])
def update_statut_cnaps(id):
    nouveau_statut = request.form.get("statut_cnaps")
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("UPDATE dossiers SET statut_cnaps = ? WHERE id = ?", (nouveau_statut, id))
    return redirect("/")

@app.route("/attestation/<int:id>")
def attestation(id):
    stagiaire = get_stagiaire_by_id(id)
    rendered = render_template("attestation_aps.html", stagiaire=stagiaire)
    pdf = HTML(string=rendered).write_pdf()
    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'inline; filename=attestation_{id}.pdf'
    return response

@app.route("/export")
def export_csv():
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM dossiers").fetchall()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(rows[0].keys())
    for row in rows:
        writer.writerow([row[key] for key in row.keys()])
    output.seek(0)
    return send_file(StringIO(output.getvalue()), mimetype='text/csv', download_name='export.csv', as_attachment=True)

@app.route("/import", methods=["GET", "POST"])
def importer():
    if request.method == "POST":
        file = request.files["fichier_csv"]
        if file:
            content = file.stream.read().decode("utf-8")
            reader = csv.reader(StringIO(content))
            headers = next(reader)
            with sqlite3.connect(DB_NAME) as conn:
                for row in reader:
                    conn.execute("INSERT INTO dossiers (id, nom, prenom, formation, session, lien, statut, commentaire, statut_cnaps) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                 row)
        return redirect("/")
    return render_template("importer.html")
