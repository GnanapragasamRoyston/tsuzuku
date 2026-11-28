"""Power BI (phase 13, ADR 016) : vues de l'activité des comptes (schéma bi, migration 0004) et
rôle lecture seule.

Règle d'anonymat : aucune ligne n'est calculée sur moins de k comptes (settings.yaml,
powerbi.min_group_size). Aucune vue bi n'expose d'identifiant de compte, d'email ou de pseudo.
"""

import datetime as dt

import psycopg
import pytest
import yaml
from psycopg import errors
from sqlalchemy.engine import make_url

from app import bi_role, migrate
from app.core.config import REPO_ROOT

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_users")]

SETTINGS = yaml.safe_load((REPO_ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))
K = SETTINGS["powerbi"]["min_group_size"]
TEST_ROLE = "tsuzuku_bi_test"  # jamais le vrai rôle : son mot de passe n'est pas touché
TEST_PASSWORD = "mot-de-passe-de-test-bi-0123456789"  # noqa: S105


def _accounts(conn, n, prefix="u", created_at=None):
    ids = []
    for i in range(n):
        ids.append(conn.execute(
            "INSERT INTO app.users (email, pseudo, password_hash, created_at)"
            " VALUES (%s, %s, 'x', COALESCE(%s, now())) RETURNING id",
            (f"{prefix}{i}@example.com", f"{prefix}{i:03d}", created_at),
        ).fetchone()[0])  # fmt: skip
    return ids


def _entries(conn, users, media_id, status="in_progress", progress=3, dropped_at=None):
    for uid in users:
        conn.execute(
            "INSERT INTO app.list_entry (user_id, media_id, status, progress, dropped_at)"
            " VALUES (%s, %s, %s, %s, %s)",
            (uid, media_id, status, progress, dropped_at),
        )


@pytest.fixture
def conn(pg_url):
    with psycopg.connect(pg_url, autocommit=True) as c:
        yield c


def test_k_is_five_as_decided_for_phase_13():
    assert K == 5


def test_most_added_works_are_hidden_below_k_accounts(conn, catalog):
    users = _accounts(conn, K)
    _entries(conn, users, catalog["anime"][1])  # k comptes : visible
    _entries(conn, users[: K - 1], catalog["anime"][2])  # k - 1 comptes : masqué
    rows = conn.execute("SELECT media_id, title, nb_accounts FROM bi.app_top_added").fetchall()
    assert rows == [(catalog["anime"][1], "Anime 1", K)]


def test_declared_drops_show_the_median_drop_point_and_the_mal_critical_episode(conn, catalog):
    users = _accounts(conn, K)
    for i, uid in enumerate(users):  # lâché aux épisodes 1, 2, 3, 4, 5 → médiane 3
        _entries(conn, [uid], catalog["anime"][1], status="dropped", progress=i + 1,
                 dropped_at=i + 1)  # fmt: skip
    _entries(conn, users[:2], catalog["anime"][2], status="dropped", progress=1, dropped_at=1)
    rows = conn.execute("SELECT media_id, nb_accounts, median_dropped_at, critical_episode"
                        " FROM bi.app_declared_drops").fetchall()  # fmt: skip
    # Anime 1 a un épisode critique MAL (3) dans le catalogue de test ; anime 2 masqué (2 < k).
    assert rows == [(catalog["anime"][1], K, 3.0, 3)]


def test_totals_and_status_counts_need_k_accounts(conn, catalog):
    users = _accounts(conn, K - 1)
    _entries(conn, users, catalog["anime"][1])
    assert conn.execute("SELECT count(*) FROM bi.app_totals").fetchone() == (0,)
    assert conn.execute("SELECT count(*) FROM bi.app_status_counts").fetchone() == (0,)
    _entries(conn, _accounts(conn, 1, prefix="v"), catalog["anime"][1])
    assert conn.execute("SELECT nb_accounts FROM bi.app_totals").fetchone() == (K,)
    assert conn.execute("SELECT status, nb_entries, nb_accounts FROM bi.app_status_counts"
                        ).fetchall() == [("in_progress", K, K)]  # fmt: skip


