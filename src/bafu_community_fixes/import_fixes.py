"""Fixes that make the raw BAFU release readable as EcoSpold 1.

These run on the raw lxml tree of each `<dataset>` (EcoSpold namespace already
stripped), in the order they are defined here, before any model is built.

Every edit goes through the helpers below (`_set`, `_delete`, `_set_text`,
`_add`, `_remove`). They record each change for the run report, and a fix
"changed" a dataset exactly when it recorded a change. Don't modify the tree
directly, or the change won't be reported.

Community patches don't belong here. They go in `patches/` and work on the
validated models.
"""

import re
from calendar import monthrange
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from bafu_community_fixes.changes import Change, Provenance, Rule, Snippet
from bafu_community_fixes.models import ECOSPOLD_NS, EXT_NS
from bafu_community_fixes.xml import attributes_with
from bafu_community_fixes.xsd import BOOLEAN, enumeration

type Fix = Callable[[etree._Element], None]

AUTHOR = "Chris Mutel"
ADAPTED = "Chris Mutel, adapted by Claude Code"


@dataclass(frozen=True)
class ImportFix:
    id: str
    func: Fix
    provenance: Provenance
    rules: tuple[Rule, ...] = ()

    @property
    def description(self) -> str:
        return (self.func.__doc__ or "").strip().splitlines()[0]

    @property
    def rationale(self) -> str:
        """The docstring after its first line."""
        lines = (self.func.__doc__ or "").strip().splitlines()[1:]
        return "\n".join(line.strip() for line in lines).strip()


IMPORT_FIXES: list[ImportFix] = []


def import_fix(
    id: str,
    *,
    authored_by: str,
    authorised_by: str | None = None,
    references: tuple[str, ...] = (),
    reported_by: str | None = None,
    confirmed_by: str | None = None,
    rules: tuple[Rule, ...] = (),
) -> Callable[[Fix], Fix]:
    """Register an import fix. `rules` say, in plain language, why it's needed."""

    def decorator(func: Fix) -> Fix:
        if any(f.id == id for f in IMPORT_FIXES):
            raise ValueError(f"Duplicate import fix id: {id}")
        provenance = Provenance(authored_by, authorised_by, references, reported_by, confirmed_by)
        IMPORT_FIXES.append(ImportFix(id, func, provenance, rules))
        return func

    return decorator


class ImportFixError(ValueError):
    """The data needs a decision that no fix covers yet."""


@dataclass(frozen=True)
class Placeholders:
    """Values used where required data is missing entirely.

    Checked when created, so the placeholders themselves can't make the output invalid.
    """

    year: int = 1111
    number: int = 1111  # for persons and the validator
    country: str = "AQ"  # Antarctica
    text: str = "UNKNOWN"  # for missing addresses, company codes, proof reading details

    def __post_init__(self):
        if not 1 <= self.year <= 9999:
            raise ValueError(f"The placeholder year must be between 1 and 9999, not {self.year}")
        if not 1 <= self.number <= 2**31 - 1:
            raise ValueError(f"The placeholder number must be 1 or more, not {self.number}")
        if self.country not in enumeration("TISOCountryCode"):
            raise ValueError(f"{self.country!r} isn't a two-letter ISO country code")
        if not 1 <= len(self.text.strip()) <= 7 or self.text != self.text.strip():
            # Also used for company codes, which can be at most 7 characters long
            raise ValueError(f"The placeholder text must be 1 to 7 characters, not {self.text!r}")

    def describe(self) -> str:
        return (
            f"year {self.year:04d}, number {self.number}, country {self.country}, text {self.text}"
        )


DEFAULT_PLACEHOLDERS = Placeholders()
_placeholders: ContextVar[Placeholders] = ContextVar(
    "import_fix_placeholders", default=DEFAULT_PLACEHOLDERS
)

LOCATION_REMAPPING = {
    # Regional codes have a maximum length of 7
    "Europe without Switzerland": "EURwoCH",
}

_PROCESS = "metaInformation/processInformation"
_MODELLING = "metaInformation/modellingAndValidation"
_ADMIN = "metaInformation/administrativeInformation"

# --- Change-recording edit helpers ----------------------------------------------------

