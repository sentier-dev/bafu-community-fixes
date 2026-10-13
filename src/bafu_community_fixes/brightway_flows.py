"""brightway-flows data for BAFU 2026 v1, built by `scripts/build_brightway_flows_data.py`.

The data comes from Brightway Flows (https://github.com/brightway-labs/brightway-flows),
used with its author's permission (see `data/README.md`).
"""

import csv
import json
import re
from functools import cache

from bafu_community_fixes.changes import Evidence
from bafu_community_fixes.models import Exchange
from bafu_community_fixes.registry import data_file
from bafu_community_fixes.xml import Database

RELEASE = "bafu-2026-v1"
FLOW_IRI = "https://vocab.brightway.dev/elementary-flows/"
FLOW_PAGE = "https://flows.brightway.dev/flows/"

KEY_FIELDS = ("name", "category", "subCategory", "unit")

type FlowKey = tuple[str, str, str, str]


def attributes(exchange: Exchange) -> dict[str, str]:
    """An elementary exchange's flow attributes, under their EcoSpold names."""
    return {
        "name": exchange.name,
        "category": exchange.category or "",
        "subCategory": exchange.sub_category or "",
        "unit": exchange.unit,
        "CASNumber": exchange.cas_number or "",
    }


def flow_key(exchange: Exchange) -> FlowKey:
    """An elementary flow as BAFU identifies it: name, category, subCategory and unit."""
    flow = attributes(exchange)
    return tuple(flow[f] for f in KEY_FIELDS)


def matches(flow: dict[str, str], match: dict[str, str]) -> bool:
    """Whether a correction's `match` applies to a flow's attributes.

    `context` matches either the category or the subCategory, and `cas_numbers`
    compares CAS numbers without leading zeros, as brightway-flows does.
    """
    for field, value in match.items():
        if field == "context":
            if value not in (flow["category"], flow["subCategory"]):
                return False
        elif field == "cas_numbers":
            if cas_digits(flow.get("CASNumber", "")) != cas_digits(value):
                return False
        elif flow[field] != value:
            return False
    return True


@cache
def crosswalk() -> dict[FlowKey, dict[str, str]]:
    """BAFU flow → `bafu_flow_uuid`, `brightway_flow_id` and `match`."""
    with data_file(f"brightway-flows-crosswalk-{RELEASE}.csv").open(newline="") as f:
        return {
            (r["name"], r["category"], r["subCategory"], r["unit"]): r for r in csv.DictReader(f)
        }


@cache
def corrections() -> dict:
    """The brightway-flows corrections to apply, and those excluded, with reasons."""
    return json.loads(data_file(f"brightway-flows-corrections-{RELEASE}.json").read_text())


def cas_digits(cas: str) -> str:
    """A CAS number without leading zeros, for comparing: `000124-38-9` → `124-38-9`."""
    if not cas:
        return ""
    return re.sub(r"^0+(?=\d)", "", cas.strip())


def bafu_cas(cas: str) -> str:
    """A CAS number in BAFU's usual style, zero-padded to six digits: `000124-38-9`."""
    first, rest = cas_digits(cas).split("-", 1)
    return f"{first.zfill(6)}-{rest}"


def _apply(exchange: Exchange, correction: dict, where: str) -> None:
    field = correction["field"]
    original = correction.get("original_value")
    if field == "cas_numbers":
        current = cas_digits(exchange.cas_number) if exchange.cas_number else None
        if "remove_value" in correction:
            if current == correction["remove_value"]:
                exchange.cas_number = None
            return
        (new,) = correction["new_value"]
        if current is not None and current not in {*(original or []), new}:
            raise ValueError(f"{where}: unexpected CAS number {exchange.cas_number}")
        exchange.cas_number = bafu_cas(new)
    elif field == "name":
        exchange.name = correction["new_value"]
    elif field == "context":
        current = [exchange.category, exchange.sub_category]
        if original is not None and current != original:
            raise ValueError(f"{where}: expected {original}, found {current}")
        exchange.category, exchange.sub_category = correction["new_value"]
    else:
        raise ValueError(f"Can't apply a correction to {field}")


def apply_corrections(db: Database, kind: str) -> None:
    """Apply the brightway-flows corrections of one `kind` to all elementary exchanges.

    Corrections are matched on BAFU's own flow attributes, never on the crosswalk.
    A correction that finds an unexpected value stops the run.
    """
    rules = [c for c in corrections()["corrections"] if c["kind"] == kind]
    if not rules:
        raise ValueError(f"No corrections of kind {kind!r}")
    for dataset in db:
        for exchange in dataset.exchanges:
            if not exchange.is_elementary:
                continue
            for correction in rules:
                if matches(attributes(exchange), correction["match"]):
                    _apply(exchange, correction, f"Dataset {dataset.number}, {exchange.name!r}")


def _describe(correction: dict) -> tuple[str, str]:
    match, field = correction["match"], correction["field"]
    subject = match["name"]
    where = [match[k] for k in ("category", "subCategory", "context") if k in match]
    if where:
        subject += f" ({' / '.join(where)})"
    if "unit" in match:
        subject += f", in {match['unit']}"
    if field == "cas_numbers":
        if "remove_value" in correction:
            return subject, f"CAS number `{correction['remove_value']}` removed"
        (new,) = correction["new_value"]
        old = " or ".join(f"`{v}`" for v in correction.get("original_value") or []) or "none"
        return subject, f"CAS number {old} → `{new}`"
    if field == "name":
        return subject, f"Renamed to `{correction['new_value']}`"
    old = " / ".join(correction.get("original_value") or [])
    return subject, f"Compartment {old} → {' / '.join(correction['new_value'])}"


def evidence(kind: str) -> tuple[Evidence, ...]:
    """The corrections of one kind, each with links to its Brightway Flows flows.

    A correction that covers several Brightway Flows flows (one substance in several
    compartments) gets one link per flow, labelled with its compartment.
    """
    items = []
    for correction in corrections()["corrections"]:
        if correction["kind"] != kind:
            continue
        flows = correction.get("brightway_flows", [])
        links = tuple(
            ("Brightway Flows" if len(flows) == 1 else f["compartment"], FLOW_PAGE + f["id"])
            for f in flows
        )
        items.append(Evidence(*_describe(correction), links))
    return tuple(items)