def test_a_hidden_status_cannot_be_recovered_by_subtraction(conn, catalog):
    """k comptes en cours, 1 seul en pause : la ligne « en pause » est masquée, et aucun total
    publié ne permet de la retrouver (total des entrées − statuts visibles)."""
    users = _accounts(conn, K)
    _entries(conn, users, catalog["anime"][1])
    _entries(conn, users[:1], catalog["anime"][2], status="paused")
    statuses = {r[0] for r in conn.execute("SELECT status FROM bi.app_status_counts")}
    assert statuses == {"in_progress"}
    query = ("SELECT column_name FROM information_schema.columns"
             " WHERE table_schema = 'bi' AND table_name = 'app_totals'")  # fmt: skip
    assert {r[0] for r in conn.execute(query)} == {"nb_accounts", "nb_onboarded"}


def test_weekly_signups_hide_small_weeks(conn):
    _accounts(conn, K)  # cette semaine : k inscriptions
    _accounts(conn, 1, prefix="old", created_at=dt.datetime(2026, 1, 7, tzinfo=dt.UTC))
    rows = conn.execute("SELECT week, nb_signups FROM bi.app_signups_weekly").fetchall()
    assert [r[1] for r in rows] == [K]  # la semaine d'une seule inscription n'apparaît pas


def test_no_bi_view_exposes_personal_data(conn):
    personal = {"user_id", "email", "pseudo", "password_hash", "token_version", "review"}
    query = "SELECT column_name FROM information_schema.columns WHERE table_schema = 'bi'"
    columns = {r[0] for r in conn.execute(query)}
    assert columns and not (columns & personal)


def _as_role(pg_url):
    url = make_url(pg_url).set(username=TEST_ROLE, password=TEST_PASSWORD)
    return psycopg.connect(url.render_as_string(hide_password=False), autocommit=True)


@pytest.fixture
def test_role(conn):
    """Un rôle est global au serveur : il est supprimé après le test (droits compris)."""
    yield TEST_ROLE
    conn.execute(f"DROP OWNED BY {TEST_ROLE}")
    conn.execute(f"DROP ROLE {TEST_ROLE}")


def test_bi_role_reads_bi_views_only_and_survives_a_redeploy(conn, pg_url, catalog, test_role):
    bi_role.ensure(conn, TEST_PASSWORD, role=TEST_ROLE)
    bi_role.ensure(conn, TEST_PASSWORD, role=TEST_ROLE)  # rejouable (et change le mot de passe)
    migrate.run(pg_url)  # redéploiement : vues remplacées, droits conservés
    with _as_role(pg_url) as bi:
        assert bi.execute("SELECT count(*) FROM bi.anime_drop").fetchone()[0] >= 1
        assert bi.execute("SELECT count(*) FROM bi.app_totals").fetchone() is not None
        assert bi.execute("SHOW default_transaction_read_only").fetchone() == ("on",)
        for forbidden in ("SELECT * FROM app.users", "SELECT * FROM catalog.media",
                          "SELECT * FROM mart.critical_episode"):  # fmt: skip
            with pytest.raises(errors.InsufficientPrivilege):
                bi.execute(forbidden)
        with pytest.raises((errors.InsufficientPrivilege, errors.ReadOnlySqlTransaction)):
            bi.execute("CREATE TABLE bi.intrus (x int)")


def test_the_password_never_reaches_the_server_in_clear(conn, test_role):
    bi_role.ensure(conn, TEST_PASSWORD, role=TEST_ROLE)
    stored = conn.execute("SELECT rolpassword FROM pg_authid WHERE rolname = %s",
                          (TEST_ROLE,)).fetchone()[0]  # fmt: skip
    assert stored.startswith("SCRAM-SHA-256$") and TEST_PASSWORD not in stored


@pytest.mark.parametrize(("host", "hashed"), [
    ("localhost", True), ("127.0.0.1", True), ("db", True),
    # Neon refuse un mot de passe déjà haché (« Neon only supports being given plaintext
    # passwords », mesuré le 2026-11-28) : il le hache lui-même via son plan de contrôle.
    ("ep-x-123.eu-central-1.aws.neon.tech", False),
])  # fmt: skip
def test_password_is_hashed_client_side_except_for_neon(host, hashed):
    assert bi_role.hash_client_side(host) is hashed


def test_bi_role_refuses_a_weak_password(conn):
    with pytest.raises(ValueError, match="16 caractères"):
        bi_role.ensure(conn, "court", role=TEST_ROLE)
