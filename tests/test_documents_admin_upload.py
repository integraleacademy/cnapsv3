import io
import json
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

    def test_admin_can_add_multiple_pdf_documents_at_once(self):
        response = self.client.post(
            f"/a-traiter/{self.request_id}/documents/add",
            data={
                "doc_type": "identity",
                "documents": [
                    (io.BytesIO(b"%PDF-1.4\n%recto"), "identite-recto.pdf"),
                    (io.BytesIO(b"%PDF-1.4\n%verso"), "identite-verso.pdf"),
                ],
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            docs = conn.execute(
                "SELECT * FROM request_documents WHERE request_id = ? ORDER BY original_name",
                (self.request_id,),
            ).fetchall()
            missing_doc_types = conn.execute(
                "SELECT missing_doc_types FROM public_requests WHERE id = ?",
                (self.request_id,),
            ).fetchone()[0]

        self.assertEqual(len(docs), 2)
        self.assertEqual([doc["original_name"] for doc in docs], ["identite-recto.pdf", "identite-verso.pdf"])
        self.assertTrue(all(doc["doc_type"] == "identity" for doc in docs))
        self.assertEqual(missing_doc_types, '["proof_address"]')

    def _create_document(self, doc_type="proof_address", original_name="ancien.pdf"):
        stored_name = f"stored-{original_name}"
        request_folder = os.path.join(self.upload_dir, str(self.request_id))
        os.makedirs(request_folder, exist_ok=True)
        with open(os.path.join(request_folder, stored_name), "wb") as stored_file:
            stored_file.write(b"%PDF-1.4\n%old")

        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO request_documents (request_id, doc_type, original_name, stored_name, storage_path)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    self.request_id,
                    doc_type,
                    original_name,
                    stored_name,
                    os.path.join(str(self.request_id), stored_name),
                ),
            )
            return cur.lastrowid

    def test_admin_can_replace_document_from_its_card(self):
        document_id = self._create_document()

        response = self.client.post(
            f"/a-traiter/{self.request_id}/documents/{document_id}/replace",
            data={
                "document": (io.BytesIO(b"%PDF-1.4\n%new"), "nouveau-justificatif.pdf"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            docs = conn.execute(
                "SELECT * FROM request_documents WHERE request_id = ? ORDER BY id",
                (self.request_id,),
            ).fetchall()
            missing_doc_types = conn.execute(
                "SELECT missing_doc_types FROM public_requests WHERE id = ?",
                (self.request_id,),
            ).fetchone()[0]

        self.assertEqual(len(docs), 2)
        self.assertEqual(docs[0]["is_active"], 0)
        self.assertEqual(docs[1]["is_active"], 1)
        self.assertEqual(docs[1]["doc_type"], "proof_address")
        self.assertEqual(docs[1]["original_name"], "nouveau-justificatif.pdf")
        self.assertEqual(docs[1]["review_status"], "pending")
        self.assertEqual(missing_doc_types, '["identity"]')

    def test_invalid_replacement_keeps_current_document_active(self):
        document_id = self._create_document()

        response = self.client.post(
            f"/a-traiter/{self.request_id}/documents/{document_id}/replace",
            data={
                "document": (io.BytesIO(b"not a pdf"), "photo.jpg"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)

        with sqlite3.connect(self.db_path) as conn:
            active_count = conn.execute(
                "SELECT COUNT(*) FROM request_documents WHERE request_id = ? AND is_active = 1",
                (self.request_id,),
            ).fetchone()[0]

        self.assertEqual(active_count, 1)

    def test_admin_can_delete_document_from_its_card(self):
        document_id = self._create_document()

        response = self.client.post(
            f"/a-traiter/{self.request_id}/documents/{document_id}/delete",
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            doc = conn.execute(
                "SELECT * FROM request_documents WHERE id = ?",
                (document_id,),
            ).fetchone()
            missing_doc_types = json.loads(
                conn.execute(
                    "SELECT missing_doc_types FROM public_requests WHERE id = ?",
                    (self.request_id,),
                ).fetchone()[0]
            )

        self.assertEqual(doc["is_active"], 0)
        self.assertIn("proof_address", missing_doc_types)

    def test_deleting_one_of_two_documents_does_not_mark_type_as_missing(self):
        document_id = self._create_document(original_name="premier.pdf")
        self._create_document(original_name="second.pdf")

        response = self.client.post(
            f"/a-traiter/{self.request_id}/documents/{document_id}/delete",
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)

        with sqlite3.connect(self.db_path) as conn:
            missing_doc_types = json.loads(
                conn.execute(
                    "SELECT missing_doc_types FROM public_requests WHERE id = ?",
                    (self.request_id,),
                ).fetchone()[0]
            )

        self.assertNotIn("proof_address", missing_doc_types)


if __name__ == "__main__":
    unittest.main()
