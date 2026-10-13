"""Conversion between XSD lexical forms (strings in the XML) and Python values.

Parsing follows the XSD lexical rules exactly. In particular, it doesn't accept
the extra spellings Python allows (`"True"`, `"1_000"`, `"inf"`,
`"2020-01-01 12:00"`). Fixing those is the job of an explicit import fix, not
something the reader quietly does.

Writing always produces one canonical form, so output is normalised.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from enum import IntEnum
from functools import cache
from importlib.resources import files
from typing import Any

from lxml import etree

SCHEMA_DIR = files("bafu_community_fixes.schemas") / "ecospold1"
_XS = "{http://www.w3.org/2001/XMLSchema}"


class LexicalError(ValueError):
    pass


@dataclass(frozen=True)
class Lexical:
    """How a simple type is read from, and written to, XML text."""

    name: str
    parse: Callable[[str], Any]
    format: Callable[[Any], str]


def _matching(pattern: str, name: str) -> Callable[[str], str]:
    regex = re.compile(pattern)

    def check(text: str) -> str:
        text = text.strip()  # XSD whitespace="collapse" for all non-string types
        if not regex.fullmatch(text):
            raise LexicalError(f"{text!r} is not a valid {name}")
        return text

    return check


_integer = _matching(r"[+-]?\d+", "xsd:integer")
_double = _matching(r"[+-]?(\d+(\.\d*)?|\.\d+)([Ee][+-]?\d+)?|[+-]?INF|NaN", "xsd:double")
_boolean = _matching(r"true|false|1|0", "xsd:boolean")
_date = _matching(r"\d{4}-\d{2}-\d{2}", "xsd:date without timezone")
_datetime = _matching(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})?", "xsd:dateTime"
)
_gyear = _matching(r"\d{4}", "xsd:gYear without timezone")


def _parse_double(text: str) -> float:
    text = _double(text)
    return float(text.replace("INF", "inf"))


def _format_double(value: float) -> str:
    # repr() gives the shortest string that round-trips. `allow_inf_nan=False` on
    # the model means we never have to write INF/NaN.
    return repr(float(value))


def _parse_datetime(text: str) -> datetime:
    return datetime.fromisoformat(_datetime(text).replace("Z", "+00:00"))


STRING = Lexical("string", lambda text: text, lambda value: value)
INTEGER = Lexical("integer", lambda text: int(_integer(text)), str)
DOUBLE = Lexical("double", _parse_double, _format_double)
BOOLEAN = Lexical(
    "boolean", lambda text: _boolean(text) in ("true", "1"), lambda v: "true" if v else "false"
)
DATE = Lexical("date", lambda text: date.fromisoformat(_date(text)), date.isoformat)
DATETIME = Lexical("dateTime", _parse_datetime, datetime.isoformat)
GYEAR = Lexical("gYear", lambda text: int(_gyear(text)), lambda value: f"{value:04d}")
# Values must have exactly one decimal place; the model checks that.
PERCENT = Lexical("percent", _parse_double, lambda value: f"{value:.1f}")


def int_enum(enum: type[IntEnum]) -> Lexical:
    return Lexical(enum.__name__, lambda text: enum(int(_integer(text))), lambda v: str(int(v)))


@cache
def enumeration(simple_type: str) -> frozenset[str]:
    """The allowed values of an enumerated simple type in the vendored XSD."""
    tree = etree.parse(str(SCHEMA_DIR / "EcoSpold01DataTypes.xsd"))
    (node,) = tree.getroot().iterfind(f"{_XS}simpleType[@name='{simple_type}']")
    return frozenset(e.get("value") for e in node.iter(f"{_XS}enumeration"))