_changes: ContextVar[list[Change]] = ContextVar("import_fix_changes")
# When set, the first element a fix touches, and its snippet before the change
_capture: ContextVar[dict | None] = ContextVar("import_fix_capture", default=None)

MAX_SNIPPET_VALUE = 100
MAX_SNIPPET_CHILDREN = 6


def _quote(value: str) -> str:
    if len(value) > MAX_SNIPPET_VALUE:
        value = value[:MAX_SNIPPET_VALUE] + "…"
    return value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


def snippet(el: etree._Element) -> str:
    """Readable XML for one element: one attribute per line, children abbreviated."""
    lines = [f"<{el.tag}"] + [f'    {k}="{_quote(v)}"' for k, v in el.attrib.items()]
    children = [c for c in el if isinstance(c.tag, str) and not c.tag.startswith("{")]
    if not children and not (el.text or "").strip():
        lines[-1] += "/>"
        return "\n".join(lines)
    lines[-1] += ">"
    if not children:
        lines[-1] += _quote(el.text.strip()) + f"</{el.tag}>"
        return "\n".join(lines)
    for child in children[:MAX_SNIPPET_CHILDREN]:
        if len(child):
            lines.append(f"  <{child.tag}>…</{child.tag}>")
        elif child.attrib and not (child.text or "").strip():
            number = f' number="{child.get("number")}"' if child.get("number") else ""
            lines.append(f"  <{child.tag}{number} …/>")
        else:
            lines.append(f"  <{child.tag}>{_quote((child.text or '').strip())}</{child.tag}>")
    if len(children) > MAX_SNIPPET_CHILDREN:
        lines.append("  …")
    lines.append(f"</{el.tag}>")
    return "\n".join(lines)


type SourceIndex = Mapping[str, dict[str, str]]

# Every source in the release, by number (see `index_sources`)
_sources: ContextVar[SourceIndex] = ContextVar("import_fix_sources")  # set by run_fix


def index_sources(paths: Iterable[Path]) -> dict[str, dict[str, str]]:
    """The attributes of every `<source>` in the files, by source number.

    Where datasets have different versions of the same source, the most common
    version wins (ties go to the first in sorted order, so the result is stable).
    """
    versions: dict[str, Counter] = {}
    for path in paths:
        tags = ("source", f"{{{ECOSPOLD_NS}}}source")
        for _, el in etree.iterparse(str(path), tag=tags):
            versions.setdefault(el.get("number"), Counter())[tuple(el.attrib.items())] += 1
            el.clear()
    return {
        number: dict(min(counts.items(), key=lambda item: (-item[1], item[0]))[0])
        for number, counts in versions.items()
    }


def _capture_before(el: etree._Element) -> None:
    if (capture := _capture.get()) is not None and not capture:
        capture.update(element=el, before=snippet(el))


def element_path(el: etree._Element) -> str:
    """Path from the enclosing `<dataset>`, e.g. `flowData/exchange[3]`."""
    parts = []
    while el is not None and el.tag != "dataset":
        parent = el.getparent()
        part = el.tag
        if parent is not None:
            same = list(parent.iterchildren(el.tag))  # filtered in C; this is hot
            if len(same) > 1:
                part += f"[{same.index(el) + 1}]"
        parts.append(part)
        el = parent
    return "/".join(reversed(parts))


def _record(el: etree._Element, suffix: str, old: str | None, new: str | None) -> None:
    _capture_before(el)
    path = element_path(el)
    _changes.get().append(Change(f"{path}/{suffix}" if path else suffix, old, new))


def _set(el: etree._Element, attribute: str, value: str) -> None:
    if (old := el.get(attribute)) != value:
        _record(el, f"@{attribute}", old, value)
        el.set(attribute, value)


def _delete(el: etree._Element, attribute: str) -> None:
    if (old := el.get(attribute)) is not None:
        _record(el, f"@{attribute}", old, None)
        del el.attrib[attribute]


def _truncate(el: etree._Element, attribute: str, max_length: int) -> None:
    if (value := el.get(attribute)) is not None and len(value) > max_length:
        _set(el, attribute, value[:max_length])


def _set_text(el: etree._Element, text: str) -> None:
    if el.text != text:
        _capture_before(el)
        _changes.get().append(Change(element_path(el), el.text, text))
        el.text = text


