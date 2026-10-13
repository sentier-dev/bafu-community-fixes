from datetime import date, datetime

import pytest

from bafu_community_fixes.xsd import BOOLEAN, DATE, DATETIME, DOUBLE, GYEAR, INTEGER, LexicalError


@pytest.mark.parametrize("text", ["True", "yes", "", "t"])
def test_boolean_rejects_non_xsd_spellings(text):
    with pytest.raises(LexicalError):
        BOOLEAN.parse(text)


def test_boolean_accepts_xsd_spellings():
    assert [BOOLEAN.parse(t) for t in ("true", "false", "1", "0", " true ")] == [
        True,
        False,
        True,
        False,
        True,
    ]


@pytest.mark.parametrize("text", ["1_000", "1,5", "infinity", "nan", ""])
def test_double_rejects_python_only_spellings(text):
    with pytest.raises(LexicalError):
        DOUBLE.parse(text)


def test_double_round_trip():
    assert DOUBLE.parse("1.5E-4") == 1.5e-4
    assert DOUBLE.format(1.5e-4) == "0.00015"
    assert DOUBLE.format(2.0) == "2.0"


def test_integer():
    assert INTEGER.parse(" 42 ") == 42
    with pytest.raises(LexicalError):
        INTEGER.parse("4.0")


def test_dates():
    assert DATE.parse("2021-01-31") == date(2021, 1, 31)
    for text in ("2021-01", "2021-01-01+01:00"):
        with pytest.raises(LexicalError):
            DATE.parse(text)
    assert GYEAR.parse("2025") == 2025
    assert GYEAR.format(800) == "0800"


def test_datetime_requires_t_separator():
    assert DATETIME.parse("2024-06-21T22:32:02.538+02:00").tzinfo is not None
    assert DATETIME.parse("2024-06-21T22:32:02Z") == datetime.fromisoformat(
        "2024-06-21T22:32:02+00:00"
    )
    with pytest.raises(LexicalError):
        DATETIME.parse("2025-09-04 18:38:44.741718")
