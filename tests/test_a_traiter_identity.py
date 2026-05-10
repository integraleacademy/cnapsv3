import os
import sqlite3
import tempfile
import unittest

import app as cnaps_app


class ATraiterIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "test.db")

        cnaps_app.app.config["TESTING"] = True
        cnaps_app.DB_NAME = self.db_path
        cnaps_app.init_db()

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dossiers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nom TEXT NOT NULL,
                    prenom TEXT NOT NULL,
                    statut_cnaps TEXT
                )
                """
            )
            cur = conn.execute(
                "INSERT INTO dossiers (nom, prenom, statut_cnaps) VALUES (?, ?, ?)",
                ("Ancien", "Prenom", "A TRAITER"),
            )
            self.dossier_id = cur.lastrowid
            cur = conn.execute(
                """
                INSERT INTO public_requests (dossier_id, nom, prenom, email, date_naissance)
                VALUES (?, ?, ?, ?, ?)
                """,
                (self.dossier_id, "Ancien", "Prenom", "test@example.com", "1990-01-01"),
            )
            self.request_id = cur.lastrowid

        self.client = cnaps_app.app.test_client()
        with self.client.session_transaction() as sess:
            sess["user"] = "admin@example.com"

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_identity_autosave_updates_public_request_and_dossier(self):
        response = self.client.post(
            f"/a-traiter/{self.request_id}/identity",
            json={"field": "nom", "value": "Nouveau"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True, "field": "nom", "value": "Nouveau"})

        with sqlite3.connect(self.db_path) as conn:
            public_name = conn.execute(
                "SELECT nom FROM public_requests WHERE id = ?",
                (self.request_id,),
            ).fetchone()[0]
            dossier_name = conn.execute(
                "SELECT nom FROM dossiers WHERE id = ?",
                (self.dossier_id,),
            ).fetchone()[0]

        self.assertEqual(public_name, "Nouveau")
        self.assertEqual(dossier_name, "Nouveau")

    def test_identity_autosave_rejects_invalid_field(self):
        response = self.client.post(
            f"/a-traiter/{self.request_id}/identity",
            json={"field": "email", "value": "Nouveau"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"ok": False, "error": "Champ invalide"})


if __name__ == "__main__":
    unittest.main()
