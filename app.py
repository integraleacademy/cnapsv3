
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

        sessions = conn.execute("SELECT * FROM sessions ORDER BY date_debut DESC").fetchall()

    return render_template(
        "index.html",
        dossiers=dossiers,
        sessions=sessions,
        statuts=statuts_disponibles,
        submitted=request.args.get("submitted")
    )

@app.route("/admin/sessions", methods=["GET", "POST"])
def sessions():
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        if request.method == "POST":
            type_formation = request.form.get("type")
            nom = request.form.get("nom")
            date_debut = request.form.get("date_debut")
            date_fin = request.form.get("date_fin")
            if type_formation and nom and date_debut:
                conn.execute("INSERT INTO sessions (type, nom, date_debut, date_fin) VALUES (?, ?, ?, ?)",
                             (type_formation, nom, date_debut, date_fin))
                conn.commit()
            return redirect("/admin/sessions")

        sessions = conn.execute("SELECT * FROM sessions ORDER BY date_debut DESC").fetchall()
    return render_template("sessions.html", sessions=sessions)

@app.route("/admin/sessions/delete/<int:id>")
def delete_session(id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("DELETE FROM sessions WHERE id=?", (id,))
    return redirect("/admin/sessions")
