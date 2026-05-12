import io
import os
import sqlite3
import tempfile
import unittest

import app as cnaps_app


class AdminDocumentUploadTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "test.db")
        self.upload_dir = os.path.join(self.tmpdir.name, "uploads")

        cnaps_app.app.config["TESTING"] = True
        cnaps_app.DB_NAME = self.db_path
        cnaps_app.UPLOAD_DIR = self.upload_dir
        cnaps_app.init_db()

        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO public_requests (nom, prenom, email, date_naissance, missing_doc_types)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "Dupont",
                    "Jean",
                    "jean@example.com",
                    "1990-01-01",
                    '["proof_address", "identity"]',
                ),
            )
            self.request_id = cur.lastrowid

        self.client = cnaps_app.app.test_client()
        with self.client.session_transaction() as sess:
            sess["user"] = "admin@example.com"

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_admin_can_add_pdf_document_and_clear_matching_missing_type(self):
        response = self.client.post(
            f"/a-traiter/{self.request_id}/documents/add",
            data={
                "doc_type": "proof_address",
                "document": (io.BytesIO(b"%PDF-1.4\n%test"), "justificatif.pdf"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            doc = conn.execute(
                "SELECT * FROM request_documents WHERE request_id = ?",
                (self.request_id,),
            ).fetchone()
            missing_doc_types = conn.execute(
                "SELECT missing_doc_types FROM public_requests WHERE id = ?",
                (self.request_id,),
            ).fetchone()[0]

        self.assertIsNotNone(doc)
        self.assertEqual(doc["doc_type"], "proof_address")
        self.assertEqual(doc["original_name"], "justificatif.pdf")
        self.assertTrue(os.path.exists(os.path.join(self.upload_dir, doc["storage_path"])))
        self.assertEqual(missing_doc_types, '["identity"]')

    def test_admin_upload_rejects_non_pdf_document(self):
        response = self.client.post(
            f"/a-traiter/{self.request_id}/documents/add",
            data={
                "doc_type": "identity",
                "document": (io.BytesIO(b"not a pdf"), "photo.jpg"),
            },
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 302)

        with sqlite3.connect(self.db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM request_documents").fetchone()[0]

        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