def _add(parent: etree._Element, tag: str, text: str) -> None:
    _capture_before(parent)
    child = etree.SubElement(parent, tag)
    child.text = text
    _changes.get().append(Change(element_path(child), None, text))


def _append(parent: etree._Element, tag: str, attributes: dict[str, str]) -> None:
    _capture_before(parent)
    child = etree.SubElement(parent, tag, attributes)
    _changes.get().append(Change(element_path(child), None, etree.tostring(child, encoding=str)))


def _remove(el: etree._Element) -> None:
    _capture_before(el.getparent())
    _changes.get().append(Change(element_path(el), etree.tostring(el, encoding=str), None))
    el.getparent().remove(el)


# --- The fixes, in order -------------------------------------------------------------


@import_fix(
    "timestamp-separator",
    authored_by=AUTHOR,
    authorised_by=AUTHOR,
    rules=(
        Rule(
            "Dates with a time must be written with a 'T' between the date and the time, "
            "as in 2025-09-04T18:38:44.",
            "xsd:dateTime: dataset/@timestamp, dataSetInformation/@timestamp",
        ),
    ),
)
def fix_timestamps(dataset: etree._Element) -> None:
    """Use 'T' rather than a space between date and time in timestamps."""
    pattern = re.compile(
        r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})?)"
    )
    for el in (dataset, dataset.find(f"{_PROCESS}/dataSetInformation")):
        if el is not None and (match := pattern.fullmatch(el.get("timestamp", ""))):
            _set(el, "timestamp", f"{match[1]}T{match[2]}")


@import_fix(
    "boolean-spelling",
    authored_by=AUTHOR,
    authorised_by=AUTHOR,
    rules=(
        Rule(
            "Yes/no fields may only contain 'true' or 'false' (or 1 and 0), in lower case. "
            "'True', 'False' and blank values aren't allowed.",
            "xsd:boolean, e.g. exchange/@infrastructureProcess, "
            "timePeriod/@dataValidForEntirePeriod",
        ),
        Rule(
            "These fields are required, so a blank value can't simply be left out. "
            "Blank is read as 'false'.",
            'use="required": timePeriod/@dataValidForEntirePeriod, '
            "dataGeneratorAndPublication/@copyright",
        ),
    ),
)
def fix_booleans(dataset: etree._Element) -> None:
    """Spell booleans as 'true'/'false'; treat blank as false.

    Only boolean attributes are changed. Blank values in other fields, such as about
    137,000 blank exchange `generalComment`s, are valid and kept.
    """
    boolean_attributes = attributes_with(BOOLEAN)
    for el in dataset.iter():
        for attribute, value in el.attrib.items():
            if (el.tag, attribute) in boolean_attributes:
                _set(
                    el, attribute, {"True": "true", "False": "false", "": "false"}.get(value, value)
                )


def _complete_date(text: str, end: bool) -> str:
    """Expand YYYY or YYYY-MM to a full date at the start or end of the period."""
    if match := re.fullmatch(r"(\d{4})-(\d{2})", text):
        year, month = int(match[1]), int(match[2])
        return f"{year:04d}-{month:02d}-{monthrange(year, month)[1] if end else 1:02d}"
    if re.fullmatch(r"\d{4}", text):
        return f"{text}-12-31" if end else f"{text}-01-01"
    return text


@import_fix(
    "time-period-dates",
    authored_by=AUTHOR,
    authorised_by=AUTHOR,
    rules=(
        Rule(
            "Start and end dates must be complete dates with year, month and day. "
            "'2021-02' or '2022' alone aren't valid dates.",
            "xsd:date: timePeriod/startDate, timePeriod/endDate",
        ),
        Rule(
            "The schema would also accept a time zone after a date (2021-01-01+01:00). "
            "We drop it, so that all dates are written the same way.",
            "xsd:date allows an optional time zone",
            schema=False,
        ),
    ),
)
def fix_time_period_dates(dataset: etree._Element) -> None:
    """Complete partial start/end dates (first/last day of month or year), drop timezones.

    Timezone offsets (e.g. `2021-01-01+01:00`, 230 datasets) are dropped, so that
    all dates are written the same way.
    """
    for tag, end in (("startDate", False), ("endDate", True)):
        for el in dataset.iterfind(f"{_PROCESS}/timePeriod/{tag}"):
            text = re.sub(
                r"(\d{4}-\d{2}-\d{2})(Z|[+-]\d{2}:\d{2})$", r"\1", (el.text or "").strip()
            )
            _set_text(el, _complete_date(text, end))


