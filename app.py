
from flask import Flask, render_template, request, redirect, make_response, send_file, url_for, flash, render_template_string
from weasyprint import HTML
import sqlite3
import os
import json

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev')
DB_NAME = "cnaps.db"

# Fonction utilitaire pour récupérer un stagiaire
def get_stagiaire_by_id(id):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    stagiaire = conn.execute("SELECT * FROM dossiers WHERE id = ?", (id,)).fetchone()
    conn.close()
    return stagiaire

# Route d’accueil avec filtre
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

# Téléchargement attestation PDF
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

# Route export JSON
@app.route('/export')
def export_data():
    try:
        with sqlite3.connect(DB_NAME) as conn:
            conn.row_factory = sqlite3.Row
            data = conn.execute("SELECT * FROM dossiers").fetchall()
            data_list = [dict(row) for row in data]
        with open('data.json', 'w', encoding='utf-8') as f:
            json.dump(data_list, f, ensure_ascii=False, indent=2)
        return send_file('data.json', as_attachment=True)
    except Exception as e:
        return str(e), 500

# Route import JSON
@app.route('/import', methods=['GET', 'POST'])
def import_data():
    if request.method == 'POST':
        file = request.files.get('file')
        if file and file.filename.endswith('.json'):
            try:
                data = json.load(file)
                with sqlite3.connect(DB_NAME) as conn:
                    conn.execute("DELETE FROM dossiers")
                    for entry in data:
                        conn.execute("""INSERT INTO dossiers (nom, prenom, formation, session, statut_dossier, statut_cnaps, commentaire)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", (
                            entry.get('nom', ''),
                            entry.get('prenom', ''),
                                                        entry.get('formation', ''),
                            entry.get('session', ''),
                            entry.get('statut_dossier', ''),
                            entry.get('statut_cnaps', ''),
                            entry.get('commentaire', '')
                        ))
                flash('Import réussi.')
            except Exception as e:
                flash(f"Erreur lors de l'import : {e}")
            return redirect(url_for('index'))
        else:
            flash('Fichier invalide.')
            return redirect(url_for('import_data'))

    return render_template_string("""
        <!doctype html>
        <title>Importer données</title>
        <h1>Importer un fichier JSON</h1>
        <form method=post enctype=multipart/form-data>
          <input type=file name=file required>
          <input type=submit value=Importer>
        </form>
        <p><a href="/">Retour à l'accueil</a></p>
    """)

# Route pour modifier le statut CNAPS
@app.route('/statut_cnaps/<int:id>', methods=['POST'])
def changer_statut_cnaps(id):
    new_statut = request.form.get('statut_cnaps')
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("UPDATE dossiers SET statut_cnaps = ? WHERE id = ?", (new_statut, id))
    return redirect(url_for('index'))
