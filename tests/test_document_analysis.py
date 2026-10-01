import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import io
import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask
from PIL import Image
import pypdfium2 as pdfium
import document_analysis as checks


def model_result(**changes):
    result = {
        "document_type": "identity", "confidence": "high", "document_date": None,
        "date_kind": "uncertain", "date_confidence": "low", "readability": "clear",
        "all_fields_legible": True, "problems": [],
        "photo_criteria": {key: "not_applicable" for key in checks.PHOTO_CRITERIA},
        "signature": "not_applicable", "signature_confidence": "low",
        "address_kind": "water", "address_kind_confidence": "high",
        "identity_document": "identity_card", "identity_sides": ["front"], "side_confidence": "high",
        "identity_checks": {key: "pass" for key in checks.IDENTITY_CHECKS},
    }
    result.update(changes)
    return result


def blank_pdf(pages=1):
    stream = io.BytesIO()
    with pdfium.PdfDocument.new() as pdf:
        for _ in range(pages):
            pdf.new_page(595, 842).close()
        pdf.save(stream)
    return stream.getvalue()


class AdvisoryTests(unittest.TestCase):
    def test_only_accepted_address_types_can_be_green_and_date_still_matters(self):
        for kind in checks.ADDRESS_KINDS:
            fields = model_result(document_type="address", address_kind=kind, document_date="2026-09-30", date_kind="invoice", date_confidence="high")
            answer = checks.advisory(fields, "proof_address", date(2026, 10, 1))
            expected = "success" if kind in checks.ACCEPTED_ADDRESS_KINDS else "unknown" if kind == "uncertain" else "warning"
            self.assertEqual(answer["status"], expected, kind)
            if expected == "success":
                fields["document_date"] = "2026-07-01"
                self.assertEqual(checks.advisory(fields, "proof_address", date(2026, 10, 1))["status"], "warning")
        fields = model_result(document_type="address", address_kind="landline", address_kind_confidence="low", document_date="2026-09-30", date_kind="invoice", date_confidence="high")
        self.assertEqual(checks.advisory(fields, "proof_address", date(2026, 10, 1))["status"], "unknown")

    def test_every_quality_criterion_can_veto_otherwise_readable_identity(self):
        for key in checks.IDENTITY_CHECKS:
            for value, expected in [("fail", "warning"), ("uncertain", "unknown"), ("not_applicable", "unknown")]:
                fields = model_result(identity_checks={criterion: value if criterion == key else "pass" for criterion in checks.IDENTITY_CHECKS})
                self.assertEqual(checks.advisory(fields, "identity", date.today())["status"], expected, (key, value))

    def test_identity_evidence_combines_pdf_pages_without_extracting_identity_values(self):
        front = model_result(identity_sides=["front"])
        back = model_result(identity_sides=["back"])
        with patch.object(checks, "call_openai", side_effect=[front, back]):
            result = checks.analyze_images(["recto", "verso"], "identity", "test-key", date.today())
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["identity_evidence"], [
                {"type": "identity_card", "sides": ["front"], "confidence": "high"},
                {"type": "identity_card", "sides": ["back"], "confidence": "high"}])
        with patch.object(checks, "call_openai", return_value=model_result(identity_document="passport", identity_sides=["passport_biodata"])):
            result = checks.analyze_images(["passport"], "host_identity", "test-key", date.today())
            self.assertNotIn("recto", result["message"])
            self.assertEqual(result["identity_evidence"][0]["type"], "passport")

    def test_detail_views_keep_full_page_and_original_pixels_with_overlap(self):
        image = Image.new("RGB", (1000, 1400), (50, 100, 150))
        stream = io.BytesIO(); image.save(stream, format="JPEG")
        encoded = base64.b64encode(stream.getvalue()).decode("ascii")
        views = checks.identity_views(encoded)
        self.assertEqual(views[0], encoded)
        self.assertEqual(len(views), 5)
        for detail in views[1:]:
            with Image.open(io.BytesIO(base64.b64decode(detail))) as cropped:
                self.assertEqual(cropped.size, (600, 840))
                self.assertLess(abs(cropped.getpixel((100, 100))[1] - 100), 3)

    def test_engie_attestation_date_is_compared_as_document_date(self):
        result = model_result(document_type="address", document_date="2026-09-30",
                              date_kind="attestation", date_confidence="high")
        answer = checks.advisory(result, "proof_address", date(2026, 10, 1))
        self.assertEqual(answer["status"], "success")
        self.assertIn("30/09/2026", answer["message"])

    def test_identity_details_focus_on_scan_instead_of_white_margins(self):
        image = Image.new("RGB", (1000, 1400), "white")
        image.paste((80, 100, 120), (0, 350, 1000, 1050))
        image.paste((80, 80, 80), (800, 1330, 950, 1360))
        top, bottom = checks.identity_detail_band(image)
        self.assertLessEqual(top, 350)
        self.assertGreaterEqual(bottom, 1050)
        self.assertGreater(top, 280)
        self.assertLess(bottom, 1120)
        stream = io.BytesIO(); image.save(stream, format="JPEG")
        encoded = base64.b64encode(stream.getvalue()).decode("ascii")
        views = checks.identity_views(encoded)
        self.assertEqual(views[0], encoded, "the whole page remains available for framing and other content")
        with Image.open(io.BytesIO(base64.b64decode(views[1]))) as detail:
            self.assertEqual(detail.width, 600)
            self.assertLess(detail.height, 600)
        two_faces = Image.new("RGB", (1000, 1400), "white")
        two_faces.paste((80, 100, 120), (0, 100, 1000, 450))
        two_faces.paste((80, 100, 120), (0, 750, 1000, 1100))
        self.assertEqual(checks.identity_detail_band(two_faces), (0, 1400))

    def test_calendar_boundary_old_recent_and_future_dates(self):
        self.assertEqual(checks.three_months_before(date(2024, 5, 31)), date(2024, 2, 29))
        self.assertEqual(checks.three_months_before(date(2026, 5, 31)), date(2026, 2, 28))
        for issued, expected in [("2026-06-30", "warning"), ("2026-07-01", "warning"),
                                 ("2026-07-02", "success"), ("2026-10-02", "unknown")]:
            with self.subTest(issued=issued):
                result = model_result(document_type="address", document_date=issued,
                                      date_kind="invoice", date_confidence="high")
                self.assertEqual(checks.advisory(result, "proof_address", date(2026, 10, 1))["status"], expected)

    def test_uncertain_or_invalid_dates_never_get_a_positive_result(self):
        for fields in [{"document_date": None}, {"document_date": "2026-02-31"},
                       {"date_confidence": "medium"}, {"date_kind": "uncertain"}]:
            result = model_result(document_type="address", document_date="2026-09-30",
                                  date_kind="attestation", date_confidence="high")
            result.update(fields)
            self.assertEqual(checks.advisory(result, "proof_address", date(2026, 10, 1)), checks.unavailable("proof_address"))

    def test_even_slight_blur_is_flagged_despite_some_readable_text(self):
        for fields in [{"readability": "slightly_blurred"}, {"problems": ["blur"]},
                       {"all_fields_legible": False}, {"problems": ["cropped"]},
                       {"confidence": "medium", "problems": ["small_text"]}]:
            result = model_result(**fields)
            self.assertEqual(checks.advisory(result, "identity", date.today())["status"], "warning")

    def test_clear_result_is_cautious_and_unknown_never_means_validated(self):
        answer = checks.advisory(model_result(), "host_identity", date.today())
        self.assertEqual(answer["status"], "success")
        self.assertNotIn("recto", answer["message"])
        self.assertIn("personne qui vous héberge", answer["message"])
        for fields in [{"readability": "uncertain"}, {"confidence": "medium"}, {"document_type": "other"}]:
            self.assertEqual(checks.advisory(model_result(**fields), "identity", date.today())["status"], "unknown")

    def test_identity_warning_names_the_observed_problem_without_inventing_blur(self):
        answer = checks.advisory(model_result(problems=["glare"]), "identity", date.today())
        self.assertIn("un reflet semble gêner la lecture", answer["message"])
        self.assertNotIn("semblent flous", answer["message"])
        with patch.object(checks, "call_openai", side_effect=[model_result(), model_result(problems=["cropped"])]):
            answer = checks.analyze_images(["front", "back"], "identity", "test-key", date.today())
        self.assertTrue(answer["message"].startswith("Page 2 : "))
        self.assertIn("une zone utile semble coupée", answer["message"])

    def test_unreadable_candidate_and_host_ids_warn_of_rejection(self):
        for kind in ["identity", "host_identity"]:
            answer = checks.advisory(model_result(problems=["blur"]), kind, date.today())
            self.assertEqual(answer["status"], "warning")
            self.assertIn("sera rejetée", answer["critical"])
            if kind == "host_identity":
                self.assertIn("personne qui vous héberge", answer["message"])

    def test_photo_requires_every_visible_criterion_and_high_confidence(self):
        criteria = {key: "pass" for key in checks.PHOTO_CRITERIA}
        valid = model_result(document_type="portrait", photo_criteria=criteria, all_fields_legible=False)
        result = checks.advisory(valid, "identity_photo", date.today())
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["title"], "Photo : c’est bon !")
        self.assertEqual(result["message"], "")
        for key in criteria:
            for value, status in [("fail", "warning"), ("uncertain", "unknown"), ("not_applicable", "unknown")]:
                changed = dict(valid, photo_criteria={**criteria, key: value})
                answer = checks.advisory(changed, "identity_photo", date.today())
                self.assertEqual(answer["status"], status, (key, value))
                if status == "warning":
                    self.assertIn(checks.PHOTO_CRITERIA[key], answer["message"])
                    self.assertIn("rejet", answer["critical"])
        self.assertEqual(checks.advisory(dict(valid, confidence="medium"), "identity_photo", date.today())["status"], "unknown")
        self.assertEqual(checks.advisory(model_result(), "identity_photo", date.today())["status"], "warning")

    def test_signature_detection_never_certifies_authenticity_or_an_uncertain_signature(self):
        base = model_result(document_type="hosting_certificate", signature_confidence="high")
        for signature, status in [("present", "success"), ("absent", "warning"), ("uncertain", "unknown"), ("not_applicable", "unknown")]:
            answer = checks.advisory(dict(base, signature=signature), "hosting_certificate", date.today())
            self.assertEqual(answer["status"], status)
            if status == "success":
                self.assertIn("ne certifie pas son authenticité", answer["message"])
        for changes in [{"signature_confidence": "medium"}, {"confidence": "medium"}, {"document_type": "address"}]:
            self.assertEqual(checks.advisory(dict(base, signature="present", **changes), "hosting_certificate", date.today())["status"], "unknown")

    def test_photo_decoder_uses_pixels_and_rejects_non_images_and_animation(self):
        for fmt in ["JPEG", "PNG"]:
            stream = io.BytesIO()
            Image.new("RGB", (300, 400), "gray").save(stream, format=fmt)
            rendered = checks.render_photo(stream.getvalue())
            with Image.open(io.BytesIO(base64.b64decode(rendered[0]))) as image:
                self.assertEqual(image.format, "JPEG")
                self.assertEqual(image.size, (300, 400))
        for data in [b"not an image", blank_pdf()]:
            with self.assertRaises(Exception):
                checks.render_photo(data)
        stream = io.BytesIO()
        Image.new("RGB", (30, 40), "red").save(stream, format="PNG", save_all=True,
            append_images=[Image.new("RGB", (30, 40), "blue")], duration=100)
        with self.assertRaises(ValueError):
            checks.render_photo(stream.getvalue())

    def test_schema_requires_all_photo_and_signature_fields(self):
        result = model_result()
        del result["photo_criteria"]["eyes_visible"]
        with self.assertRaises(ValueError):
            checks.check_schema(result)
        with self.assertRaises(ValueError):
            checks.check_schema(model_result(signature="verified_authentic"))

    def test_each_identity_page_is_analyzed_separately_and_worst_result_wins(self):
        for kind in ["identity", "host_identity"]:
            with patch.object(checks, "call_openai", side_effect=[model_result(), model_result(problems=["blur"])]) as provider:
                answer = checks.analyze_images(["clear-page", "blurry-page"], kind, "test-key", date.today())
                self.assertEqual(answer["status"], "warning")
                self.assertEqual([call.args[0] for call in provider.call_args_list], [["clear-page"], ["blurry-page"]])
                self.assertGreater(provider.call_args_list[0].kwargs["timeout"], provider.call_args_list[1].kwargs["timeout"])
                self.assertLessEqual(provider.call_args_list[0].kwargs["timeout"], 25)
            with patch.object(checks, "call_openai", side_effect=[model_result(), model_result(confidence="low")]):
                self.assertEqual(checks.analyze_images(["one", "two"], kind, "test-key", date.today())["status"], "unknown")
        with patch.object(checks, "call_openai", return_value=model_result(problems=["blur"])) as provider:
            self.assertEqual(checks.analyze_images(["bad", "second"], "identity", "test-key", date.today())["status"], "warning")
            self.assertEqual(provider.call_count, 1, "stop spending calls once the file needs replacement")

    def test_page_analysis_has_one_overall_time_budget(self):
        with patch.object(checks.time, "monotonic", side_effect=[100, 100, 126]), patch.object(checks, "call_openai", return_value=model_result()) as provider:
            self.assertEqual(checks.analyze_images(["one", "two"], "identity", "test-key", date.today())["status"], "unknown")
            self.assertEqual(provider.call_count, 1)

    def test_only_visible_pdf_pages_are_rendered_and_oversized_documents_are_refused(self):
        images = checks.render_pages(blank_pdf())
        self.assertEqual(len(images), 1)
        with Image.open(io.BytesIO(base64.b64decode(images[0]))) as image:
            self.assertLessEqual(max(image.size), 2401)
            self.assertEqual(image.getpixel((100, 100)), (255, 255, 255))
        with self.assertRaises(ValueError):
            checks.render_pages(blank_pdf(checks.MAX_PAGES + 1))
        with self.assertRaises(ValueError):
            checks.render_pages(b"not a PDF")

    def test_openai_request_uses_images_strict_schema_and_no_response_storage(self):
        response = {"status": "completed", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": json.dumps(model_result())}]}]}
        with patch.object(checks, "urlopen", return_value=io.BytesIO(json.dumps(response).encode())) as call:
            self.assertEqual(checks.call_openai(checks.render_pages(blank_pdf()), "identity", "test-key-not-real"), model_result())
        request = call.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.openai.com/v1/responses")
        payload = json.loads(request.data)
        self.assertIs(payload["store"], False)
        self.assertTrue(payload["text"]["format"]["strict"])
        self.assertEqual(payload["input"][0]["content"][1]["type"], "input_image")
        self.assertEqual(payload["input"][0]["content"][1]["detail"], "high")
        self.assertEqual(len([part for part in payload["input"][0]["content"] if part["type"] == "input_image"]), 5)
        self.assertEqual(call.call_args.kwargs["timeout"], 25)

    def test_provider_refusal_and_incomplete_response_are_not_successes(self):
        for response in [{"status": "incomplete"}, {"status": "completed", "output": [
                {"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}]}]:
            with patch.object(checks, "urlopen", return_value=io.BytesIO(json.dumps(response).encode())):
                with self.assertRaises(ValueError):
                    checks.call_openai(["image"], "proof_address", "test-key-not-real")


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "usage.db")
        self.app = Flask(__name__)
        self.app.secret_key = "test-only"
        self.app.testing = True
        checks.register_document_analysis(self.app, lambda: self.db)
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["document_analysis_token"] = "test-session-token"
        self.env = patch.dict(os.environ, {"OPENAI_API_KEY": "test-key-not-real"}).start()
        self.render = patch.object(checks, "render_pages", return_value=["image"]).start()
        self.provider = patch.object(checks, "call_openai", return_value=model_result()).start()
        with checks._cache_lock:
            checks._cache.clear()

    def tearDown(self):
        patch.stopall()
        self.tmp.cleanup()

    def submit(self, kind="identity", headers=None, data=b"%PDF-1.4 specimen", filename="document.pdf"):
        return self.client.post("/api/document-analysis", data={
            "kind": kind, "document": (io.BytesIO(data), filename)},
            headers=headers if headers is not None else {"X-Document-Check-Token": "test-session-token"},
            content_type="multipart/form-data")

    def test_no_token_or_cross_site_requests_cannot_spend_api_calls(self):
        for headers in [{}, {"X-Document-Check-Token": "wrong"},
                        {"X-Document-Check-Token": "test-session-token", "Origin": "https://external.example"}]:
            self.assertEqual(self.submit(headers=headers).status_code, 403)
        self.provider.assert_not_called()

    def test_missing_key_and_api_errors_return_specific_non_blocking_message(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            response = self.submit("proof_address")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json, checks.unavailable("proof_address"))
        self.provider.assert_not_called()
        self.provider.side_effect = TimeoutError()
        response = self.submit("host_identity")
        self.assertEqual(response.json, checks.unavailable("host_identity"))

    def test_results_are_cached_without_storing_documents_or_changing_dossiers(self):
        first = self.submit()
        second = self.submit()
        self.assertEqual(first.json, second.json)
        self.assertEqual(first.headers["Cache-Control"], "no-store")
        self.assertEqual(self.provider.call_count, 1)
        self.assertEqual(os.listdir(self.tmp.name), ["usage.db"])
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [("document_analysis_usage",)])

    def test_size_kind_and_budget_limits_prevent_api_calls(self):
        self.assertEqual(self.submit("unsupported_kind").status_code, 400)
        self.assertEqual(self.submit(data=b"x" * (checks.MAX_BYTES + 1)).status_code, 413)
        with patch.object(checks, "reserve_usage", return_value=False):
            self.assertEqual(self.submit().status_code, 429)
        self.provider.assert_not_called()

    def test_photo_signature_and_host_identity_reach_their_specific_analysis(self):
        stream = io.BytesIO()
        Image.new("RGB", (30, 40), "gray").save(stream, format="PNG")
        self.provider.return_value = model_result(document_type="portrait", photo_criteria={key: "pass" for key in checks.PHOTO_CRITERIA})
        photo = self.submit("identity_photo", data=stream.getvalue(), filename="photo.png")
        self.assertEqual(photo.status_code, 200)
        self.assertEqual(photo.json["status"], "success")
        self.assertEqual(self.provider.call_args.args[1], "identity_photo")
        self.render.assert_not_called()
        self.provider.return_value = model_result(document_type="hosting_certificate", signature="absent", signature_confidence="high")
        self.assertEqual(self.submit("hosting_certificate").json["status"], "warning")
        self.assertEqual(self.provider.call_args.args[1], "hosting_certificate")
        self.provider.return_value = model_result(problems=["blur"])
        self.assertIn("personne qui vous héberge", self.submit("host_identity").json["message"])
        calls = self.provider.call_count
        self.assertEqual(self.submit("identity_photo").status_code, 400)
        self.assertEqual(self.submit("identity", filename="photo.png").status_code, 400)
        self.assertEqual(calls, self.provider.call_count)

    def test_rate_counter_is_atomic_across_concurrent_requests(self):
        # Initialise the table before simultaneous reservations.
        checks.reserve_usage(self.db, "one-session", 100000)
        with ThreadPoolExecutor(max_workers=4) as pool:
            accepted = list(pool.map(lambda _: checks.reserve_usage(self.db, "one-session", 100000), range(35)))
        self.assertEqual(sum(accepted), 29)

    def test_multipage_identity_reserves_provider_calls_for_all_pages(self):
        self.render.return_value = ["one", "two", "three"]
        self.assertEqual(self.submit().json["status"], "success")
        self.assertEqual(self.provider.call_count, 3)
        with sqlite3.connect(self.db) as conn:
            self.assertEqual({row[0] for row in conn.execute("SELECT used FROM document_analysis_usage")}, {3})
        self.assertTrue(checks.reserve_usage(self.db, "another-session", 100000, units=28))
        self.assertFalse(checks.reserve_usage(self.db, "another-session", 100000, units=3))
        self.assertTrue(checks.reserve_usage(self.db, "another-session", 100000, units=2))


if __name__ == "__main__":
    unittest.main()
