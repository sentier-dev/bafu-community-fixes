"""Import, fix, patch and write, keeping a record of everything that changed.

1. Parse the raw XML.
2. Apply the import fixes (`import_fixes.py`) to the raw trees.
3. Build strict models. Anything that doesn't fit the schema stops the run here.
4. Apply community patches one at a time. After each patch, every dataset is
   revalidated, and any error is reported against that patch.
   the datasets it changed are checked against the XSD again.
5. Write EcoSpold 1 XML, with or without extensions.

Every step's changes go into a `RunLog`, which `report.py` renders as HTML.
"""

import hashlib
import logging
import zlib
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from bafu_community_fixes import compliance
from bafu_community_fixes.changes import Change, DatasetRef, RunLog, StepLog
from bafu_community_fixes.import_fixes import (
    DEFAULT_PLACEHOLDERS,
    IMPORT_FIXES,
    ImportFixError,
    Placeholders,
    apply_import_fixes,
    index_sources,
)
from bafu_community_fixes.models import Dataset, DatasetExtension
from bafu_community_fixes.progress import ProgressCallback, RunCancelled, tracker
from bafu_community_fixes.registry import Patch, available_patches
from bafu_community_fixes.xml import (
    Database,
    EcoSpoldError,
    build,
    find_files,
    flatten,
    parse,
    write,
)

logger = logging.getLogger(__name__)


class PatchError(Exception):
    def __init__(self, patch: Patch, messages: list[str]):
        self.patch, self.messages = patch, messages
        shown = "\n".join(f"  {m}" for m in messages[:50])
        super().__init__(f"Patch {patch.id} left invalid data:\n{shown}")


def _ext(dataset: Dataset) -> DatasetExtension:
    if dataset.ext is None:
        dataset.ext = DatasetExtension()
    return dataset.ext


def _ref(file: str, dataset: Dataset) -> DatasetRef:
    return DatasetRef(file, dataset.number, dataset.name, dataset.location)


def import_database(
    source: Path | str,
    strict: bool = False,
    log: RunLog | None = None,
    progress: ProgressCallback | None = None,
    placeholders: Placeholders = DEFAULT_PLACEHOLDERS,
) -> Database:
    """Read the raw release, apply the import fixes and build the models."""
    log = log or RunLog(str(source), {})
    steps = {
        fix.id: StepLog(
            fix.id,
            "import fix",
            fix.description,
            fix.rationale,
            fix.provenance,
            rules=fix.rules,
        )
        for fix in IMPORT_FIXES
    }
    log.steps.extend(steps.values())
    root, files = find_files(Path(source))
    fingerprint = hashlib.sha256()
    tracker(progress, "Indexing sources across the release")
    sources = index_sources(files)
    documents, errors = {}, []
    update = tracker(progress, "Reading and preparing the data", len(files))
    for done, path in enumerate(files, start=1):
        update(done)
        relative = str(path.relative_to(root))
        fingerprint.update(relative.encode() + b"\0" + path.read_bytes())
        try:
            tree = parse(path)
            applied = []
            for dataset in tree.iterfind("dataset"):
                capture = frozenset(i for i, step in steps.items() if step.snippet is None)
                applied.append(apply_import_fixes(dataset, capture, placeholders, sources))
            doc = build(tree, relative)
        except (EcoSpoldError, ImportFixError) as e:
            errors.extend(getattr(e, "messages", [f"{relative}: {e}"]))
            continue
        for index, (dataset, fixes) in enumerate(zip(doc.datasets, applied, strict=True)):
            if not fixes:
                continue
            _ext(dataset).import_fixes = [fix.id for fix, _, _ in fixes]
            log.changed_datasets.add((relative, index))
            for fix, changes, snippet in fixes:
                steps[fix.id].record(_ref(relative, dataset), changes)
                if snippet is not None:
                    steps[fix.id].snippet = (_ref(relative, dataset), snippet)
        documents[Path(relative)] = doc
    if errors:
        raise EcoSpoldError(errors)
    db = Database(documents)
    log.input_fingerprint = fingerprint.hexdigest()
    log.files, log.datasets = len(documents), len(db)
    log.exchanges = sum(len(d.exchanges) for d in db)
    logger.info("Imported %d datasets from %d files", len(db), len(documents))
    if strict:
        documents_list = [(str(p), d) for p, d in db.documents.items()]
        compliance.check(documents_list, "after import", progress)
        for step in steps.values():
            step.xsd_checked = len(db)
        logger.info("All documents are XSD-compliant after import")
    return db


def select_patches(
    only: Iterable[str] | None = None, skip: Iterable[str] | None = None
) -> list[Patch]:
    patches = available_patches()
    known = {p.id for p in patches}
    only, skip = set(only or ()), set(skip or ())
    if unknown := (only | skip) - known:
        raise KeyError(f"Unknown patch id(s): {', '.join(sorted(unknown))}")
    return [p for p in patches if (not only or p.id in only) and p.id not in skip]


