"""Build the brightway-flows data files used by the elementary flow patches.

Everything comes from public, pinned sources, so anyone can rebuild the files:

* the brightway-flows fix files, from GitHub at `BRIGHTWAY_FLOWS_COMMIT`, checked
  against their git blob hashes;
* the brightway-flows 1.0.0 release (`harmonised-flows-simple.json.gz`) from
  Zenodo, checked against its MD5 checksum, for the BAFU crosswalk;
* the BAFU release, downloaded like `bafu-fixes run latest` does.

Downloads are cached in the user cache folder. Writes two files to
`src/bafu_community_fixes/data/`:

* `brightway-flows-corrections-bafu-2026-v1.json`: the brightway-flows corrections
  that change what a flow is (CAS numbers, names, compartments), with their
  reasoning and a `kind` that says which patch applies them. They are matched on
  BAFU's own flow attributes, not brightway-flows identifiers, so they don't depend
  on the crosswalk. Unit changes are left to downstream users; corrections that only
  affect matching, or depend on open questions to BAFU, are listed as excluded.
* `brightway-flows-crosswalk-bafu-2026-v1.csv`: every BAFU elementary flow, as
  BAFU ships it (name, category, subCategory, unit), with its brightway-flows
  source UUID and the brightway-flows elementary flow it corresponds to. Flows the
  corrections rename or move get a second row under their new attributes.

Usage:
    uv run python scripts/build_brightway_flows_data.py
    uv run python scripts/build_brightway_flows_data.py --brightway-flows ~/Code/brightway-flows

With `--brightway-flows`, the fix files and the crosswalk are read from a local
checkout and its build output instead (for trying unreleased fixes).
"""

import argparse
import csv
import gzip
import hashlib
import importlib.util
import json
import re
import sys
import urllib.request
import uuid
from pathlib import Path

from lxml import etree

from bafu_community_fixes.brightway_flows import KEY_FIELDS, matches
from bafu_community_fixes.download import cache_dir, latest_release

DATA = Path(__file__).parents[1] / "src" / "bafu_community_fixes" / "data"
RELEASE = "bafu-2026-v1"

BRIGHTWAY_FLOWS_COMMIT = "19d6cc6268e59e18fcbb47bfec0f440fb0f6a353"
GITHUB_RAW = (
    f"https://raw.githubusercontent.com/brightway-labs/brightway-flows/{BRIGHTWAY_FLOWS_COMMIT}/"
)
# path in the repository: git blob hash at BRIGHTWAY_FLOWS_COMMIT
GITHUB_FILES = {
    "src/brightway_flows/data/bafu-2026-v1-manual-fixes.json": (
        "14cea8ffdc73acd950cd299ffde8eba717c278af"
    ),
    "src/brightway_flows/data/simapro-lineage-manual-fixes.json": (
        "36fb79239104c9850c97d837ce9dca561d90f839"
    ),
    "src/brightway_flows/simapro_names.py": "8669c3691bdf682bcb24330c1e18adae393da7ca",
}
ZENODO_DOI = "10.5281/zenodo.22857950"
ZENODO_FILE = (
    "https://zenodo.org/api/records/22857950/files/harmonised-flows-simple.json.gz/content"
)
ZENODO_MD5 = "d303eb7e2275c590f5b10274c3d35f08"

BAFU_FLOW_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://vocab.brightway.one/bafu/")
SOURCE_IRI = "https://vocab.brightway.one/bafu/2026-v1/flow/"
TARGET_IRI = "https://vocab.brightway.dev/elementary-flows/"
FIELDS = {"cas_numbers", "name", "context"}

# match name: reason, for corrections of those fields that we don't apply to the data
EXCLUDED = {
    "Energy, waste heat, air": (
        "Renaming it to `Heat, waste` only makes sense together with moving it from "
        "resources to emissions, which reverses its direction; brightway-flows does that "
        "only when matching."
    ),
    "Water, process, unspecified natural origin/kg": (
        "Open question to BAFU: the /kg and /m3 process-water rows may count the same "
        "water twice (brightway-flows #67)."
    ),
    "Water, process, unspecified natural origin/m3": (
        "Open question to BAFU: the /kg and /m3 process-water rows may count the same "
        "water twice (brightway-flows #67)."
    ),
}


# --- Sources ---------------------------------------------------------------------------


def _download(url: str, target: Path, check) -> Path:
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {url}")
        with urllib.request.urlopen(url, timeout=120) as response:
            content = response.read()
        if not check(content):
            raise OSError(f"{url} doesn't match its expected checksum")
        target.write_bytes(content)
    return target


