"""Recording what a pipeline run changed, for the run report.

Every change is recorded as an XML path relative to its dataset, plus the old
and new values in their XML form. The path looks like
`flowData/exchange[3]/@CASNumber`; there's an index only where an element
repeats. Import fixes and patches use the same path format, so their changes can
be compared directly.

Some steps change hundreds of thousands of values, so a run doesn't keep every
change. It keeps, per step:

* the number of datasets and values changed
* for each field, the most common old -> new transitions, with counts
* the complete list of changes for the first `EXAMPLES` datasets it changed
"""

import platform
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from importlib.metadata import version

EXAMPLES = 10
MAX_TRANSITIONS = 1000  # distinct transitions tracked per field; the rest are counted as "other"


@dataclass(frozen=True, slots=True)
class Change:
    path: str
    old: str | None  # None: didn't exist before
    new: str | None  # None: removed

    @property
    def field(self) -> str:
        """The path without indices, e.g. `flowData/exchange/@CASNumber`."""
        return re.sub(r"\[\d+\]", "", self.path)


@dataclass(frozen=True)
class DatasetRef:
    file: str
    number: int | str | None
    name: str | None
    location: str | None


@dataclass(frozen=True)
class Rule:
    """Why a step changes data, in plain language.

    `schema` is True for rules the EcoSpold 1 schema enforces, and False for our
    own conventions (things the schema allows, but that we change anyway).
    `reference` points to the relevant part of the XSD, for readers who want to check.
    """

    text: str
    reference: str = ""
    schema: bool = True


@dataclass(frozen=True)
class Evidence:
    """One specific change a step makes, with links to where it's explained."""

    subject: str  # what is changed, e.g. a flow
    change: str  # how, e.g. "CAS number 7440-43-9 → 22537-48-0"
    links: tuple[tuple[str, str], ...] = ()  # (label, url)


@dataclass(frozen=True)
class Snippet:
    """An element as XML before and after a step changed it."""

    before: str
    after: str


@dataclass
class FieldStats:
    changes: int = 0
    transitions: Counter = field(default_factory=Counter)
    other: int = 0

    def add(self, change: Change) -> None:
        self.changes += 1
        key = (change.old, change.new)
        if key in self.transitions or len(self.transitions) < MAX_TRANSITIONS:
            self.transitions[key] += 1
        else:
            self.other += 1


@dataclass(frozen=True)
class Provenance:
    """Who is behind a change.

    * `authored_by`: who wrote the patch or fix.
    * `authorised_by`: who approved it for this community release (None: not yet).
    * `references`: links to the issue, discussion or evidence.
    * `reported_by`: who found the problem, if someone else.
    * `confirmed_by`: who confirmed the problem or the correction for the data owner
      (e.g. BAFU), and how.
    """

    authored_by: str
    authorised_by: str | None = None
    references: tuple[str, ...] = ()
    reported_by: str | None = None
    confirmed_by: str | None = None


@dataclass
class StepLog:
    """What one import fix or patch did during a run."""

    id: str
    kind: str  # "import fix" or "patch"
    description: str
    rationale: str
    provenance: Provenance
    datasets: int = 0
    changes: int = 0
    fields: dict[str, FieldStats] = field(default_factory=dict)
    examples: list[tuple[DatasetRef, list[Change]]] = field(default_factory=list)
    xsd_checked: int | None = None  # datasets checked against the XSD after this step
    snippet: tuple[DatasetRef, Snippet] | None = None  # first changed element, before/after
    rules: tuple[Rule, ...] = ()
    evidence: tuple[Evidence, ...] = ()

    def record(self, dataset: DatasetRef, changes: list[Change]) -> None:
        if not changes:
            return
        self.datasets += 1
        self.changes += len(changes)
        for change in changes:
            self.fields.setdefault(change.field, FieldStats()).add(change)
        if len(self.examples) < EXAMPLES:
            self.examples.append((dataset, changes))


def _git_commit() -> str | None:
    import subprocess
    from pathlib import Path

    here = Path(__file__).parent
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=here, capture_output=True, text=True
        )
        if commit.returncode != 0:
            return None
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=here,
            capture_output=True,
            text=True,
        ).stdout.strip()
        return commit.stdout.strip() + (" (with uncommitted changes)" if dirty else "")
    except OSError:
        return None


@dataclass
class RunLog:
    """Everything a run report shows."""

    source: str
    options: dict[str, object]
    started: datetime = field(default_factory=lambda: datetime.now().astimezone())
    finished: datetime | None = None
    status: str = "running"  # "completed", "failed" or "cancelled"
    error: str | None = None
    input_fingerprint: str | None = None
    files: int = 0
    datasets: int = 0
    exchanges: int = 0
    changed_datasets: set[tuple[str, int]] = field(default_factory=set)
    steps: list[StepLog] = field(default_factory=list)
    destination: str | None = None
    written: int = 0
    xsd_final_checked: int | None = None  # datasets checked against the XSD at the end
    software: dict[str, str] = field(
        default_factory=lambda: {
            "bafu-community-fixes": version("bafu-community-fixes"),
            "git commit": _git_commit() or "not available",
            "Python": platform.python_version(),
            "pydantic": version("pydantic"),
            "lxml": version("lxml"),
            "platform": platform.platform(terse=True),
        }
    )

    @property
    def duration(self) -> float | None:
        return None if self.finished is None else (self.finished - self.started).total_seconds()
