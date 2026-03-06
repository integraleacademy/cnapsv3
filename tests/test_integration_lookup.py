import os
import sqlite3
import tempfile
import unittest

import app as cnaps_app


class IntegrationLookupCnapsTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "test.db")

        cnaps_app.app.config["TESTING"] = True
        cnaps_app.DB_NAME = self.db_path
        cnaps_app.GESTIONSTAGIAIRE_SYNC_TOKEN = "expected-token"
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

        self.client = cnaps_app.app.test_client()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _auth_headers(self, token="expected-token"):
        return {"Authorization": f"Bearer {token}"}

    def _insert_dossier(self, nom, prenom):
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO dossiers (nom, prenom, statut_cnaps) VALUES (?, ?, ?)",
                (nom, prenom, "INSTRUCTION"),
            )
            return cur.lastrowid

    def _insert_request(self, dossier_id, email):
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO public_requests (dossier_id, nom, prenom, email, date_naissance)
                VALUES (?, ?, ?, ?, ?)
                """,
                (dossier_id, "Nom", "Prenom", email, "1990-01-01"),
            )
            return cur.lastrowid

    def test_lookup_returns_401_when_token_missing_or_invalid(self):
        payload = {"first_name": "Jean", "last_name": "Dupont"}

        missing = self.client.post(
            "/integrations/gestionstagiaire/cnaps/lookup",
            json=payload,
        )
        self.assertEqual(missing.status_code, 401)

        invalid = self.client.post(
            "/integrations/gestionstagiaire/cnaps/lookup",
            headers=self._auth_headers("bad-token"),
            json=payload,
        )
        self.assertEqual(invalid.status_code, 401)

    def test_lookup_returns_404_when_not_found(self):
        response = self.client.post(
            "/integrations/gestionstagiaire/cnaps/lookup",
            headers=self._auth_headers(),
            json={"first_name": "Inconnu", "last_name": "Personne"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json(), {"error": "NOT_FOUND"})

    def test_lookup_returns_409_when_ambiguous(self):
        d1 = self._insert_dossier("Dùpont", "Jean")
        self._insert_request(d1, "jean1@example.com")

        d2 = self._insert_dossier("Dupont", "Jean")
        self._insert_request(d2, "jean2@example.com")

        response = self.client.post(
            "/integrations/gestionstagiaire/cnaps/lookup",
            headers=self._auth_headers(),
            json={"first_name": "Jean", "last_name": "Dupont"},
        )

        self.assertEqual(response.status_code, 409)
        body = response.get_json()
        self.assertEqual(body["error"], "AMBIGUOUS")
        self.assertEqual(body["count"], 2)

    def test_lookup_returns_200_when_unique_match(self):
        dossier_id = self._insert_dossier("Dùpont", "Jean-Pierre")
        request_id = self._insert_request(dossier_id, "jean@example.com")

        response = self.client.post(
            "/integrations/gestionstagiaire/cnaps/lookup",
            headers=self._auth_headers(),
            json={
                "first_name": "  jean pierre ",
                "last_name": "du'pont",
                "email": " JEAN@EXAMPLE.COM ",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {
                "request_id": str(request_id),
                "dossier_id": str(dossier_id),
                "email": "jean@example.com",
            },
        )

    def test_lookup_returns_200_with_empty_email_when_missing(self):
        dossier_id = self._insert_dossier("Dupont", "Jeanne")
        request_id = self._insert_request(dossier_id, "")

        response = self.client.post(
            "/integrations/gestionstagiaire/cnaps/lookup",
            headers=self._auth_headers(),
            json={"first_name": "Jeanne", "last_name": "Dupont"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {
                "request_id": str(request_id),
                "dossier_id": str(dossier_id),
                "email": "",
            },
        )


if __name__ == "__main__":
    unittest.main()