def _git_blob_hash(content: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()


def github_files() -> dict[str, Path]:
    """The pinned brightway-flows files, by their path in the repository."""
    folder = cache_dir() / "brightway-flows" / BRIGHTWAY_FLOWS_COMMIT
    return {
        path: _download(
            GITHUB_RAW + path,
            folder / path,
            lambda content, blob=blob: _git_blob_hash(content) == blob,
        )
        for path, blob in GITHUB_FILES.items()
    }


def zenodo_release() -> Path:
    target = cache_dir() / "brightway-flows" / "zenodo-22857950" / "harmonised-flows-simple.json.gz"
    return _download(
        ZENODO_FILE, target, lambda content: hashlib.md5(content).hexdigest() == ZENODO_MD5
    )


def local_checkout(path: Path) -> tuple[dict[str, Path], Path]:
    return {p: path / p for p in GITHUB_FILES}, path / "harmonised-flows-simple.json.gz"


# --- Crosswalk ---------------------------------------------------------------------------


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses look the module up while it loads
    spec.loader.exec_module(module)
    return module


def flow_uuid(name: str, category: str, sub_category: str, unit: str, split) -> str:
    """brightway-flows' identifier for one BAFU flow (`integrations/bafu.py:_flow_uuid`)."""
    location = ""
    if (parts := split(name)) is not None:
        name, location = parts
    fields = (name, category, sub_category, unit)
    return str(
        uuid.uuid5(BAFU_FLOW_NAMESPACE, "|".join((*fields, location) if location else fields))
    )


def elementary_flows(release: Path) -> dict[tuple[str, str, str, str], int]:
    """Every distinct (name, category, subCategory, unit) of elementary exchanges."""
    counts: dict[tuple[str, str, str, str], int] = {}
    for path in sorted(release.glob("*.xml")):
        for exchange in etree.parse(str(path)).getroot().iter("exchange"):
            groups = [g.text for g in exchange if g.tag in ("inputGroup", "outputGroup")]
            if groups != ["4"]:
                continue
            key = tuple(exchange.get(a, "") for a in KEY_FIELDS)
            counts[key] = counts.get(key, 0) + 1
    return counts


def crosswalk(harmonised: Path, simapro_names: Path, release: Path) -> list[dict]:
    split = load_module(simapro_names, "simapro_names").split_geography_suffix
    with gzip.open(harmonised) as f:
        data = json.load(f)
    (correspondence,) = [
        c for c in data["correspondences"] if c["@id"].endswith(f"/correspondences/{RELEASE}")
    ]
    targets = {}
    for row in correspondence["xkos:madeOf"]:
        source = row["xkos:sourceConcept"]
        (kind,) = [k.removeprefix("skos:") for k in source if re.fullmatch(r"skos:\w+Match", k)]
        targets[source["@id"].removeprefix(SOURCE_IRI)] = (
            row["xkos:targetConcept"]["@id"].removeprefix(TARGET_IRI),
            kind,
        )
    rows = []
    for key, n in sorted(elementary_flows(release).items()):
        source_uuid = flow_uuid(*key, split)
        target, kind = targets.get(source_uuid, ("", ""))
        rows.append(
            dict(zip(KEY_FIELDS, key, strict=True))
            | {"key": "as shipped", "exchanges": n, "bafu_flow_uuid": source_uuid}
            | {"brightway_flow_id": target, "match": kind}
        )
    return rows


def corrected_rows(rows: list[dict], included: list[dict]) -> list[dict]:
    """Crosswalk rows for flows as the corrections rename or move them.

    So linking works whether or not the corrections have been applied.
    """
    known = {tuple(r[f] for f in KEY_FIELDS) for r in rows}
    extra = []
    for row in rows:
        attributes = {f: row[f] for f in KEY_FIELDS}
        for correction in included:
            if correction["field"] == "name" and matches(attributes, correction["match"]):
                attributes["name"] = correction["new_value"]
            elif correction["field"] == "context" and matches(attributes, correction["match"]):
                attributes["category"], attributes["subCategory"] = correction["new_value"]
        key = tuple(attributes[f] for f in KEY_FIELDS)
        if key not in known:
            known.add(key)
            extra.append(row | attributes | {"key": "after corrections", "exchanges": 0})
    return extra


# --- Corrections ---------------------------------------------------------------------


def flows_for(correction: dict, rows: list[dict]) -> list[dict]:
    """The Brightway Flows flows of the BAFU flows a correction applies to.

    Each with the BAFU compartment it comes from. CAS numbers are per exchange, not
    in the crosswalk, so a `cas_numbers` match is left out here.
    """
    match = {k: v for k, v in correction["match"].items() if k != "cas_numbers"}
    flows = {}
    for r in rows:
        if r["brightway_flow_id"] and matches({f: r[f] for f in KEY_FIELDS}, match):
            compartment = f"{r['category']} / {r['subCategory']}"
            flows.setdefault(r["brightway_flow_id"], set()).add(compartment)
    return [
        {"id": flow, "compartment": ", ".join(sorted(compartments))}
        for flow, compartments in sorted(flows.items(), key=lambda kv: sorted(kv[1]))
    ]


def native_match(match: dict, uuids: dict[str, dict]) -> dict:
    """Replace a brightway-flows UUID in a match with BAFU's own flow attributes."""
    if "uuid" not in match:
        return match
    row = uuids[match["uuid"]]
    native = {f: row[f] for f in KEY_FIELDS}
    if match.get("name", native["name"]) != native["name"]:
        raise ValueError(f"UUID {match['uuid']} isn't {match['name']!r}")
    return native


def kind(fix: dict) -> str:
    """Which patch applies a correction."""
    if fix["field"] == "cas_numbers":
        if "remove_value" in fix:
            return "cas-removed"
        return "cas-replaced" if fix.get("original_value") else "cas-added"
    return {"name": "name", "context": "compartment"}[fix["field"]]


def corrections(fix_files: list[Path], rows: list[dict]) -> tuple[list[dict], list[dict]]:
    uuids = {r["bafu_flow_uuid"]: r for r in rows}
    included, excluded = [], []
    for path in fix_files:
        with open(path) as f:
            fixes = json.load(f)["fixes"]
        for fix in fixes:
            entry = {
                "source": path.name,
                "match": native_match(fix["match"], uuids),
                "field": fix["field"],
                **{k: fix[k] for k in ("original_value", "new_value", "remove_value") if k in fix},
                "comment": fix.get("comment", ""),
                "issues": sorted(set(re.findall(r"#(\d+)", fix.get("comment", ""))), key=int),
            }
            name = fix["match"].get("name")
            if fix["field"] not in FIELDS:
                reason = {
                    "unit": "Unit changes are left to downstream users.",
                    "synonyms": "Synonyms only affect how brightway-flows matches flows.",
                }.get(fix["field"], f"Field {fix['field']} isn't applied to the data.")
                excluded.append(entry | {"reason": reason})
            elif name in EXCLUDED:
                excluded.append(entry | {"reason": EXCLUDED[name]})
            elif path.name.startswith("simapro") and fix["field"] == "name":
                excluded.append(
                    entry | {"reason": "A brightway-flows naming convention, used for matching."}
                )
            else:
                included.append({"kind": kind(fix)} | entry)
    return included, excluded


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--brightway-flows", type=Path, help="local brightway-flows checkout")
    parser.add_argument("--bafu", type=Path, help="BAFU release folder (default: latest)")
    args = parser.parse_args()

    if args.brightway_flows:
        files, harmonised = local_checkout(args.brightway_flows.expanduser())
        source = f"local checkout {args.brightway_flows}"
    else:
        files, harmonised = github_files(), zenodo_release()
        source = f"commit {BRIGHTWAY_FLOWS_COMMIT}; release DOI {ZENODO_DOI}"
    release = args.bafu.expanduser() if args.bafu else latest_release()

    rows = crosswalk(harmonised, files["src/brightway_flows/simapro_names.py"], release)
    fix_files = [files[p] for p in GITHUB_FILES if p.endswith(".json")]
    included, excluded = corrections(fix_files, rows)
    for correction in included:
        correction["brightway_flows"] = flows_for(correction, rows)
    rows += corrected_rows(rows, included)

    with open(DATA / f"brightway-flows-crosswalk-{RELEASE}.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    unmatched = [r for r in rows if not r["brightway_flow_id"]]
    print(f"{len(rows)} crosswalk rows, {len(unmatched)} without a brightway-flows match")

    document = {
        "description": (
            "brightway-flows corrections for BAFU 2026 v1 elementary flows that change what "
            "a flow is. `kind` says which patch applies each one. Generated by "
            "scripts/build_brightway_flows_data.py; do not edit by hand."
        ),
        "source": f"https://github.com/brightway-labs/brightway-flows ({source})",
        "license": (
            "Brightway Flows data (ODbL-1.0), used in bafu-community-fixes with its author's "
            "permission; pipeline output follows the BAFU licensing"
        ),
        "corrections": included,
        "excluded": excluded,
    }
    path = DATA / f"brightway-flows-corrections-{RELEASE}.json"
    path.write_text(json.dumps(document, indent=1, ensure_ascii=False) + "\n")
    counts = {
        k: sum(c["kind"] == k for c in included) for k in sorted({c["kind"] for c in included})
    }
    print(f"{len(included)} corrections {counts}, {len(excluded)} excluded")


if __name__ == "__main__":
    main()
