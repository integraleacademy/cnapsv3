"""Private copies of accepted outgoing mail, independent of later SMS failures."""
from datetime import datetime
from html import escape
from html.parser import HTMLParser
import sqlite3
from zoneinfo import ZoneInfo

from flask import current_app, g, has_request_context


def init_email_history(conn):
    existed = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='request_email_history'").fetchone()
    conn.execute("""CREATE TABLE IF NOT EXISTS request_email_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, request_id INTEGER NOT NULL,
        email_kind TEXT NOT NULL, recipient TEXT, sender TEXT, subject TEXT NOT NULL,
        html_body TEXT, sent_at TEXT NOT NULL, provider TEXT, legacy_key TEXT UNIQUE,
        FOREIGN KEY (request_id) REFERENCES public_requests(id) ON DELETE CASCADE
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS request_email_history_request ON request_email_history(request_id, sent_at)")
    if existed:
        return
    # Import only real historical traces, never infer a send from a dossier's
    # creation/status. Bodies and historic recipient addresses were not stored.
    conn.execute("""INSERT OR IGNORE INTO request_email_history
        (request_id, email_kind, subject, sent_at, legacy_key)
        SELECT request_id, 'non_conformity', 'Notification de documents à corriger', sent_at, 'notification:' || id
        FROM request_non_conformity_notifications""")
    for kind, column, label in [
        ('reminder_4h', 'cnaps_reminder_4h_sent_at', 'Rappel de validation CNAPS · 4 h'),
        ('reminder_2h', 'cnaps_reminder_2h_sent_at', 'Rappel urgent de validation CNAPS · 2 h'),
    ]:
        conn.execute(f"""INSERT OR IGNORE INTO request_email_history
            (request_id, email_kind, subject, sent_at, legacy_key)
            SELECT id, ?, ?, {column}, ? || id FROM public_requests
            WHERE {column} IS NOT NULL AND TRIM({column}) != '' AND TRIM(email) != ''""", (kind, label, kind + ':'))


def _persist(db_path, entries):
    with sqlite3.connect(db_path) as conn:
        conn.executemany("""INSERT INTO request_email_history
            (request_id, email_kind, recipient, sender, subject, html_body, sent_at, provider)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", entries)


def archive_sent_email(db_path, request_id, kind, recipient, sender, subject, html, provider):
    if not request_id:
        return
    entry = (request_id, kind, recipient, sender, subject, html,
             datetime.now(ZoneInfo('Europe/Paris')).strftime('%Y-%m-%d %H:%M:%S'), provider)
    if has_request_context():
        g.setdefault('sent_email_copies', []).append(entry)
    else:
        _persist(db_path, [entry])


def register_email_history(app, db_path):
    @app.after_request
    def save_sent_mail_copies(response):
        entries = g.pop('sent_email_copies', [])
        if entries:
            # The business transaction is now closed: no nested SQLite writer,
            # and an SMS failure cannot roll back the copy of an accepted mail.
            try:
                _persist(db_path(), entries)
            except sqlite3.Error as error:
                current_app.logger.error('email_archive_failed reason=%s', type(error).__name__)
        return response


class _ReadOnlyEmail(HTMLParser):
    blocked = {'script', 'iframe', 'object', 'embed', 'form', 'input', 'button',
               'textarea', 'select', 'meta', 'base', 'link', 'video', 'audio', 'source'}
    void = {'input', 'embed', 'meta', 'base', 'link', 'source'}

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.output = []
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.blocked:
            if tag not in self.void:
                self.depth += 1
            return
        if self.depth:
            return
        attrs = [(k, v) for k, v in attrs if not k.startswith('on') and k not in
                 {'href', 'target', 'action', 'formaction', 'srcdoc', 'autofocus', 'contenteditable'}]
        self.output.append('<' + tag + ''.join(' ' + k + '="' + escape(v or '', quote=True) + '"' for k, v in attrs) + '>')

    def handle_endtag(self, tag):
        if tag in self.blocked:
            if tag not in self.void and self.depth:
                self.depth -= 1
        elif not self.depth:
            self.output.append('</' + tag + '>')

    def handle_data(self, text):
        if not self.depth:
            self.output.append(text)

    def handle_entityref(self, name):
        self.handle_data('&' + name + ';')

    def handle_charref(self, name):
        self.handle_data('&#' + name + ';')


def email_preview(html):
    parser = _ReadOnlyEmail()
    parser.feed(html)
    return '<!doctype html>' + ''.join(parser.output)
