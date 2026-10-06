import io
import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import app as cnaps
import document_analysis as checks
from test_document_analysis import blank_pdf, model_result


class SavedDocumentAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db, self.old_upload = cnaps.DB_NAME, cnaps.UPLOAD_DIR
        cnaps.DB_NAME = os.path.join(self.tmp.name, "db.sqlite")
        cnaps.UPLOAD_DIR = os.path.join(self.tmp.name, "uploads")
        cnaps.app.testing = True
        cnaps.init_db()
        os.makedirs(os.path.join(cnaps.UPLOAD_DIR, "1"))
        with open(os.path.join(cnaps.UPLOAD_DIR, "1", "bill.pdf"), "wb") as source:
            source.write(blank_pdf(6))
        with sqlite3.connect(cnaps.DB_NAME) as conn:
            conn.execute("INSERT INTO public_requests (id, nom, prenom, email, date_naissance) VALUES (1, 'Test', 'Test', 'test@example.com', '1990-01-01')")
            conn.execute("""INSERT INTO request_documents (id, request_id, doc_type, original_name, stored_name, storage_path, review_status, is_conforme)
                            VALUES (1, 1, 'proof_address', 'bill.pdf', 'bill.pdf', '1/bill.pdf', 'conforme', 1)""")
        self.client = cnaps.app.test_client()
        with self.client.session_transaction() as session:
            session["user"] = "admin@example.com"
            session["document_analysis_token"] = "test-token"
        self.url = "/a-traiter/1/documents/1/analyze"

    def tearDown(self):
        cnaps.DB_NAME, cnaps.UPLOAD_DIR = self.old_db, self.old_upload
        self.tmp.cleanup()

    def submit(self, **changes):
        return self.client.post(self.url, data={"document_analysis_token": "test-token", **changes},
                                headers={"Accept": "application/json"})

    def test_six_page_bill_is_analyzed_and_persisted_without_altering_review(self):
        result = model_result(document_type="address", address_kind="electricity",
                              document_date=checks.datetime.now(checks.FRANCE_TZ).date().isoformat(),
                              date_kind="invoice", date_confidence="high")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), patch.object(checks, "call_openai", return_value=result) as provider:
            response = self.submit(only_missing="1")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json["analysis"]["status"], "success")
            self.assertEqual(len(provider.call_args.args[0]), 6)
            self.assertEqual(self.submit(only_missing="1").status_code, 200)
            self.assertEqual(provider.call_count, 1)
        with sqlite3.connect(cnaps.DB_NAME) as conn:
            saved, status, conforms = conn.execute("SELECT auto_analysis_json, review_status, is_conforme FROM request_documents WHERE id = 1").fetchone()
        self.assertEqual(json.loads(saved)["status"], "success")
        self.assertEqual((status, conforms), ("conforme", 1))

    def test_provider_failure_is_saved_as_non_conclusive_with_reason(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), patch.object(checks, "call_openai", side_effect=ValueError("incomplete_response")):
            response = self.submit()
        self.assertEqual(response.json["analysis"]["reason_code"], "incomplete_response")
        self.assertIn("Vérification non concluante", response.json["html"])

    def test_csrf_login_inactive_and_other_dossier_cannot_launch_a_check(self):
        with patch.object(cnaps, "analyze_document_bytes") as analyze:
            self.assertEqual(self.submit(document_analysis_token="wrong").status_code, 403)
            self.assertEqual(self.client.post(self.url, data={"document_analysis_token": "test-token"}, headers={"Origin": "https://other.example"}).status_code, 403)
            original = self.url
            self.url = "/a-traiter/2/documents/1/analyze"
            self.assertEqual(self.submit().status_code, 404)
            self.url = original
            with sqlite3.connect(cnaps.DB_NAME) as conn:
                conn.execute("UPDATE request_documents SET is_active = 0 WHERE id = 1")
            self.assertEqual(self.submit().status_code, 404)
            self.assertEqual(cnaps.app.test_client().post(self.url).status_code, 302)
            analyze.assert_not_called()

    def test_replaced_document_cannot_receive_stale_result(self):
        def replace_during_analysis(*args):
            with sqlite3.connect(cnaps.DB_NAME) as conn:
                conn.execute("UPDATE request_documents SET is_active = 0 WHERE id = 1")
            return {"status": "success", "message": "OK"}, 200
        with patch.object(cnaps, "analyze_document_bytes", side_effect=replace_during_analysis):
            self.assertEqual(self.submit().status_code, 409)
        with sqlite3.connect(cnaps.DB_NAME) as conn:
            self.assertIsNone(conn.execute("SELECT auto_analysis_json FROM request_documents WHERE id = 1").fetchone()[0])

    def test_only_unchecked_address_is_automatically_recovered(self):
        response = self.client.get("/a-traiter/1/documents")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'data-check-missing', response.data)
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            self.submit()
        self.assertNotIn(b'data-check-missing', self.client.get("/a-traiter/1/documents").data)

    def test_identity_limit_is_unchanged(self):
        with self.assertRaisesRegex(ValueError, "page_limit"):
            checks.render_pages(blank_pdf(5))
        with self.assertRaisesRegex(ValueError, "page_limit"):
            checks.render_pages(blank_pdf(13), max_pages=checks.MAX_ADDRESS_PAGES)


if __name__ == "__main__":
    unittest.main()
