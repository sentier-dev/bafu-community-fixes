"""Checking against the official EcoSpold 1 XSD.

The models enforce the schema themselves. This is an independent second check:
the XSD is the reference, the models are our reading of it.
"""

from collections.abc import Sequence
from functools import cache

from lxml import etree

from bafu_community_fixes.models import Dataset, EcoSpold
from bafu_community_fixes.progress import ProgressCallback, tracker
from bafu_community_fixes.xml import to_tree
from bafu_community_fixes.xsd import SCHEMA_DIR


class ComplianceError(Exception):
    def __init__(self, stage: str, messages: list[str]):
        self.stage, self.messages = stage, messages
        shown = "\n".join(f"  {m}" for m in messages[:50])
        more = f"\n  ... and {len(messages) - 50} more" if len(messages) > 50 else ""
        super().__init__(f"Not XSD-compliant {stage}: {len(messages)} error(s)\n{shown}{more}")


@cache
def schema() -> etree.XMLSchema:
    return etree.XMLSchema(etree.parse(str(SCHEMA_DIR / "EcoSpold01Dataset.xsd")))


def xsd_errors(doc: EcoSpold, label: str = "") -> list[str]:
    """XSD errors for a document, as written with extensions."""
    xsd = schema()
    if xsd.validate(to_tree(doc, extensions=True)):
        return []
    return [f"{label}: line {e.line}: {e.message}" for e in xsd.error_log]


def check(
    docs: Sequence[tuple[str, EcoSpold | Dataset]],
    stage: str,
    progress: ProgressCallback | None = None,
) -> None:
    """Raise `ComplianceError` if any document or dataset fails the XSD."""
    errors = []
    update = tracker(progress, f"Checking against the EcoSpold schema {stage}", len(docs))
    for done, (label, item) in enumerate(docs, start=1):
        update(done)
        doc = EcoSpold(datasets=[item]) if isinstance(item, Dataset) else item
        errors.extend(xsd_errors(doc, label))
    if errors:
        raise ComplianceError(stage, errors)
