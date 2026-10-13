"""Move `Carbon dioxide, in air` to the `in air` resource compartment."""

from bafu_community_fixes.brightway_flows import apply_corrections, evidence
from bafu_community_fixes.registry import patch
from bafu_community_fixes.xml import Database

ID = "0008-flow-compartments"


@patch(
    ID,
    authored_by="Claude Code",
    evidence=evidence("compartment"),
    authorised_by="Chris Mutel",
    reported_by="Chris Mutel, Brightway Flows",
    references=(
        "https://github.com/brightway-labs/brightway-flows/blob/main/docs/changes/bafu-2026-v1.md",
        "https://github.com/brightway-labs/brightway-flows/issues/135",
    ),
)
def flow_compartments(db: Database) -> None:
    """Move `Carbon dioxide, in air` to the `in air` resource compartment (brightway-flows).

    The name says the carbon comes from the air, but some exchanges file it under
    `resources / biotic` or `resources / unspecified`. The main flow is under
    `resources / in air`, so these become the same flow.

    Matched on BAFU's own flow attributes, so this doesn't depend on the brightway-flows
    crosswalk. Each correction's reasoning is in
    `data/brightway-flows-corrections-bafu-2026-v1.json`.
    """
    apply_corrections(db, "compartment")
