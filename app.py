
import sqlite3
import os
from flask import Flask

app = Flask(__name__)
DB_NAME = "cnaps.db"

def init_sessions():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT,
                nom TEXT,
                date_debut TEXT,
                date_fin TEXT
            )
        """)

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
                statut TEXT DEFAULT 'INCOMPLET',
                commentaire TEXT,
                statut_cnaps TEXT,
                date_transmission TEXT
            )
        """)

@app.route("/")
def index():
    return "Application CNAPS opérationnelle"

if __name__ == "__main__":
    init_db()
    init_sessions()
    port = int(os.environ.get("PORT", 10000))
    app.run(debug=True, host="0.0.0.0", port=port)
