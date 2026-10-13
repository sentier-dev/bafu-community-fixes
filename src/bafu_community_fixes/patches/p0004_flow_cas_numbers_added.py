"""Add missing CAS numbers to 28 elementary flows."""

from bafu_community_fixes.brightway_flows import apply_corrections, evidence
from bafu_community_fixes.registry import patch
from bafu_community_fixes.xml import Database

ID = "0004-flow-cas-numbers-added"


@patch(
    ID,
    authored_by="Claude Code",
    evidence=evidence("cas-added"),
    authorised_by="Chris Mutel",
    reported_by="Chris Mutel, Brightway Flows",
    references=(
        "https://github.com/brightway-labs/brightway-flows/blob/main/docs/changes/bafu-2026-v1.md",
        "https://github.com/brightway-labs/brightway-flows/issues/103",
        "https://github.com/brightway-labs/brightway-flows/issues/177",
    ),
)
def flow_cas_numbers_added(db: Database) -> None:
    """Add missing CAS numbers to 28 elementary flows (brightway-flows).

    BAFU leaves the CAS number off flows whose substance is known under another name
    (`Arsine` for hydrogen arsenide, `Methyl mercaptan` for methanethiol, …), off
    some ions (`Arsenic V`, `Calcium II`, …), and off `Carbon dioxide, biogenic`,
    `Carbon dioxide, land transformation` and `Carbon monoxide, biogenic`. Without the
    number, each becomes a separate, uncharacterised substance for software that
    matches flows. `1-Pentanol` and `Nitrogen monoxide` can't be told apart from
    related substances by name alone, so the number is what identifies them.

    Matched on BAFU's own flow attributes, so this doesn't depend on the brightway-flows
    crosswalk. Each correction's reasoning is in
    `data/brightway-flows-corrections-bafu-2026-v1.json`.
    """
    apply_corrections(db, "cas-added")