def _snapshot(dataset: Dataset) -> bytes:
    return zlib.compress(dataset.model_dump_json().encode(), level=1)


def _diff(before: dict[str, str], after: dict[str, str]) -> list[Change]:
    return [
        Change(path, before.get(path), after.get(path))
        for path in sorted(before.keys() | after.keys())
        if before.get(path) != after.get(path)
    ]


def apply_patch(
    db: Database,
    patch: Patch,
    strict: bool = False,
    log: RunLog | None = None,
    progress: ProgressCallback | None = None,
) -> list[Dataset]:
    """Apply one patch, revalidate everything, and record what changed."""
    step = StepLog(
        patch.id,
        "patch",
        patch.description,
        patch.rationale,
        patch.provenance,
        rules=patch.rules,
        evidence=patch.evidence,
    )
    if log is not None:
        log.steps.append(step)
    located = [
        (str(path), index, dataset)
        for path, doc in db.documents.items()
        for index, dataset in enumerate(doc.datasets)
    ]
    update = tracker(progress, f"Patch {patch.id}: taking a snapshot", len(located))
    before = {}
    for done, (_, _, dataset) in enumerate(located, start=1):
        before[id(dataset)] = _snapshot(dataset)
        update(done)
    tracker(progress, f"Patch {patch.id}: applying")
    patch(db)
    errors = []
    update = tracker(
        progress, f"Patch {patch.id}: checking the result", len(db.documents) + len(located)
    )
    for done, (path, doc) in enumerate(db.documents.items(), start=1):
        update(done)
        try:
            type(doc).model_validate(doc)
        except ValidationError as e:
            errors.extend(
                f"{path}: {'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()
            )
    if errors:
        raise PatchError(patch, errors)

    changed = []
    for done, (file, index, dataset) in enumerate(located, start=len(db.documents) + 1):
        update(done)
        old = before.get(id(dataset))
        if old == _snapshot(dataset):
            continue
        previous = Dataset.model_validate_json(zlib.decompress(old)) if old else None
        changes = _diff(flatten(previous) if previous else {}, flatten(dataset))
        _ext(dataset).patches = [*_ext(dataset).patches, patch.id]
        step.record(_ref(file, dataset), changes)
        if log is not None:
            log.changed_datasets.add((file, index))
        changed.append(dataset)
    if strict:
        compliance.check(
            [(f"dataset {d.number}", d) for d in changed], f"after patch {patch.id}", progress
        )
        step.xsd_checked = len(changed)
    logger.info("Patch %s changed %d datasets", patch.id, len(changed))
    return changed


# How often to check against the official XSD, as an independent second check of the
# models: never, once on the final result, or after import and after every patch (which
# names the step that broke the data, but is slowest).
XSD_CHECKS = {
    "off": "not checked",
    "end": "once, on the final result",
    "every-step": "after import and after every patch",
}


def run(
    source: Path | str,
    destination: Path | str,
    only: Iterable[str] | None = None,
    skip: Iterable[str] | None = None,
    extensions: bool = True,
    xsd_check: str = "off",
    report: Path | str | None = None,
    progress: ProgressCallback | None = None,
    placeholders: Placeholders = DEFAULT_PLACEHOLDERS,
) -> RunLog:
    """Run the whole pipeline. With `report`, also write an HTML report there.

    `xsd_check` is one of `XSD_CHECKS`. With "end", the result is checked once,
    after all patches and before anything is written. The report is written even if
    the run fails, so the failure can be shared.
    """
    if xsd_check not in XSD_CHECKS:
        raise ValueError(f"xsd_check must be one of {', '.join(XSD_CHECKS)}, not {xsd_check!r}")
    every_step = xsd_check == "every-step"
    log = RunLog(
        str(source),
        {
            "XSD schema check": XSD_CHECKS[xsd_check],
            "extensions in output": extensions,
            "only patches": ", ".join(only) if only else "all",
            "skipped patches": ", ".join(skip) if skip else "none",
            "placeholders for missing data": placeholders.describe(),
        },
    )
    try:
        db = import_database(
            source, strict=every_step, log=log, progress=progress, placeholders=placeholders
        )
        for patch in select_patches(only, skip):
            apply_patch(db, patch, strict=every_step, log=log, progress=progress)
        if xsd_check == "end":
            documents = [(str(p), d) for p, d in db.documents.items()]
            compliance.check(documents, "after all patches", progress)
            log.xsd_final_checked = len(db)
        written = write(db, destination, extensions=extensions, progress=progress)
        log.destination, log.written = str(destination), len(written)
        log.status = "completed"
    except RunCancelled:
        log.status, log.error = "cancelled", "The run was cancelled before it finished."
        raise
    except Exception as e:
        log.status, log.error = "failed", str(e)
        raise
    finally:
        log.finished = datetime.now().astimezone()
        if report is not None:
            from bafu_community_fixes.report import write_report

            tracker(progress, "Writing the report")
            write_report(log, report)
    return log
