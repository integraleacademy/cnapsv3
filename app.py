import os
import sqlite3
import csv
from flask import Flask, render_template, request, redirect, send_file, url_for
from datetime import datetime

app = Flask(__name__)
DATABASE = 'cnaps.db'

def init_db():
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dossiers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nom TEXT,
                prenom TEXT,
                formation TEXT,
                session TEXT,
                lien_suivi TEXT,
                statut_dossier TEXT,
                statut_cnaps TEXT,
                commentaire TEXT,
                date_de_transmission TEXT
            )
        """)
        conn.commit()

init_db()

@app.route("/", methods=["GET"])
def index():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    query = "SELECT * FROM dossiers WHERE 1=1"
    params = []

    search = request.args.get("search", "").strip()
    formation = request.args.get("formation", "").strip()
    statut_dossier = request.args.get("statut_dossier", "").strip()
    statut_cnaps = request.args.get("statut_cnaps", "").strip()
    date_debut = request.args.get("date_debut", "").strip()
    date_fin = request.args.get("date_fin", "").strip()

    if search:
        query += " AND (nom LIKE ? OR prenom LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    if formation:
        query += " AND formation LIKE ?"
        params.append(f"%{formation}%")
    if statut_dossier:
        query += " AND statut_dossier LIKE ?"
        params.append(f"%{statut_dossier}%")
    if statut_cnaps:
        query += " AND statut_cnaps LIKE ?"
        params.append(f"%{statut_cnaps}%")
    if date_debut:
        query += " AND date(date_de_transmission) >= date(?)"
        params.append(date_debut)
    if date_fin:
        query += " AND date(date_de_transmission) <= date(?)"
        params.append(date_fin)

    cursor.execute(query, params)
    dossiers = cursor.fetchall()
    conn.close()

    return render_template("index.html", dossiers=dossiers, request=request)

@app.route("/ajouter", methods=["POST"])
def ajouter():
    data = request.form
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO dossiers (nom, prenom, formation, session, lien_suivi, statut_dossier, statut_cnaps, commentaire, date_de_transmission)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.get("nom"), data.get("prenom"), data.get("formation"), data.get("session"),
            data.get("lien_suivi"), data.get("statut_dossier"), data.get("statut_cnaps"),
            data.get("commentaire"), data.get("date_de_transmission")
        ))
        conn.commit()
    return redirect(url_for("index"))

@app.route("/modifier/<int:id>", methods=["POST"])
def modifier(id):
    data = request.form
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE dossiers SET nom=?, prenom=?, formation=?, session=?, lien_suivi=?, 
            statut_dossier=?, statut_cnaps=?, commentaire=?, date_de_transmission=? WHERE id=?
        """, (
            data.get("nom"), data.get("prenom"), data.get("formation"), data.get("session"),
            data.get("lien_suivi"), data.get("statut_dossier"), data.get("statut_cnaps"),
            data.get("commentaire"), data.get("date_de_transmission"), id
        ))
        conn.commit()
    return redirect(url_for("index"))

@app.route("/supprimer/<int:id>")
def supprimer(id):
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM dossiers WHERE id=?", (id,))
        conn.commit()
    return redirect(url_for("index"))

@app.route("/export")
def export():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM dossiers")
    dossiers = cursor.fetchall()
    conn.close()

    filename = "export_cnaps.csv"
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "nom", "prenom", "formation", "session", "lien_suivi", "statut_dossier", "statut_cnaps", "commentaire", "date_de_transmission"])
        writer.writerows(dossiers)

    return send_file(filename, as_attachment=True)

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

# Route attestation sans PDF : affichage HTML simple
@app.route("/attestation/<int:id>")
def attestation(id):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM dossiers WHERE id=?", (id,))
    dossier = cursor.fetchone()
    conn.close()

    return render_template("attestation.html",
        nom=dossier[1],
        prenom=dossier[2],
        formation=dossier[3],
        session=dossier[4],
        lien_suivi=dossier[5],
        statut_dossier=dossier[6],
        statut_cnaps=dossier[7],
        commentaire=dossier[8],
        date_de_transmission=dossier[9]
    )
