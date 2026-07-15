import os
import sqlite3
import tempfile
import unittest

import app as cnaps_app


class ApiATraiterTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "test.db")

        cnaps_app.app.config["TESTING"] = True
        cnaps_app.DB_NAME = self.db_path
        cnaps_app.CNAPSV3_API_TOKEN = "expected-token"
        cnaps_app.init_db()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dossiers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nom TEXT NOT NULL,
                    prenom TEXT NOT NULL,
                    statut_cnaps TEXT,
                    commentaire TEXT
                )
                """
            )

        self.client = cnaps_app.app.test_client()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _auth_headers(self, token="expected-token"):
        return {"Authorization": f"Bearer {token}"}

    def _insert_request(self):
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO public_requests (nom, prenom, email, date_naissance, formation, session_date)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("Dupont", "Jean", "jean@example.com", "1990-01-01", "APS", "Session test"),
            )
            return cur.lastrowid

    def test_api_a_traiter_returns_401_without_redirect_when_token_missing_or_invalid(self):
        missing = self.client.get("/api/a-traiter")
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(missing.location, None)
        self.assertEqual(missing.get_json(), {"success": False, "error": "UNAUTHORIZED"})

        invalid = self.client.get("/api/a-traiter", headers=self._auth_headers("bad-token"))
        self.assertEqual(invalid.status_code, 401)
        self.assertEqual(invalid.location, None)
        self.assertEqual(invalid.get_json(), {"success": False, "error": "UNAUTHORIZED"})

    def test_api_a_traiter_returns_current_a_traiter_dataset_as_json(self):
        request_id = self._insert_request()

        response = self.client.get("/api/a-traiter", headers=self._auth_headers())

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["success"], True)
        self.assertEqual(len(body["requests"]), 1)
        self.assertEqual(body["requests"][0]["id"], request_id)
        self.assertEqual(body["requests"][0]["nom"], "Dupont")
        self.assertEqual(body["requests"][0]["prenom"], "Jean")
        self.assertEqual(body["requests"][0]["email"], "jean@example.com")
        self.assertIn("cnaps_is_expired", body["requests"][0])

    def test_html_a_traiter_still_requires_user_login(self):
        response = self.client.get("/a-traiter")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.location)


if __name__ == "__main__":
    unittest.main()