@import_fix(
    "time-period-default-years",
    authored_by=AUTHOR,
    authorised_by=AUTHOR,
    rules=(
        Rule(
            "Every time period needs both a start and an end (a year, a month or a date).",
            "timePeriod: one of startYear/startYearMonth/startDate and one of "
            "endYear/endYearMonth/endDate is required",
        ),
    ),
)
def fix_missing_time_period(dataset: etree._Element) -> None:
    """Add placeholder start/end years when a time period has no start or end."""
    for time_period in dataset.iterfind(f"{_PROCESS}/timePeriod"):
        for side in ("start", "end"):
            if not any(
                time_period.find(side + k) is not None for k in ("Year", "YearMonth", "Date")
            ):
                _add(time_period, f"{side}Year", f"{_placeholders.get().year:04d}")


@import_fix(
    "representativeness-percent",
    authored_by=AUTHOR,
    authorised_by=AUTHOR,
    rules=(
        Rule(
            "Percentages are written with one decimal place, like 100.0 or 55.5, and can't "
            "be more than 100. '100' and 'unknown' aren't allowed.",
            "TPercent: pattern \\d{1,3}\\.\\d, maximum 100.0: representativeness/@percent",
        ),
        Rule(
            "The percentage is optional, so an unknown value is left out.",
            "representativeness/@percent is optional",
        ),
    ),
)
def fix_percent(dataset: etree._Element) -> None:
    """Write percentages with exactly one decimal place (truncating), drop non-numbers.

    Non-numeric values (`unknown`, 1 dataset) are removed; the percentage is optional.
    """
    for el in dataset.iterfind(f"{_MODELLING}/representativeness"):
        value = el.get("percent")
        if value is None:
            continue
        if match := re.fullmatch(r"(\d+)(?:\.(\d*))?", value.strip()):
            _set(el, "percent", f"{match[1]}.{(match[2] or '0')[:1]}")
        else:
            _delete(el, "percent")


@import_fix(
    "copy-missing-published-source",
    authored_by=AUTHOR,
    authorised_by=AUTHOR,
    rules=(
        Rule(
            "If a dataset says where it was published, that must be one of the dataset's "
            "own sources.",
            "keyref fkDataGenerationAndPublicationSource: "
            "dataGeneratorAndPublication/@referenceToPublishedSource",
        ),
    ),
)
def copy_missing_published_source(dataset: etree._Element) -> None:
    """Copy a published source that's referenced but missing from another dataset.

    The 2 datasets in BAFU 2026 that refer to a missing source (141100) get a copy
    of that source from the 29 other datasets that have it. Where those copies
    differ, the most common version is used. If no dataset has the source, the
    reference is removed instead, as the schema doesn't allow it to point nowhere.
    """
    modelling = dataset.find(_MODELLING)
    numbers = {s.get("number") for s in modelling.iterfind("source")}
    for el in dataset.iterfind(f"{_ADMIN}/dataGeneratorAndPublication"):
        reference = el.get("referenceToPublishedSource")
        if reference is None or reference in numbers:
            continue
        if (source := _sources.get().get(reference)) is not None:
            _append(modelling, "source", source)
            numbers.add(reference)
        else:
            _delete(el, "referenceToPublishedSource")


@import_fix(
    "source-attributes",
    authored_by=AUTHOR,
    authorised_by=AUTHOR,
    rules=(
        Rule(
            "Sources have no 'sourceNumber' field; only fields defined in the schema are allowed.",
            "TSource has no sourceNumber attribute",
        ),
        Rule(
            "Every source needs a publication year, written as four digits.",
            'xsd:gYear, use="required": source/@year',
        ),
        Rule(
            "A volume number is a whole number of at most three digits.",
            "pattern \\d{1,3}: source/@volumeNo",
        ),
        Rule(
            "A publisher's name can be at most 40 characters long.",
            "TString40: source/@publisher",
        ),
    ),
)
def fix_sources(dataset: etree._Element) -> None:
    """Remove `sourceNumber`; placeholder for invalid years; drop bad `volumeNo`; cut publisher."""
    for source in dataset.iterfind(f"{_MODELLING}/source"):
        _delete(source, "sourceNumber")  # Not in the schema; values are 0 or 999
        year = source.get("year", "").strip()
        placeholder = f"{_placeholders.get().year:04d}"
        _set(source, "year", str(int(year)) if re.fullmatch(r"\d+", year) else placeholder)
        if not re.fullmatch(r"\d{1,3}", source.get("volumeNo", "0")):
            _delete(source, "volumeNo")
        _truncate(source, "publisher", 40)


