"""Targeted CNAPS tracking reads without reminder or notification side effects."""

from contextlib import closing
from datetime import date, datetime
from pathlib import Path
import re
import sqlite3
import unicodedata

from flask import Blueprint, jsonify, request


TRACKING_FIELDS = (
    "id", "dossier_id", "nom", "prenom", "email", "date_naissance",
    "formation", "session_date", "espace_cnaps", "created_at", "updated_at",
    "statut_cnaps", "nub",
)


def normalized_name(value):
    value = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return "".join(char for char in value if char.isalnum())


def tracking_record(row):
    """Expose only tracking and matching fields, never account or document data."""
    result = {}
    for field in TRACKING_FIELDS:
        value = row.get(field)
        if isinstance(value, (date, datetime)):
            value = value.isoformat()
        elif value is not None and not isinstance(value, (str, int, float, bool)):
            value = None
        if isinstance(value, str):
            value = value.strip()[:512]
        result[field] = value

    # The legacy database stores the NUB in dossiers.commentaire. Do not expose
    # arbitrary comments (e.g. "Dossier reçu via formulaire public") as a NUB.
    match = re.fullmatch(
        r"(?:NUB\s*[:=-]?\s*)?(\d(?:[\s-]*\d){6})",
        str(row.get("nub") or "").strip(), re.IGNORECASE,
    )
    result["nub"] = re.sub(r"\D", "", match.group(1)) if match else ""
    return result


def register_cnaps_tracking_api(app, *, db_path, token_is_valid, dataset_loader):
    """Reuse the tracking source through a read-only SQLite connection.

    Both identity fields are mandatory. Ambiguous matches remain separate so the
    calling integration can disambiguate using the candidate's birth date/email.
    Unlike /api/a-traiter, this route never runs CNAPS reminders.
    """
    bp = Blueprint("cnaps_tracking_readonly", __name__)

    @bp.get("/api/cnaps-tracking")
    def tracking():
        authorization = str(request.headers.get("Authorization") or "").strip()
        token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
        if not token_is_valid(token):
            return jsonify(success=False, error="UNAUTHORIZED"), 401

        last_name = str(request.args.get("nom") or "").strip()
        first_name = str(request.args.get("prenom") or "").strip()
        if any(not value or len(value) > 200 or not normalized_name(value)
               for value in (last_name, first_name)):
            return jsonify(success=False, error="IDENTITY_REQUIRED"), 400

        expected = (normalized_name(last_name), normalized_name(first_name))
        try:
            # mode=ro prevents writes and prevents creating a missing database.
            # query_only also protects the connection if the loader later changes.
            uri = Path(db_path()).resolve().as_uri() + "?mode=ro"
            with closing(sqlite3.connect(uri, uri=True, timeout=5)) as conn:
                conn.execute("PRAGMA query_only=ON")
                rows = dataset_loader(conn)
                matches = [
                    tracking_record(row) for row in rows
                    if (normalized_name(row.get("nom")), normalized_name(row.get("prenom"))) == expected
                ]
        except (OSError, sqlite3.Error, ValueError, TypeError):
            # Do not log the query, applicant identity, credentials or database rows.
            app.logger.warning("Read-only CNAPS tracking unavailable")
            return jsonify(success=False, error="TRACKING_UNAVAILABLE"), 503
        return jsonify(success=True, requests=matches)

    @bp.after_request
    def private(response):
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response

    app.register_blueprint(bp)
