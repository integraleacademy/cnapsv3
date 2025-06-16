import unicodedata
import uuid

from flask import Flask, render_template, request, redirect, send_file
import sqlite3
import os
from datetime import datetime
from docx import Document
from docx.shared import Inches

app = Flask(__name__)
app.secret_key = "cnaps_clé_ultra_secrète_42"
DB_NAME = "cnaps.db"

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS dossiers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nom TEXT NOT NULL,
                prenom TEXT NOT NULL,
                formation TEXT NOT NULL,
                session TEXT NOT NULL,
                lien TEXT,
                statut TEXT DEFAULT 'INCOMPLET', commentaire TEXT
            )
        """)




@app.route("/")
def index():
    statuts_cnaps = [
        "--", "TRANSMIS", "ENREGISTRÉ", "INSTRUCTION", "ACCEPTÉ", "REFUSÉ", "PIÈCES COMPLÉMENTAIRES", "DÉCISION EN COURS"
    ]
    
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

    
    return render_template("index.html", dossiers=dossiers, filtre_cnaps=filtre_cnaps, statuts_disponibles=statuts_disponibles, statuts_cnaps=statuts_cnaps)




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


@app.route("/statut/<int:id>/<string:new_status>")
def update_statut(id, new_status):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("UPDATE dossiers SET statut = ? WHERE id = ?", (new_status, id))
    return redirect("/")

@app.route("/delete/<int:id>")
def delete(id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("DELETE FROM dossiers WHERE id = ?", (id,))
    return redirect("/")

@app.route("/attestation/<int:id>")
def attestation(id):
    with sqlite3.connect(DB_NAME) as conn:
        dossier = conn.execute("SELECT * FROM dossiers WHERE id = ?", (id,)).fetchone()

    nom, prenom, formation, session = dossier[1], dossier[2], dossier[3], dossier[4]
    date_today = datetime.now().strftime("%d/%m/%Y")

    doc = Document()
    doc.add_heading("ANNEXE : Justificatif de préinscription à une formation", 0)
    doc.add_paragraph("Cadre réservé à l’organisme de formation")
    doc.add_paragraph(f"Je soussigné(e), Monsieur Clément VAILLANT")
    doc.add_paragraph("Responsable de l'organisme de formation : INTEGRALE SECURITE FORMATIONS")
    doc.add_paragraph("Numéro d'enregistrement DIRECCTE : 93830600283")
    doc.add_paragraph("Autorisé à exercer par le CNAPS sous le numéro : FOR-083-2027-02-08-20220755135")
    doc.add_paragraph("Téléphone : 04 22 47 07 68")
    doc.add_paragraph("Adresse électronique : integralesecuriteformations@gmail.com")
    doc.add_paragraph(f"Certifie que Monsieur / Madame : {nom} {prenom}")
    doc.add_paragraph("est préinscrit(e) à la formation qualifiante ci-dessous :")

    if formation == "A3P":
        doc.add_paragraph("Libellé exact de la formation : AGENT DE PROTECTION PHYSIQUE DES PERSONNES (A3P)")
        doc.add_paragraph("Numéro d'enregistrement RNCP : 35098")
        doc.add_paragraph("Nature de la formation : Titre à Finalité Professionnelle (TFP) Agent de Protection Physique des Personnes - Agrément de la CPNEFP n°8320111201 en date du 02/02/2021")
    else:
        doc.add_paragraph("Libellé exact de la formation : AGENT DE PREVENTION ET DE SECURITE (APS)")
        doc.add_paragraph("Numéro d'enregistrement RNCP : 34054")
        doc.add_paragraph("Nature de la formation : Titre à Finalité Professionnelle (TFP) Agent de Prévention et de Sécurité - Agrément de la CPNEFP n°8320032701 en date du 30/11/2020")

    doc.add_paragraph(f"Dates de la formation : {session} qui se déroulera à Puget sur Argens (83480).")
    doc.add_paragraph("Lieu(x) de réalisation de la formation : Intégrale Sécurité Formations - 54 chemin du Carreou - 83480 PUGET SUR ARGENS")
    doc.add_paragraph("")
    doc.add_paragraph("Monsieur Clément VAILLANT")
    doc.add_paragraph("Directeur Général – Intégrale Sécurité Formations")

    doc.add_picture('static/signature_bloc.png', width=Inches(3.8))

    filename = f"attestation_{nom}_{prenom}.docx"
    filepath = os.path.join("temp", filename)
    os.makedirs("temp", exist_ok=True)
    doc.save(filepath)

    return send_file(filepath, as_attachment=True)






@app.route("/update_date/<int:id>", methods=["POST"])
def update_date(id):
    data = request.get_json()
    new_date = data.get("date_transmission")
    conn = sqlite3.connect("cnaps.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE dossiers SET date_transmission = ? WHERE id = ?", (new_date, id))
    conn.commit()
    conn.close()
    return "Date mise à jour"


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 10000))
    app.run(debug=True, host="0.0.0.0", port=port)

@app.route("/commentaire/<int:id>", methods=["POST"])
def commentaire(id):
    texte = request.form["commentaire"]
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("UPDATE dossiers SET commentaire = ? WHERE id = ?", (texte, id))
    return redirect("/")


@app.route("/ajouter_session", methods=["GET", "POST"])
def ajouter_session():
    if request.method == "POST":
        session_type = request.form.get("type")
        nom = request.form.get("nom")
        date_debut = request.form.get("date_debut")
        date_fin = request.form.get("date_fin")

        conn = sqlite3.connect("/data/cnaps.db")
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT,
                nom TEXT,
                date_debut TEXT,
                date_fin TEXT
            )
        """)
        c.execute("INSERT INTO sessions (type, nom, date_debut, date_fin) VALUES (?, ?, ?, ?)",
                  (session_type, nom, date_debut, date_fin))
        conn.commit()
        conn.close()

        return redirect("/")
    return render_template("ajouter_session.html")
    if request.method == "POST":
        nom_session = request.form.get("nom_session")
        date_session = request.form.get("date_session")

        conn = sqlite3.connect("/data/cnaps.db")
        c = conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, nom TEXT, date TEXT)")
        c.execute("INSERT INTO sessions (nom, date) VALUES (?, ?)", (nom_session, date_session))
        conn.commit()
        conn.close()

        return redirect("/")
    return render_template("ajouter_session.html")