@import_fix(
    "person-attributes",
    authored_by=AUTHOR,
    authorised_by=AUTHOR,
    rules=(
        Rule(
            "Every person needs a country, given as a two-letter ISO country code.",
            'TISOCountryCode, use="required": person/@countryCode',
        ),
        Rule(
            "Every person needs an address and a company code (blank is allowed), a number of "
            "1 or more, a name of at most 40 characters, and a company code of at most 7 "
            "characters.",
            'use="required": person/@address, @companyCode, @number; TString40: @name; '
            "TCompanyCode (7): @companyCode",
        ),
    ),
)
def fix_persons(dataset: etree._Element) -> None:
    """Placeholders for missing country/company codes, addresses, numbers; cut long values.

    Blank addresses and company codes are kept, as the schema allows. Placeholders
    are only used where an attribute is missing entirely.
    """
    placeholders = _placeholders.get()
    counter = placeholders.number
    for person in dataset.iterfind(f"{_ADMIN}/person"):
        if person.get("countryCode", "") in ("", "false"):
            _set(person, "countryCode", placeholders.country)
        for attribute in ("address", "companyCode"):
            if person.get(attribute) is None:
                _set(person, attribute, placeholders.text)
        if person.get("number", "").strip() in ("", "0"):
            _set(person, "number", str(counter))
            counter += 1
        _truncate(person, "companyCode", 7)
        _truncate(person, "name", 40)


@import_fix(
    "validation",
    authored_by=AUTHOR,
    authorised_by=AUTHOR,
    rules=(
        Rule(
            "A dataset can have at most one validation record.",
            "modellingAndValidation/validation: maxOccurs 1",
        ),
        Rule(
            "A validation record must name its validator, who must be one of the dataset's "
            "persons.",
            'use="required" and keyref fkValidationPerson: validation/@proofReadingValidator',
        ),
        Rule(
            "A validation record must have proof reading details (blank is allowed).",
            'use="required": validation/@proofReadingDetails',
        ),
    ),
)
def fix_validation(dataset: etree._Element) -> None:
    """Remove empty `<validation/>`; placeholders for missing proof reading details/validator.

    Only *empty* elements are removed (all 197 extra elements in BAFU 2026 are
    empty), so no validation information is lost; the schema check still fails if
    more than one real validation record remains. Blank proof reading details are
    kept, as the schema allows.
    """
    modelling = dataset.find(_MODELLING)
    for validation in list(modelling.iterfind("validation")):
        if not validation.attrib and len(validation) == 0:
            _remove(validation)
    for validation in modelling.iterfind("validation"):
        if validation.get("proofReadingDetails") is None:
            _set(validation, "proofReadingDetails", _placeholders.get().text)
        if validation.get("proofReadingValidator", "").strip() in ("", "0"):
            _set(validation, "proofReadingValidator", str(_placeholders.get().number))


@import_fix(
    "reference-function-text",
    authored_by=AUTHOR,
    authorised_by=AUTHOR,
    rules=(
        Rule(
            "The reference function has no 'text' field; only fields defined in the schema "
            "are allowed. The same text is already in the general comment.",
            "TReferenceFunction has no text attribute",
        ),
    ),
)
def fix_reference_function_text(dataset: etree._Element) -> None:
    """Remove the non-schema `text` attribute from `referenceFunction`.

    The attribute is only removed if its text also appears in `generalComment` or
    `includedProcesses` (true for all 33 cases in BAFU 2026). Otherwise this raises,
    so no information is lost silently.
    """
    for el in dataset.iterfind(f"{_PROCESS}/referenceFunction"):
        if (text := el.get("text")) is None:
            continue
        if text not in el.get("generalComment", "") + el.get("includedProcesses", ""):
            raise ImportFixError(f"referenceFunction text not found elsewhere: {text[:80]!r}")
        _delete(el, "text")


