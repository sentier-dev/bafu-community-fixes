"""Remove units from 3 elementary flow names."""

from bafu_community_fixes.brightway_flows import apply_corrections, evidence
from bafu_community_fixes.registry import patch
from bafu_community_fixes.xml import Database

ID = "0007-flow-names"


@patch(
    ID,
    authored_by="Claude Code",
    evidence=evidence("name"),
    authorised_by="Chris Mutel",
    reported_by="Chris Mutel, Brightway Flows",
    references=(
        "https://github.com/brightway-labs/brightway-flows/blob/main/docs/changes/bafu-2026-v1.md",
        "https://github.com/brightway-labs/brightway-flows/issues/67",
    ),
)
def flow_names(db: Database) -> None:
    """Remove units from 3 elementary flow names (brightway-flows).

    `Gas, natural/m3` and `Gas, mine, off-gas, process, coal mining/m3` say m3 in the
    name while their unit is Nm3 (on those exchanges only), and
    `Wood, unspecified, standing/kg` repeats its unit. The unit belongs in the unit
    field; names without it match the same substance in other flow lists. Units
    themselves are not changed.

    Matched on BAFU's own flow attributes, so this doesn't depend on the brightway-flows
    crosswalk. Each correction's reasoning is in
    `data/brightway-flows-corrections-bafu-2026-v1.json`.
    """
    apply_corrections(db, "name")
