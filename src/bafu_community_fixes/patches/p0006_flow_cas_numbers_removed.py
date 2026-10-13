"""Remove CAS numbers that name a different substance, from 3 elementary flows."""

from bafu_community_fixes.brightway_flows import apply_corrections, evidence
from bafu_community_fixes.registry import patch
from bafu_community_fixes.xml import Database

ID = "0006-flow-cas-numbers-removed"


@patch(
    ID,
    authored_by="Claude Code",
    evidence=evidence("cas-removed"),
    authorised_by="Chris Mutel",
    reported_by="Chris Mutel, Brightway Flows",
    references=(
        "https://github.com/brightway-labs/brightway-flows/blob/main/docs/changes/bafu-2026-v1.md",
        "https://github.com/brightway-labs/brightway-flows/issues/57",
        "https://github.com/brightway-labs/brightway-flows/issues/80",
        "https://github.com/brightway-labs/brightway-flows/issues/183",
    ),
)
def flow_cas_numbers_removed(db: Database) -> None:
    """Remove CAS numbers naming a different substance, from 3 elementary flows (brightway-flows).

    * `Nitrogen, organic bound` carries the number of nitrogen gas (N2). Organically
      bound nitrogen is a measurement over many compounds and has no CAS number.
    * Coal-mine gas (`Gas, mine, off-gas, process, coal mining/m3`, in m3) carries the
      number of natural gas, a different resource.
    * One `Copper ion` flow (air, high population density) carries the number of
      copper metal, which BAFU's `Copper` flow in the same compartment also carries.

    Matched on BAFU's own flow attributes, so this doesn't depend on the brightway-flows
    crosswalk. Each correction's reasoning is in
    `data/brightway-flows-corrections-bafu-2026-v1.json`.
    """
    apply_corrections(db, "cas-removed")