# (exchange name, wrong CAS number) -> correct CAS number
CAS_CORRECTIONS = {
    # Not a valid CAS number; the other 1400 "Sulfur dioxide" exchanges use 007446-09-5
    ("Sulfur dioxide", "2025884"): "007446-09-5",
}


@import_fix(
    "cas-numbers-blank",
    authored_by=AUTHOR,
    authorised_by=AUTHOR,
    rules=(
        Rule(
            "A CAS number is written as three groups of digits separated by dashes, like "
            "007446-09-5. Blank values and '0' aren't allowed.",
            "pattern \\d{2,7}-\\d{2}-\\d: exchange/@CASNumber",
        ),
        Rule(
            "The CAS number is optional, so a missing value is left out.",
            "exchange/@CASNumber is optional",
        ),
    ),
)
def remove_blank_cas_numbers(dataset: etree._Element) -> None:
    """Remove blank or zero CAS numbers."""
    for exchange in dataset.iterfind("flowData/exchange"):
        if (cas := exchange.get("CASNumber")) is not None and cas.strip() in ("", "0"):
            _delete(exchange, "CASNumber")


@import_fix(
    "cas-numbers-known-wrong",
    authored_by=AUTHOR,
    authorised_by=AUTHOR,
    rules=(
        Rule(
            "A CAS number is written as three groups of digits separated by dashes, like "
            "007446-09-5. Digits without dashes aren't allowed.",
            "pattern \\d{2,7}-\\d{2}-\\d: exchange/@CASNumber",
        ),
    ),
)
def correct_known_wrong_cas_numbers(dataset: etree._Element) -> None:
    """Correct CAS numbers that are known to be wrong.

    `2025884` (sulfur dioxide, 5 exchanges) isn't a valid CAS number; the other 1,400
    sulfur dioxide exchanges use `007446-09-5`. The corrections are in `CAS_CORRECTIONS`.
    """
    for exchange in dataset.iterfind("flowData/exchange"):
        key = (exchange.get("name"), exchange.get("CASNumber"))
        if (correct := CAS_CORRECTIONS.get(key)) is not None:
            _set(exchange, "CASNumber", correct)


# Dummy exchange numbers are DUMMY_BASE + original number * 1000 + occurrence, so
# 1000631002 is the second exchange numbered 631. BAFU numbers go up to 997,485, so a
# dummy can't clash with a real number, and the largest dummy (1,999,999,999) is still a
# valid 32-bit integer.
DUMMY_BASE = 1_000_000_000
MAX_ENCODED_NUMBER = 999_999
MAX_OCCURRENCE = 999


def _is_digits(value: str) -> bool:
    # str.isdigit() also accepts characters like "²", which int() rejects
    return value.isascii() and value.isdigit()


def _index_number(value: str | None) -> int | None:
    """`value` as a schema-valid exchange number (1 to 2**31 - 1), or None."""
    if value is None or not _is_digits(value) or not 1 <= int(value) <= 2**31 - 1:
        return None
    return int(value)


def _dummy_number(original: str | None, occurrence: int) -> int:
    if original is None or not _is_digits(original) or int(original) > MAX_ENCODED_NUMBER:
        raise ImportFixError(f"Can't encode exchange number {original!r} in a dummy number")
    if occurrence > MAX_OCCURRENCE:
        raise ImportFixError(f"More than {MAX_OCCURRENCE} exchanges numbered {original}")
    return DUMMY_BASE + int(original) * 1000 + occurrence


