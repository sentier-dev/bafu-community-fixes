"""Align exchange locations with the datasets that supply them."""

from bafu_community_fixes.registry import patch
from bafu_community_fixes.xml import Database

ID = "0002-supplier-locations"
# (consumer dataset number, exchange name): (location in BAFU 2026 v1, supplier location)
CORRECTIONS = {
    (573961, "Disposal, concrete, 5% water, to inert material landfill"): ("CH", "GLO"),
    (204861, "Direct air capture system, sorbent-based, 100ktCO2"): ("CH", "RER"),
}


@patch(
    ID,
    authored_by="Claude Code",
    authorised_by="Chris Mutel",
    reported_by="Manuel Klarmann, Eaternity",
    confirmed_by="Marine Manche, BAFU (email, 12 October 2026)",
    references=(
        "https://github.com/sentier-dev/sentier-bafu/issues/8",
        "https://gitlab.com/eos-lci/lci-bafu-catalog/-/issues/3",
    ),
)
def supplier_locations(db: Database) -> None:
    """Use the location of the supplying dataset for 25 exchanges.

    23 exchanges, mostly in hard coal supply chains, say their electricity comes
    from `ENTSO`, but no dataset has that location; the suppliers exist as
    `ENTSO-E`. Two more exchanges say `CH` for suppliers that only exist as `GLO`
    (concrete landfill, in the offshore crude oil platform) and `RER` (direct air
    capture system). Matching suppliers by name and location fails for all of them.
    BAFU confirmed this by email (12 October 2026) and will correct it in its next
    release.

    A change is only made if the input has a supplier with the new location (or
    no supplier of that name at all, when running on part of the release). The
    patch stops if one of the two named exchanges doesn't have the expected location.
    """
    suppliers = {(d.name, d.reference_function.unit, d.location) for d in db}
    supplier_names = {(name, unit) for name, unit, _ in suppliers}
    for dataset in db:
        for exchange in dataset.exchanges:
            key = (dataset.number, exchange.name)
            if key in CORRECTIONS:
                old, target = CORRECTIONS[key]
                if exchange.location != old:
                    raise ValueError(
                        f"Dataset {dataset.number}: expected {exchange.name!r} in {old}, "
                        f"found {exchange.location}"
                    )
            elif exchange.location == "ENTSO":
                target = "ENTSO-E"
            else:
                continue
            supplier = (exchange.name, exchange.unit)
            if supplier in supplier_names and (*supplier, target) not in suppliers:
                raise ValueError(f"No supplier {exchange.name!r} in {target}")
            exchange.location = target
