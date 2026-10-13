"""Write CAS numbers of elementary flows the same way everywhere."""

from collections import defaultdict

from bafu_community_fixes.brightway_flows import bafu_cas, cas_digits, flow_key
from bafu_community_fixes.registry import patch
from bafu_community_fixes.xml import Database

ID = "0009-consistent-cas-numbers"


@patch(
    ID,
    authored_by="Claude Code",
    authorised_by="Chris Mutel",
    reported_by="Chris Mutel, Brightway Flows",
    references=(
        "https://github.com/brightway-labs/brightway-flows/issues/375",
        "https://github.com/brightway-labs/brightway-flows/issues/376",
    ),
)
def consistent_cas_numbers(db: Database) -> None:
    """Zero-pad elementary flows' CAS numbers; add them where the flow's other exchanges agree.

    BAFU writes the same CAS number in two ways (`000124-38-9` on 98,777 exchanges,
    `124-38-9` on 2,538), so matching on the number as text fails. Every CAS number
    of an elementary exchange is written in the zero-padded style.

    BAFU also writes the CAS number per exchange rather than per flow, and many
    exchanges have none although other exchanges of the same flow (same name,
    compartment, subcompartment and unit) do. Where all of a flow's exchanges that
    have a number agree on it, it's added to the ones without. Flows whose
    exchanges disagree are left alone.
    """
    numbers: dict[tuple, set[str]] = defaultdict(set)
    elementary = [e for d in db for e in d.exchanges if e.is_elementary]
    for exchange in elementary:
        if exchange.cas_number:
            numbers[flow_key(exchange)].add(cas_digits(exchange.cas_number))
    for exchange in elementary:
        if exchange.cas_number:
            exchange.cas_number = bafu_cas(exchange.cas_number)
        elif len(found := numbers.get(flow_key(exchange), set())) == 1:
            exchange.cas_number = bafu_cas(next(iter(found)))