from flask import Flask, request, send_file, redirect, render_template, flash
import pandas as pd
import sqlite3
import os
from io import BytesIO

@app.route("/export", methods=["GET"])
def exporter_donnees():
    conn = sqlite3.connect("cnaps.db")
    df = pd.read_sql_query("SELECT * FROM dossiers", conn)
    conn.close()

    output = BytesIO()
    df.to_csv(output, index=False)
    output.seek(0)

    return send_file(
        output,
        mimetype="text/csv",
        as_attachment=True,
        download_name="export_dossiers.csv"
    )


@app.route("/import", methods=["GET", "POST"])
def importer_donnees():
    if request.method == "POST":
        fichier = request.files["fichier_csv"]
        if not fichier:
            flash("Aucun fichier sélectionné.")
            return redirect("/")

        df = pd.read_csv(fichier)

        # Dictionnaire de mapping intelligent
        mapping = {
            'nom': ['nom'],
            'prenom': ['prenom', 'prénom'],
            'formation': ['formation'],
            'session': ['session'],
            'lien': ['lien', 'url'],
            'statut': ['statut'],
            'commentaire': ['commentaire', 'remarque'],
            'statut_cnaps': ['statutcnaps', 'cnaps', 'statut cnaps']
        }

        # Normaliser les colonnes existantes
        new_columns = {}
        for col in df.columns:
            norm_col = unicodedata.normalize('NFD', col).encode('ascii', 'ignore').decode("utf-8")
            norm_col = norm_col.lower().replace(" ", "").replace("-", "").replace("_", "")
            for target, possibles in mapping.items():
                if norm_col in [p.lower().replace(" ", "").replace("-", "").replace("_", "") for p in possibles]:
                    new_columns[col] = target
                    break

        df.rename(columns=new_columns, inplace=True)

        # Ajouter les colonnes manquantes
        for target in mapping.keys():
            if target not in df.columns:
                df[target] = ''

        with sqlite3.connect(DB_NAME) as conn:
            conn.execute("DELETE FROM dossiers")
            for _, row in df.iterrows():
                conn.execute("""INSERT INTO dossiers 
                    (nom, prenom, formation, session, lien, statut, commentaire, statut_cnaps)
                    VALUES (?,?,?,?,?,?,?,?)""", 
                    (row['nom'], row['prenom'], row['formation'], row['session'],
                     row['lien'], row['statut'] if row['statut'] else 'INCOMPLET', 
                     row['commentaire'], row['statut_cnaps']))

        flash("Importation réussie !")
        return redirect("/")

    return render_template("importer.html")





@app.route("/statut_cnaps/<int:id>", methods=["POST"])
def modifier_statut_cnaps(id):
    statut_cnaps = request.form["statut_cnaps"]
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("UPDATE dossiers SET statut_cnaps = ? WHERE id = ?", (statut_cnaps, id))
    return redirect("/")
