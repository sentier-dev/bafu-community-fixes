"""Link every elementary exchange to its brightway-flows elementary flow."""

from bafu_community_fixes.brightway_flows import FLOW_IRI, crosswalk, flow_key
from bafu_community_fixes.models import ExchangeExtension
from bafu_community_fixes.registry import patch
from bafu_community_fixes.xml import Database

ID = "0010-brightway-flows-links"


@patch(
    ID,
    authored_by="Claude Code",
    authorised_by="Chris Mutel",
    reported_by="Chris Mutel, Brightway Flows",
    references=("https://github.com/brightway-labs/brightway-flows",),
)
def brightway_flows_links(db: Database) -> None:
    """Link each elementary exchange to the brightway-flows elementary flow it corresponds to.

    BAFU identifies an elementary flow only by its name, compartment, subcompartment
    and unit. brightway-flows maps all 2,679 BAFU 2026 v1 flows to its consensus list,
    which gives each substance one identity. This patch adds two extension
    attributes to every elementary exchange: `brightwayFlow`, the flow's identifier
    (https://vocab.brightway.dev/elementary-flows/...), and `brightwayMatch`, whether
    the BAFU flow is the same (`exactMatch`), practically the same (`closeMatch`), or
    a more specific flow (`broadMatch`).

    Links are found by name, compartment, subcompartment and unit, as BAFU ships them
    or as patches 0007 and 0008 correct them, so this patch works with or without the
    corrections. The data is from Brightway Flows, used with its author's permission.
    """
    links = crosswalk()
    for dataset in db:
        for exchange in dataset.exchanges:
            if not exchange.is_elementary or (row := links.get(flow_key(exchange))) is None:
                continue
            if exchange.ext is None:
                exchange.ext = ExchangeExtension()
            exchange.ext.brightway_flow = FLOW_IRI + row["brightway_flow_id"]
            exchange.ext.brightway_match = row["match"]
