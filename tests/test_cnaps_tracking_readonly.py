"""Authenticated targeted reads must not send reminders or mutate the source."""
import hmac
import json
import sqlite3

from flask import Flask
import pytest

from cnaps_tracking_api import TRACKING_FIELDS, register_cnaps_tracking_api


@pytest.fixture
def tracking(tmp_path):
    path = tmp_path / "cnaps.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE tracking (payload TEXT)")
    app = Flask(__name__)
    app.config["TESTING"] = True
    calls = []

    def loader(conn):
        calls.append("read")
        return [json.loads(row[0]) for row in conn.execute("SELECT payload FROM tracking")]

    register_cnaps_tracking_api(
        app, db_path=lambda: path,
        token_is_valid=lambda token: hmac.compare_digest(token, "server-token"),
        dataset_loader=loader,
    )

    def insert(**values):
        row = dict(id=1, dossier_id=11, nom="Dùpont", prenom="Jean-Pierre",
                   email="jean@example.test", date_naissance="2000-02-03",
                   statut_cnaps="TRANSMIS", nub="NUB : 012 3456", formation="APS",
                   session_date="2027-01-04", espace_cnaps="Validé",
                   created_at="2026-11-13T08:00:00", updated_at="2026-11-13T09:00:00",
                   dracar_password="private-password", espace_cnaps_validation_token="private-token",
                   telephone="private-phone", document_path="private-file")
        row.update(values)
        with sqlite3.connect(path) as conn:
            conn.execute("INSERT INTO tracking VALUES (?)", (json.dumps(row),))

    return app.test_client(), path, calls, insert


HEADERS = {"Authorization": "Bearer server-token"}
IDENTITY = {"nom": "Du'pont", "prenom": "jean pierre"}


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": "Bearer café"}, {"X-API-Key": "server-token"}])
def test_requires_api_token_before_reading_any_identity(tracking, headers):
    client, _, calls, _ = tracking
    response = client.get("/api/cnaps-tracking", query_string=IDENTITY, headers=headers)
    assert response.status_code == 401
    assert response.json == {"success": False, "error": "UNAUTHORIZED"}
    assert not calls
    assert response.headers["Cache-Control"] == "private, no-store"


@pytest.mark.parametrize("identity", [{}, {"nom": "Dupont"}, {"prenom": "Jean"},
                                      {"nom": "-", "prenom": "Jean"},
                                      {"nom": "D" * 201, "prenom": "Jean"}])
def test_requires_both_bounded_names(tracking, identity):
    client, _, calls, _ = tracking
    response = client.get("/api/cnaps-tracking", query_string=identity, headers=HEADERS)
    assert response.status_code == 400
    assert not calls


def test_returns_only_exact_identity_and_allowlisted_tracking_fields(tracking):
    client, path, calls, insert = tracking
    insert()
    insert(id=2, prenom="Jean")
    insert(id=3, nom="Autre")
    insert(id=4, prenom="")
    before = path.read_bytes()
    response = client.get("/api/cnaps-tracking", query_string=IDENTITY, headers=HEADERS)
    assert response.status_code == 200
    assert response.json["success"] is True
    row, = response.json["requests"]
    assert row["id"] == 1 and row["statut_cnaps"] == "TRANSMIS"
    assert row["nub"] == "0123456"
    assert row["email"] == "jean@example.test" and row["date_naissance"] == "2000-02-03"
    assert set(row) == set(TRACKING_FIELDS)
    assert "private-" not in response.text
    assert calls == ["read"]
    assert path.read_bytes() == before


def test_does_not_choose_arbitrarily_among_homonyms(tracking):
    client, _, _, insert = tracking
    insert()
    insert(id=2, email="other@example.test", date_naissance="1999-02-03", nub="7654321")
    response = client.get("/api/cnaps-tracking", query_string=IDENTITY, headers=HEADERS)
    assert response.status_code == 200
    assert len(response.json["requests"]) == 2


def test_empty_result_is_distinct_from_unavailable_source(tracking):
    client, path, _, _ = tracking
    response = client.get("/api/cnaps-tracking", query_string=IDENTITY, headers=HEADERS)
    assert response.json == {"success": True, "requests": []}
    path.unlink()
    unavailable = client.get("/api/cnaps-tracking", query_string=IDENTITY, headers=HEADERS)
    assert unavailable.status_code == 503
    assert not path.exists()
    assert "requests" not in unavailable.json


@pytest.mark.parametrize("comment", ["Dossier reçu via formulaire public", "Téléphone 0612345678", "123456789", "NUB inconnu"])
def test_legacy_free_text_comments_are_not_exposed_as_nub(tracking, comment):
    client, _, _, insert = tracking
    insert(nub=comment)
    response = client.get("/api/cnaps-tracking", query_string=IDENTITY, headers=HEADERS)
    assert response.json["requests"][0]["nub"] == ""
    assert comment not in response.text


def test_source_connection_refuses_mutation_even_if_loader_regresses(tmp_path):
    path = tmp_path / "readonly.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE marker (value TEXT)")
        conn.execute("INSERT INTO marker VALUES ('unchanged')")
    app = Flask(__name__)
    app.config["TESTING"] = True

    def mutating_loader(conn):
        conn.execute("UPDATE marker SET value='changed'")
        return []

    register_cnaps_tracking_api(app, db_path=lambda: path,
                                token_is_valid=lambda token: token == "server-token",
                                dataset_loader=mutating_loader)
    response = app.test_client().get("/api/cnaps-tracking", query_string=IDENTITY, headers=HEADERS)
    assert response.status_code == 503
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT value FROM marker").fetchone()[0] == "unchanged"


def test_post_is_not_a_supported_operation(tracking):
    client, _, calls, _ = tracking
    assert client.post("/api/cnaps-tracking", json=IDENTITY, headers=HEADERS).status_code == 405
    assert not calls
