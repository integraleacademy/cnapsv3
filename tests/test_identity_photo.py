import io
import json
import os
import sqlite3
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from PIL import Image
import app as cnaps_app
import document_analysis as analysis


def photo_file(image_format="JPEG", filename=None):
    image = io.BytesIO()
    Image.new("RGB", (350, 450), "#ccddee").save(image, format=image_format)
    image.seek(0)
    return image, filename or ("photo.png" if image_format == "PNG" else "photo.jpg")


class IdentityPhotoTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_db = cnaps_app.DB_NAME
        self.original_upload_dir = cnaps_app.UPLOAD_DIR
        cnaps_app.DB_NAME = os.path.join(self.tmpdir.name, "test.db")
        cnaps_app.UPLOAD_DIR = os.path.join(self.tmpdir.name, "uploads")
        cnaps_app.app.config["TESTING"] = True
        cnaps_app.init_db()
        with sqlite3.connect(cnaps_app.DB_NAME) as conn:
            conn.execute("""CREATE TABLE dossiers (
                id INTEGER PRIMARY KEY AUTOINCREMENT, nom TEXT, prenom TEXT,
                formation TEXT, session TEXT, lien TEXT, statut TEXT,
                commentaire TEXT, statut_cnaps TEXT, telephone TEXT
            )""")
        self.email = patch.object(cnaps_app, "_send_email_html").start()
        self.sms = patch.object(cnaps_app, "_send_sms").start()
        self.client = cnaps_app.app.test_client()
        self.admin = cnaps_app.app.test_client()
        with self.admin.session_transaction() as sess:
            sess["user"] = "admin@example.com"

    def tearDown(self):
        patch.stopall()
        cnaps_app.DB_NAME = self.original_db
        cnaps_app.UPLOAD_DIR = self.original_upload_dir
        self.tmpdir.cleanup()

    def payload(self, include_photo=True):
        data = {
            "nom": "Test", "prenom": "Photo", "email": "photo@example.com",
            "email_confirm": "photo@example.com", "telephone": "0612345678",
            "date_naissance": "01/01/1990",
            "identity": (io.BytesIO(b"%PDF-1.4\nidentity"), "identite.pdf"),
            "proof_address": (io.BytesIO(b"%PDF-1.4\naddress"), "domicile.pdf"),
        }
        data.update({label: "on" for label in cnaps_app.CHECKLIST_LABELS})
        if include_photo:
            data["identity_photo"] = photo_file()
        return data

    def submit(self, data=None):
        return self.client.post("/public-form", data=self.payload() if data is None else data,
                                content_type="multipart/form-data")

    def rows(self, sql, params=()):
        with sqlite3.connect(cnaps_app.DB_NAME) as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(sql, params).fetchall()

    def create_request(self):
        response = self.submit()
        self.assertEqual(response.status_code, 200)
        rows = self.rows("SELECT id FROM public_requests")
        self.assertEqual(len(rows), 1, response.get_data(as_text=True))
        return rows[0]["id"]

    def review(self, request_id, photo_status):
        data = {}
        for doc in self.rows("SELECT * FROM request_documents WHERE is_active = 1"):
            data[f"status_{doc['id']}"] = photo_status if doc["doc_type"] == "identity_photo" else "conforme"
            if doc["doc_type"] == "identity_photo":
                data[f"reason_{doc['id']}"] = "Photo floue : visage non visible."
        return self.admin.post(f"/a-traiter/{request_id}/documents/review", data=data)

    def test_public_form_displays_required_photo_criteria_and_acknowledgement(self):
        html = self.client.get("/public-form").get_data(as_text=True)
        self.assertIn('name="identity_photo"', html)
        self.assertIn('data-identity-photo required', html)
        self.assertIn("Photo non conforme = dossier rejeté", html)
        self.assertIn("sans capture d'écran", html)
        self.assertIn("J&#39;ai compris que mon dossier sera rejeté", html)

    def test_public_form_has_non_blocking_document_checks_and_signature_reminder(self):
        html = self.client.get("/public-form").get_data(as_text=True)
        for doc_type in ("identity", "host_identity", "proof_address", "hosting_certificate", "identity_photo"):
            self.assertIn(f'data-document-check="{doc_type}"', html)
        self.assertIn('data-check-date="', html)
        self.assertIn('<dialog class="document-analysis-modal"', html)
        self.assertIn('aria-labelledby="analysis-modal-title"', html)
        self.assertNotIn("Avez-vous vérifié que l'attestation d'hébergement est bien signée", html)
        self.assertIn('data-check-token="', html)
        self.assertIn('type="module" src="/static/document-checks.mjs?v=', html)

    def test_photo_is_visible_at_top_of_admin_document_page(self):
        request_id = self.create_request()
        html = self.admin.get(f"/a-traiter/{request_id}/documents").get_data(as_text=True)
        self.assertLess(html.index('<section class="dossier-photo-overview"'), html.index('id="ajouter-document"'))
        self.assertIn('loading="eager" fetchpriority="high"', html)
        self.assertIn('alt="Photo d\'identité de Photo Test"', html)

    def receipt(self, data, kind, result):
        with self.client.session_transaction() as sess:
            sess['document_analysis_token'] = 'receipt-test-session'
        with cnaps_app.app.test_request_context():
            analysis.session['document_analysis_token'] = 'receipt-test-session'
            return analysis.analysis_receipt(result, data, kind)

    def test_public_deposit_keeps_verified_warning_and_unchecked_per_file(self):
        data = self.payload()
        identity = {"status": "success", "message": "Informations lisibles", "identity_evidence": [
            {"type": "identity_card", "sides": ["front", "back"], "confidence": "high"}]}
        warning = {"status": "warning", "message": "Justificatif de plus de trois mois."}
        data['document_analysis_receipts'] = [
            self.receipt(data['identity'][0].getvalue(), 'identity', identity),
            self.receipt(data['proof_address'][0].getvalue(), 'proof_address', warning),
        ]
        self.assertEqual(self.submit(data).status_code, 200)
        docs = {row['doc_type']: row for row in self.rows('SELECT * FROM request_documents')}
        self.assertEqual(json.loads(docs['identity']['auto_analysis_json'])['status'], 'success')
        self.assertEqual(json.loads(docs['proof_address']['auto_analysis_json'])['status'], 'warning')
        self.assertIsNone(docs['identity_photo']['auto_analysis_json'])
        self.assertTrue(all(d['is_conforme'] is None and d['review_status'] == 'pending' for d in docs.values()))
        html = self.admin.get(f"/a-traiter/{docs['identity']['request_id']}/documents").get_data(as_text=True)
        for text in ('Document vérifié · Tout semble OK', 'Anomalie suspectée', 'Fichier envoyé malgré', 'Document non vérifié', warning['message']):
            self.assertIn(text, html)

    def test_receipt_cannot_follow_a_different_file_kind_session_or_be_tampered(self):
        from werkzeug.datastructures import FileStorage
        data = b'%PDF example'
        token = self.receipt(data, 'identity', {'status': 'success', 'message': 'Lisible'})
        for content, kind, session_token, receipt in [
            (b'%PDF changed', 'identity', 'receipt-test-session', token),
            (data, 'host_identity', 'receipt-test-session', token),
            (data, 'identity', 'another-session', token),
            (data, 'identity', 'receipt-test-session', token + 'x'),
        ]:
            with self.subTest(kind=kind, session=session_token), cnaps_app.app.test_request_context(method='POST', data={'document_analysis_receipts': receipt}):
                analysis.session['document_analysis_token'] = session_token
                stream = io.BytesIO(content)
                self.assertIsNone(analysis.submitted_analysis(FileStorage(stream=stream), kind))
                self.assertEqual(stream.tell(), 0)

    def test_old_positive_photo_receipt_is_saved_as_inconclusive(self):
        data = self.payload()
        data['document_analysis_receipts'] = self.receipt(data['identity_photo'][0].getvalue(), 'identity_photo',
            {'status': 'success', 'title': 'Photo : c’est bon !', 'message': ''})
        self.submit(data)
        photo = self.rows("SELECT * FROM request_documents WHERE doc_type='identity_photo'")[0]
        self.assertEqual(json.loads(photo['auto_analysis_json'])['status'], 'unknown')
        self.assertIsNone(photo['is_conforme'])
        self.assertEqual(photo['review_status'], 'pending')

    def test_old_photo_green_badge_is_removed_without_changing_stored_review(self):
        request_id = self.create_request()
        old_result = json.dumps({'status': 'success', 'message': '', 'checked_at': '2026-10-02T14:43:00+02:00'})
        with sqlite3.connect(cnaps_app.DB_NAME) as conn:
            conn.execute("UPDATE request_documents SET auto_analysis_json=?, is_conforme=1, review_status='conforme' WHERE doc_type='identity_photo'", (old_result,))
        html = self.admin.get(f'/a-traiter/{request_id}/documents').get_data(as_text=True)
        self.assertNotIn('Document vérifié · Tout semble OK', html)
        self.assertIn('Vérification non concluante', html)
        self.assertIn('L’ancien contrôle ne vérifiait pas explicitement les planches', html)
        photo = self.rows("SELECT * FROM request_documents WHERE doc_type='identity_photo'")[0]
        self.assertEqual(photo['auto_analysis_json'], old_result)
        self.assertEqual(photo['is_conforme'], 1)
        self.assertEqual(photo['review_status'], 'conforme')
        self.email.reset_mock()
        self.sms.reset_mock()
        self.admin.get(f'/a-traiter/{request_id}/documents')
        self.email.assert_not_called()
        self.sms.assert_not_called()

    def test_current_positive_photo_receipt_keeps_green_badge(self):
        data = self.payload()
        data['document_analysis_receipts'] = self.receipt(data['identity_photo'][0].getvalue(), 'identity_photo',
            {'status': 'success', 'message': '', 'photo_check_version': analysis.PHOTO_CHECK_VERSION})
        self.submit(data)
        photo = self.rows("SELECT * FROM request_documents WHERE doc_type='identity_photo'")[0]
        self.assertEqual(json.loads(photo['auto_analysis_json'])['status'], 'success')
        html = self.admin.get(f'/a-traiter/{photo["request_id"]}/documents').get_data(as_text=True)
        self.assertIn('Document vérifié · Tout semble OK', html)

    def test_initial_deposit_keeps_missing_verso_alert_despite_readable_file(self):
        data = self.payload()
        result = {"status": "success", "message": "Fichier lisible", "identity_evidence": [
            {"type": "identity_card", "sides": ["front"], "confidence": "high"}]}
        data['document_analysis_receipts'] = self.receipt(data['identity'][0].getvalue(), 'identity', result)
        self.submit(data)
        saved = json.loads(self.rows("SELECT auto_analysis_json FROM request_documents WHERE doc_type='identity'")[0][0])
        self.assertEqual(saved['status'], 'warning')
        self.assertIn('verso manquant', saved['message'])

    def test_public_replacement_keeps_its_own_result_and_admin_replacement_resets_it(self):
        request_id = self.create_request()
        original = self.rows("SELECT * FROM request_documents WHERE doc_type='proof_address'")[0]
        with sqlite3.connect(cnaps_app.DB_NAME) as conn:
            conn.execute("UPDATE request_documents SET review_status='notified_expected' WHERE id=?", (original['id'],))
        content = b'%PDF replacement'
        token = self.receipt(content, 'proof_address', {'status': 'unknown', 'message': 'Date incertaine'})
        response = self.client.post(f'/replace-documents/{request_id}', data={
            f"replace_{original['id']}": (io.BytesIO(content), 'new.pdf'), 'document_analysis_receipts': token}, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 200)
        replacement = self.rows("SELECT * FROM request_documents WHERE doc_type='proof_address' AND is_active=1")[0]
        self.assertEqual(json.loads(replacement['auto_analysis_json'])['status'], 'unknown')
        self.assertIn('Vérification non concluante', self.admin.get(f'/a-traiter/{request_id}/documents').get_data(as_text=True))
        self.admin.post(f"/a-traiter/{request_id}/documents/{replacement['id']}/replace", data={
            'document': (io.BytesIO(b'%PDF admin replacement'), 'admin.pdf')}, content_type='multipart/form-data')
        self.assertIsNone(self.rows("SELECT auto_analysis_json FROM request_documents WHERE doc_type='proof_address' AND is_active=1")[0][0])

    def test_photo_is_required_server_side(self):
        response = self.submit(self.payload(include_photo=False))
        self.assertIn("Document manquant : Photo", response.get_data(as_text=True))
        self.assertEqual(self.rows("SELECT * FROM public_requests"), [])
        self.email.assert_not_called()

    def test_photo_acknowledgement_is_required_server_side(self):
        data = self.payload()
        del data[cnaps_app.CHECKLIST_LABELS[1]]
        response = self.submit(data)
        self.assertIn("cocher toutes les cases", response.get_data(as_text=True))
        self.assertEqual(self.rows("SELECT * FROM public_requests"), [])

    def test_jpeg_and_png_are_stored_intact_and_pending(self):
        for fmt in ("JPEG", "PNG"):
            with self.subTest(fmt=fmt):
                data = self.payload()
                data["email"] = data["email_confirm"] = f"{fmt.lower()}@example.com"
                upload = photo_file(fmt, "PHOTO.JPG" if fmt == "JPEG" else "photo.png")
                original_bytes = upload[0].getvalue()
                data["identity_photo"] = upload
                self.assertEqual(self.submit(data).status_code, 200)
                photo = self.rows("SELECT * FROM request_documents WHERE doc_type = 'identity_photo' ORDER BY id DESC")[0]
                self.assertIsNone(photo["is_conforme"])
                self.assertEqual(photo["review_status"], "pending")
                with open(os.path.join(cnaps_app.UPLOAD_DIR, photo["storage_path"]), "rb") as saved:
                    self.assertEqual(saved.read(), original_bytes)

    def test_invalid_photo_uploads_do_not_create_a_dossier(self):
        cases = [
            (b"%PDF-1.4", "photo.pdf"), (b"not an image", "photo.jpg"),
            (b"", "empty.png"), (b"x" * (cnaps_app.MAX_DOCUMENT_SIZE_BYTES + 1), "large.jpg"),
            (photo_file("PNG")[0].getvalue(), "renamed.jpg"),
            (photo_file("JPEG")[0].getvalue()[:150], "truncated.jpg"),
            (b"heic", "photo.heic"),
        ]
        for content, filename in cases:
            with self.subTest(filename=filename):
                data = self.payload()
                data["identity_photo"] = (io.BytesIO(content), filename)
                response = self.submit(data)
                self.assertIn('class="flash"', response.get_data(as_text=True))
                self.assertEqual(self.rows("SELECT * FROM public_requests"), [])
        self.email.assert_not_called()

    def test_public_form_rejects_multiple_identity_photos(self):
        data = self.payload()
        data["identity_photo"] = [photo_file(), photo_file("PNG")]
        response = self.submit(data)
        self.assertIn("une seule photo", response.get_data(as_text=True))
        self.assertEqual(self.rows("SELECT * FROM public_requests"), [])

    def test_review_notify_replace_and_download_flow(self):
        request_id = self.create_request()
        photo = self.rows("SELECT * FROM request_documents WHERE doc_type = 'identity_photo'")[0]
        review_html = self.admin.get(f"/a-traiter/{request_id}/documents").get_data(as_text=True)
        self.assertIn("Photo d&#39;identité officielle", review_html)
        self.assertIn('alt="Photo d\'identité à contrôler"', review_html)
        self.review(request_id, "non_conforme")
        rejected = self.rows("SELECT * FROM request_documents WHERE id = ?", (photo["id"],))[0]
        self.assertEqual(rejected["is_conforme"], 0)
        self.assertEqual(rejected["non_conformite_reason"], "Photo floue : visage non visible.")
        self.assertEqual(self.admin.get(f"/a-traiter/{request_id}/download").status_code, 400)
        self.admin.post(f"/a-traiter/{request_id}/notify")
        self.assertIn("Photo d&#39;identité officielle", self.email.call_args.args[2])
        self.assertIn("Photo floue", self.email.call_args.args[2])
        self.assertEqual(self.rows("SELECT review_status FROM request_documents WHERE id = ?", (photo["id"],))[0][0], "notified_expected")
        replace_html = self.client.get(f"/replace-documents/{request_id}").get_data(as_text=True)
        self.assertIn('accept="image/jpeg,image/png,.jpg,.jpeg,.png"', replace_html)
        self.assertIn("Photo non conforme = dossier rejeté", replace_html)
        response = self.client.post(f"/replace-documents/{request_id}", data={f"replace_{photo['id']}": photo_file("PNG")}, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 200)
        photos = self.rows("SELECT * FROM request_documents WHERE doc_type = 'identity_photo' ORDER BY id")
        self.assertEqual([d["is_active"] for d in photos], [0, 1])
        self.assertIsNone(photos[1]["is_conforme"])
        self.assertEqual(photos[1]["review_status"], "pending")
        self.review(request_id, "conforme")
        bundle = self.admin.get(f"/a-traiter/{request_id}/download")
        self.assertEqual(bundle.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(bundle.data)) as archive:
            self.assertTrue(any(name.endswith(".png") and "Photo" in name for name in archive.namelist()))
        with sqlite3.connect(cnaps_app.DB_NAME) as conn:
            conn.execute("UPDATE public_requests SET missing_doc_types = ? WHERE id = ?", (json.dumps(["identity_photo"]), request_id))
        self.assertEqual(self.admin.get(f"/a-traiter/{request_id}/download").status_code, 400)

    def test_legacy_dossier_can_request_missing_photo(self):
        with sqlite3.connect(cnaps_app.DB_NAME) as conn:
            request_id = conn.execute("INSERT INTO public_requests (nom, prenom, email, date_naissance, missing_doc_types) VALUES ('Legacy', 'Test', 'legacy@example.com', '01/01/1990', ?)", (json.dumps(["identity_photo"]),)).lastrowid
        page = self.client.get(f"/replace-documents/{request_id}").get_data(as_text=True)
        self.assertIn('name="missing_identity_photo"', page)
        self.assertIn('data-document-check="identity_photo"', page)
        self.assertIn('<dialog class="document-analysis-modal"', page)
        response = self.client.post(f"/replace-documents/{request_id}", data={"missing_identity_photo": photo_file("PNG")}, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.rows("SELECT missing_doc_types FROM public_requests")[0][0], "[]")
        self.assertEqual(self.rows("SELECT review_status FROM request_documents")[0][0], "pending")

    def test_invalid_replacement_keeps_all_previous_files_and_displays_error(self):
        request_id = self.create_request()
        with sqlite3.connect(cnaps_app.DB_NAME) as conn:
            conn.execute("UPDATE request_documents SET is_conforme = 0, review_status = 'non_conforme'")
        docs = self.rows("SELECT * FROM request_documents ORDER BY id")
        data = {f"replace_{doc['id']}": (io.BytesIO(b"%PDF-1.4 new"), "new.pdf") for doc in docs}
        photo = next(d for d in docs if d["doc_type"] == "identity_photo")
        data[f"replace_{photo['id']}"] = (io.BytesIO(b"bad"), "bad.jpg")
        response = self.client.post(f"/replace-documents/{request_id}", data=data, content_type="multipart/form-data", follow_redirects=True)
        self.assertIn("illisible ou invalide", response.get_data(as_text=True))
        self.assertEqual(len(self.rows("SELECT * FROM request_documents")), 3)
        self.assertTrue(all(d["is_active"] for d in self.rows("SELECT * FROM request_documents")))

    def test_admin_can_add_replace_and_delete_photo_with_pending_review(self):
        with sqlite3.connect(cnaps_app.DB_NAME) as conn:
            request_id = conn.execute("INSERT INTO public_requests (nom, prenom, email, date_naissance) VALUES ('Admin', 'Test', 'admin@example.com', '01/01/1990')").lastrowid
        response = self.admin.post(f"/a-traiter/{request_id}/documents/add", data={"doc_type": "identity_photo", "documents": photo_file()}, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 302)
        photo = self.rows("SELECT * FROM request_documents")[0]
        response = self.admin.post(f"/a-traiter/{request_id}/documents/{photo['id']}/replace", data={"document": (io.BytesIO(b"%PDF invalid photo"), "invalid.pdf")}, content_type="multipart/form-data")
        self.assertEqual(len(self.rows("SELECT * FROM request_documents")), 1)
        response = self.admin.post(f"/a-traiter/{request_id}/documents/{photo['id']}/replace", data={"document": photo_file("PNG")}, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 302)
        photos = self.rows("SELECT * FROM request_documents ORDER BY id")
        self.assertEqual([d["is_active"] for d in photos], [0, 1])
        self.assertEqual(photos[1]["review_status"], "pending")
        self.admin.post(f"/a-traiter/{request_id}/documents/{photos[1]['id']}/delete")
        self.assertIn("identity_photo", json.loads(self.rows("SELECT missing_doc_types FROM public_requests")[0][0]))

    def test_photo_remains_behind_admin_authentication(self):
        request_id = self.create_request()
        photo = self.rows("SELECT * FROM request_documents WHERE doc_type = 'identity_photo'")[0]
        url = f"/uploads/{request_id}/{photo['stored_name']}"
        self.assertEqual(self.client.get(url).status_code, 302)
        response = self.admin.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/jpeg")
        response.close()


if __name__ == "__main__":
    unittest.main()
