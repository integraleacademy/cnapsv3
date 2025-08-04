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
            cur = conn.execute("SELECT * FROM dossiers WHERE statut_cnaps=? ORDER BY id DESC", (filtre_cnaps,))
        else:
            cur = conn.execute("SELECT * FROM dossiers ORDER BY id DESC")  # <-- ligne modifiée
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

@app.route("/update-statut/<int:id>", methods=["POST"])
def update_statut(id):
    statut = request.form.get("statut")
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("UPDATE dossiers SET statut = ? WHERE id = ?", (statut, id))
    return redirect("/")

@app.route("/delete/<int:id>", methods=["POST"])
def delete(id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("DELETE FROM dossiers WHERE id = ?", (id,))
    return redirect("/")

@app.route("/export")
def export():
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM dossiers").fetchall()
    si = StringIO()
    cw = csv.writer(si)
    if rows:
        cw.writerow(rows[0].keys())
        cw.writerows([list(row) for row in rows])
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=dossiers.csv"
    output.headers["Content-type"] = "text/csv"
    return output

@app.route("/attestation/<int:id>")
def attestation(id):
    stagiaire = get_stagiaire_by_id(id)
    return render_template("attestation_aps.html", stagiaire=stagiaire)

@app.route("/attestation_a3p/<int:id>")
def attestation_a3p(id):
    stagiaire = get_stagiaire_by_id(id)
    return render_template("attestation_a3p.html", stagiaire=stagiaire)

@app.route("/attestation/pdf/<int:id>")
def generate_pdf(id):
    stagiaire = get_stagiaire_by_id(id)
    rendered_html = render_template("attestation_aps.html", stagiaire=stagiaire)
    pdf_file = HTML(string=rendered_html).write_pdf()
    response = make_response(pdf_file)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'inline; filename=attestation_{id}.pdf'
    return response
