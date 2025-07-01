from flask import Flask, render_template, request, redirect, make_response, Response
from weasyprint import HTML
from werkzeug.utils import secure_filename
import sqlite3
import os
import io
import csv

app = Flask(__name__)
DB_NAME = "cnaps.db"

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
            cur = conn.execute("SELECT * FROM dossiers")
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

@app.route('/attestation/<int:id>')
def attestation_pdf(id):
    stagiaire = get_stagiaire_by_id(id)
    if not stagiaire:
        return "Stagiaire introuvable", 404
    formation = stagiaire["formation"]
    if formation not in ["APS", "A3P"]:
        return "Type de formation non pris en charge", 400
    template_name = f"attestation_{formation.lower()}.html"
    html = render_template(template_name, stagiaire=stagiaire)
    pdf = HTML(string=html, base_url=os.getcwd()).write_pdf()
    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=attestation_{formation}_{stagiaire['nom']}.pdf'
    return response

@app.route("/export")
def export_csv():
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM dossiers")
        rows = cur.fetchall()

    def generate():
        headers = ["ID", "Nom", "Prénom", "Formation", "Session", "Lien", "Statut dossier", "Commentaire", "Statut CNAPS"]
        yield ",".join(headers) + "\n"
        for row in rows:
            ligne = [str(row[col]) if row[col] is not None else "" for col in row.keys()]
            yield ",".join(ligne) + "\n"

    return Response(generate(), mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=dossiers_cnaps.csv"})

@app.route("/import", methods=["GET", "POST"])
def import_csv():
    if request.method == "POST":
        file = request.files.get("file")
        if not file or not file.filename.endswith(".csv"):
            return "Fichier non valide", 400

        stream = io.StringIO(file.stream.read().decode("utf-8"))
        reader = csv.reader(stream)
        headers = next(reader)  # saute les en-têtes

        with sqlite3.connect(DB_NAME) as conn:
            conn.execute("DELETE FROM dossiers")  # supprime tout
            for row in reader:
                if len(row) < 6:
                    continue
                nom, prenom, formation, session, lien, statut = row[1:7]
                commentaire = row[7] if len(row) > 7 else ""
                statut_cnaps = row[8] if len(row) > 8 else ""
                conn.execute(
                    "INSERT INTO dossiers (nom, prenom, formation, session, lien, statut, commentaire, statut_cnaps) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (nom, prenom, formation, session, lien, statut, commentaire, statut_cnaps)
                )
        return redirect("/")
    
    return '''
        <h2>Importer un fichier CSV (Remplace tous les dossiers existants)</h2>
        <form method="POST" enctype="multipart/form-data">
            <input type="file" name="file" accept=".csv" required>
            <button type="submit">Importer</button>
        </form>
        <a href="/">⬅ Retour</a>
    '''
