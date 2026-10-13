"""Replace CAS numbers that name a different substance, on 17 elementary flows."""

from bafu_community_fixes.brightway_flows import apply_corrections, evidence
from bafu_community_fixes.registry import patch
from bafu_community_fixes.xml import Database

ID = "0005-flow-cas-numbers-replaced"


@patch(
    ID,
    authored_by="Claude Code",
    evidence=evidence("cas-replaced"),
    authorised_by="Chris Mutel",
    reported_by="Chris Mutel, Brightway Flows",
    references=(
        "https://github.com/brightway-labs/brightway-flows/blob/main/docs/changes/bafu-2026-v1.md",
        "https://github.com/brightway-labs/brightway-flows/issues/146",
        "https://github.com/brightway-labs/brightway-flows/issues/168",
    ),
)
def flow_cas_numbers_replaced(db: Database) -> None:
    """Replace CAS numbers naming a different substance, on 17 elementary flows (brightway-flows).

    * `Cadmium II`, `Zinc II`, `Mercury II`, `Lead II` and `Nickel II` carry the metal's
      number, although the name says the 2+ ion, and BAFU lists the metal separately;
      they get the ion's number.
    * 11 metal flows (cadmium, chromium, lead, mercury, nickel and zinc, to air or
      water) carry the metal's number on some exchanges and the ion's on others; all
      get the metal's number, as the name says.
    * `Uranium-238` carries the number of uranium metal; it gets the isotope's.

    Matched on BAFU's own flow attributes, so this doesn't depend on the brightway-flows
    crosswalk. Each correction's reasoning is in
    `data/brightway-flows-corrections-bafu-2026-v1.json`.
    """
    apply_corrections(db, "cas-replaced")
