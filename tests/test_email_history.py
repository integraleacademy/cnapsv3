import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import app as cnaps
from email_history import init_email_history, email_preview


class EmailHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db, self.old_uploads = cnaps.DB_NAME, cnaps.UPLOAD_DIR
        cnaps.DB_NAME = os.path.join(self.tmp.name, 'app.db')
        cnaps.UPLOAD_DIR = os.path.join(self.tmp.name, 'uploads')
        cnaps.app.config['TESTING'] = True
        cnaps.init_db()
        with sqlite3.connect(cnaps.DB_NAME) as conn:
            self.request_id = conn.execute("INSERT INTO public_requests(nom,prenom,email,date_naissance) VALUES ('Test','Mail','recipient@example.com','01/01/1990')").lastrowid
        self.client = cnaps.app.test_client()
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin@example.com'

    def tearDown(self):
        cnaps.DB_NAME, cnaps.UPLOAD_DIR = self.old_db, self.old_uploads
        self.tmp.cleanup()

    def rows(self):
        with sqlite3.connect(cnaps.DB_NAME) as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute('SELECT * FROM request_email_history ORDER BY id').fetchall()

    def archive(self, html='<p>Contenu exact au moment de l’envoi.</p>'):
        with cnaps.app.app_context(), patch.object(cnaps, '_deliver_email_html', return_value='smtp') as send:
            cnaps._send_email_html('recipient@example.com', 'Objet exact', html, request_id=self.request_id, email_kind='non_conformity')
        send.assert_called_once_with('recipient@example.com', 'Objet exact', html)

    def test_exact_copy_is_retained_and_scoped_to_one_dossier(self):
        self.archive()
        saved = self.rows()[0]
        self.assertEqual(saved['recipient'], 'recipient@example.com')
        self.assertEqual(saved['subject'], 'Objet exact')
        self.assertIn('Contenu exact', saved['html_body'])
        self.assertEqual(saved['request_id'], self.request_id)
        page = self.client.get(f'/a-traiter/{self.request_id}/documents').get_data(as_text=True)
        self.assertIn('Historique des mails', page)
        self.assertIn('Objet exact', page)
        self.assertIn('Voir le mail', page)
        self.assertNotIn('Contenu exact', page)  # lazy preview, no mail body in the parent page
        self.assertIn('Contenu exact', self.client.get(f'/a-traiter/{self.request_id}/emails/{saved["id"]}').get_data(as_text=True))
        self.assertEqual(self.client.get(f'/a-traiter/{self.request_id + 1}/emails/{saved["id"]}').status_code, 404)
        self.assertEqual(cnaps.app.test_client().get(f'/a-traiter/{self.request_id}/emails/{saved["id"]}').status_code, 302)

    def test_failed_or_unconfigured_send_is_never_shown_as_sent(self):
        with cnaps.app.app_context(), patch.object(cnaps, '_deliver_email_html', return_value=None):
            cnaps._send_email_html('recipient@example.com', 'No send', '<p>No</p>', request_id=self.request_id)
        with cnaps.app.app_context(), patch.object(cnaps, '_deliver_email_html', side_effect=RuntimeError('provider failed')):
            with self.assertRaises(RuntimeError):
                cnaps._send_email_html('recipient@example.com', 'Failed', '<p>No</p>', request_id=self.request_id)
        self.assertEqual(self.rows(), [])

    def test_mail_copy_survives_business_transaction_rollback_and_does_not_lock(self):
        with cnaps.app.test_request_context(), patch.object(cnaps, '_deliver_email_html', return_value='smtp'):
            conn = sqlite3.connect(cnaps.DB_NAME)
            conn.execute('UPDATE public_requests SET formation=? WHERE id=?', ('TEST', self.request_id))
            cnaps._send_email_html('recipient@example.com', 'Accepted', '<p>Sent before SMS error</p>', request_id=self.request_id)
            conn.rollback()
            conn.close()
            cnaps.app.process_response(cnaps.make_response('SMS failed', 500))
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]['subject'], 'Accepted')

    def test_preview_is_read_only_and_not_cached(self):
        html = '<p onclick="bad()">Hello</p><script>alert(1)</script><meta http-equiv="refresh" content="0;url=/delete"><a href="/espace-cnaps/validation/test">Valider</a><form action="/send"><button>Envoyer</button></form>'
        self.archive(html)
        saved = self.rows()[0]
        self.assertEqual(saved['html_body'], html)  # original copy stays intact
        response = self.client.get(f'/a-traiter/{self.request_id}/emails/{saved["id"]}')
        body = response.get_data(as_text=True)
        for forbidden in ('onclick', '<script', '<meta', '<form', 'href=', 'alert(1)'):
            self.assertNotIn(forbidden, body)
        self.assertIn('Valider', body)
        self.assertIn('sandbox', response.headers['Content-Security-Policy'])
        self.assertIn('no-store', response.headers['Cache-Control'])

    def test_smtp_and_brevo_transport_success_return_confirmed_provider(self):
        smtp = MagicMock()
        smtp.return_value.__enter__.return_value.send_message.return_value = {}
        with patch.multiple(cnaps, SMTP_HOST='smtp.example.com', SMTP_USER='test', SMTP_PASSWORD='not-real'), patch.object(cnaps.smtplib, 'SMTP', smtp):
            self.assertEqual(cnaps._deliver_email_html('recipient@example.com', 'Subject', '<p>Body</p>'), 'smtp')
        with patch.multiple(cnaps, SMTP_HOST='', BREVO_API_KEY='not-real', BREVO_SENDER_EMAIL='sender@example.com'), patch.object(cnaps.urllib_request, 'urlopen') as send:
            self.assertEqual(cnaps._deliver_email_html('recipient@example.com', 'Subject', '<p>Body</p>'), 'brevo')
            self.assertEqual(send.call_count, 1)

    def test_legacy_import_is_once_and_does_not_invent_bodies_or_recipients(self):
        with sqlite3.connect(':memory:') as conn:
            conn.executescript("""CREATE TABLE public_requests(id INTEGER, email TEXT, cnaps_reminder_4h_sent_at TEXT, cnaps_reminder_2h_sent_at TEXT);
                CREATE TABLE request_non_conformity_notifications(id INTEGER, request_id INTEGER, sent_at TEXT);
                INSERT INTO public_requests VALUES (189, 'current@example.com', '2026-09-30 10:00:00', NULL);
                INSERT INTO request_non_conformity_notifications VALUES (1, 189, '2026-09-29 09:00:00');""")
            init_email_history(conn)
            rows = conn.execute('SELECT recipient, html_body FROM request_email_history').fetchall()
            self.assertEqual(rows, [(None, None), (None, None)])
            conn.execute("INSERT INTO request_non_conformity_notifications VALUES (2,189,'2026-10-01 10:00:00')")
            init_email_history(conn)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM request_email_history').fetchone()[0], 2)

    def test_actual_notification_flow_archives_email_even_if_sms_fails(self):
        with sqlite3.connect(cnaps.DB_NAME) as conn:
            conn.execute('CREATE TABLE dossiers(id INTEGER PRIMARY KEY, telephone TEXT)')
            conn.execute("""INSERT INTO request_documents
                (request_id,doc_type,original_name,stored_name,storage_path,review_status,non_conformite_reason)
                VALUES (?,'identity','test.pdf','test.pdf','test.pdf','non_conforme','Verso manquant')""", (self.request_id,))
        with patch.object(cnaps, '_deliver_email_html', return_value='smtp') as send, \
                patch.object(cnaps, '_send_sms', side_effect=RuntimeError('SMS failed')), \
                patch.object(cnaps.app.logger, 'exception'):
            response = self.client.post(f'/a-traiter/{self.request_id}/notify')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]['email_kind'], 'non_conformity')
        self.assertIn('Verso manquant', self.rows()[0]['html_body'])


if __name__ == '__main__':
    unittest.main()
