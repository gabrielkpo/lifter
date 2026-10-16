"""Tests run on the same Postgres major version as the hosted database (Neon, 18)."""

HOSTED_MAJOR = 18


def test_tests_run_on_the_hosted_major_version(conn):
    version = conn.execute("show server_version_num").fetchone()[0]
    assert int(version) // 10000 == HOSTED_MAJOR, (
        f"tests run on Postgres {version}, the hosted database is {HOSTED_MAJOR}:"
        " point TEST_DATABASE_URL at a Postgres 18 server"
    )
