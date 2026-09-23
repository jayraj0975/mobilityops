from datetime import date

import duckdb
import pytest

from mobilityops.sqlutil import quote_literal


def test_plain_and_date_values() -> None:
    assert quote_literal("abc") == "'abc'"
    assert quote_literal(date(2024, 3, 10)) == "'2024-03-10'"


def test_quotes_are_doubled_so_they_cannot_close_the_literal() -> None:
    assert quote_literal("it's") == "'it''s'"


def test_an_injection_attempt_stays_inside_the_literal() -> None:
    evil = "x'); DROP TABLE t; --"
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE t(a VARCHAR)")
    con.execute(f"INSERT INTO t VALUES ({quote_literal(evil)})")
    assert con.execute("SELECT count(*), any_value(a) FROM t").fetchone() == (
        1,
        evil,
    )  # table intact


def test_nul_bytes_are_rejected() -> None:
    with pytest.raises(ValueError, match="NUL"):
        quote_literal("a\x00b")