@import_fix(
    "renumber-exchanges",
    authored_by=AUTHOR,
    authorised_by=AUTHOR,
    rules=(
        Rule(
            "Within a dataset, every exchange needs its own number, of 1 or more. In BAFU, "
            "several exchanges often share a number.",
            "unique constraint pkExchangeNumber; TIndexNumber (minimum 1): exchange/@number",
        ),
    ),
)
def renumber_exchanges(dataset: etree._Element) -> None:
    """Give exchanges that share a number (or have an invalid one) a dummy number.

    BAFU exchange numbers are identifiers. The reference product has the dataset's own
    number, a technosphere input almost always has the number of the dataset that supplies
    it, and an elementary flow has a number for the substance. But numbers aren't unique
    within a dataset: one substance emitted to several subcompartments shares a number,
    and so do some repeated exchanges.

    So numbers are kept wherever possible. Among the exchanges that share a number, the
    reference product keeps it, or else the first one in the dataset. The others get a
    dummy number, 1,000,000,000 + original number × 1,000 + occurrence: `1000631002` is
    the second exchange numbered 631. Dummies are far above any BAFU number, so they can't
    be mistaken for one. The original number is also kept as the `originalNumber`
    extension.
    """
    exchanges = dataset.findall("flowData/exchange")
    by_number: dict[str | None, list[etree._Element]] = {}
    for exchange in exchanges:
        by_number.setdefault(exchange.get("number"), []).append(exchange)
    keepers = {
        number: next((e for e in group if e.findtext("outputGroup") == "0"), group[0])
        for number, group in by_number.items()
        if _index_number(number) is not None
    }
    # Allocations refer to exchanges by number, so a reference to a shared number is
    # ambiguous. BAFU has no allocations; stop rather than guess if that changes.
    for allocation in dataset.iterfind("flowData/allocation"):
        references = [allocation.get("referenceToCoProduct")]
        references += [r.text for r in allocation.iterfind("referenceToInputOutput")]
        for reference in references:
            if len(by_number.get(reference, ())) > 1:
                raise ImportFixError(
                    f"Allocation refers to exchange number {reference}, which several "
                    "exchanges share"
                )

    extensions = dataset.find(f"{{{EXT_NS}}}extensions")
    for exchange in exchanges:
        original = exchange.get("number")
        if keepers.get(original) is exchange:
            continue
        number = str(_dummy_number(original, by_number[original].index(exchange) + 1))
        if extensions is None:
            extensions = etree.SubElement(dataset, f"{{{EXT_NS}}}extensions")
        attributes = {"number": number}
        if original is not None:
            attributes["originalNumber"] = original
        etree.SubElement(extensions, f"{{{EXT_NS}}}exchange", attributes)
        _set(exchange, "number", number)


@import_fix(
    "location-codes",
    authored_by=AUTHOR,
    authorised_by=AUTHOR,
    rules=(
        Rule(
            "Location codes can be at most 7 characters long.",
            "TRegionalCode (maximum length 7): geography/@location, exchange/@location",
        ),
    ),
)
def fix_locations(dataset: etree._Element) -> None:
    """Replace location names that are too long for a regional code (max 7 characters)."""
    for el in (*dataset.iterfind(f"{_PROCESS}/geography"), *dataset.iterfind("flowData/exchange")):
        if (location := el.get("location")) in LOCATION_REMAPPING:
            _set(el, "location", LOCATION_REMAPPING[location])


def run_fix(
    fix: ImportFix,
    dataset: etree._Element,
    capture: bool = False,
    placeholders: Placeholders = DEFAULT_PLACEHOLDERS,
    sources: SourceIndex | None = None,
) -> tuple[list[Change], Snippet | None]:
    """Apply one fix to a raw dataset element; return its changes and, if asked, a snippet."""
    changes: list[Change] = []
    captured: dict = {}
    tokens = (
        _changes.set(changes),
        _capture.set(captured if capture else None),
        _placeholders.set(placeholders),
        _sources.set(sources or {}),
    )
    try:
        fix.func(dataset)
    finally:
        for var, token in zip((_changes, _capture, _placeholders, _sources), tokens, strict=True):
            var.reset(token)
    if not captured:
        return changes, None
    return changes, Snippet(captured["before"], snippet(captured["element"]))


def apply_import_fixes(
    dataset: etree._Element,
    capture: frozenset[str] = frozenset(),
    placeholders: Placeholders = DEFAULT_PLACEHOLDERS,
    sources: SourceIndex | None = None,
) -> list[tuple[ImportFix, list[Change], Snippet | None]]:
    """Apply all import fixes in order; return those that changed something.

    For fixes whose id is in `capture`, also return a before/after `Snippet`.
    """
    results = [
        (fix, *run_fix(fix, dataset, fix.id in capture, placeholders, sources))
        for fix in IMPORT_FIXES
    ]
    return [result for result in results if result[1]]
