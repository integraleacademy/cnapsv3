from flask import Flask, render_template, request, redirect, make_response
from weasyprint import HTML
import sqlite3
import os

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

        # Récupérer tous les statuts distincts existants
        cur_statuts = conn.execute("SELECT DISTINCT statut_cnaps FROM dossiers")
        statuts_disponibles = sorted([row['statut_cnaps'] for row in cur_statuts if row['statut_cnaps']])

        # Appliquer le filtre
        if filtre_cnaps != 'Tous':
            cur = conn.execute("SELECT * FROM dossiers WHERE statut_cnaps=?", (filtre_cnaps,))
        else:
            cur = conn.execute("SELECT * FROM dossiers")
        dossiers = cur.fetchall()

    return render_template("index.html", dossiers=dossiers, filtre_cnaps=filtre_cnaps, statuts_disponibles=statuts_disponibles)


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
    response.headers['Content-Disposition'] = f'attachment; filename=attestation_{formation}_{stagiaire["nom"]}.pdf'
    return response

from flask import send_file, request, redirect, url_for, flash
import json

@app.route('/export')
def export_data():
    try:
        return send_file('data.json', as_attachment=True)
    except Exception as e:
        return str(e), 500

@app.route('/import', methods=['GET', 'POST'])
def import_data():
    if request.method == 'POST':
        file = request.files.get('file')
        if file and file.filename.endswith('.json'):
            file.save('data.json')
            flash('Import réussi.')
            return redirect(url_for('accueil'))
        else:
            flash('Fichier invalide.')
            return redirect(url_for('import_data'))
    return '''
        <!doctype html>
        <title>Importer données</title>
        <h1>Importer un fichier JSON</h1>
        <form method=post enctype=multipart/form-data>
          <input type=file name=file>
          <input type=submit value=Importer>
        </form>
    '''
