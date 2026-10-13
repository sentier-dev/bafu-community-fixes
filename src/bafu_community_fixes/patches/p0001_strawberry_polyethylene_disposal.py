"""Correct the polyethylene disposal amounts of three strawberry datasets."""

from bafu_community_fixes.registry import patch
from bafu_community_fixes.xml import Database

ID = "0001-strawberry-polyethylene-disposal"
EXCHANGE = "Disposal, polyethylene, 0.4% water, to municipal incineration"
# dataset number: (amount in BAFU 2026 v1, corrected amount), kg per kg of strawberries
CORRECTIONS = {
    188725: (126.22, 0.00957),  # conventional, unheated plastic tunnel, ES
    242090: (18.079, 0.0363),  # conventional, unheated plastic tunnel, CH
    178351: (18.085, 0.0423),  # organic, unheated plastic tunnel, CH
}


@patch(
    ID,
    authored_by="Claude Code",
    authorised_by="Chris Mutel",
    reported_by="Manuel Klarmann, Eaternity",
    confirmed_by="Marine Manche, BAFU (email, 12 October 2026)",
    references=(
        "https://github.com/sentier-dev/sentier-bafu/issues/6",
        "https://gitlab.com/eos-lci/lci-bafu-catalog/-/issues/1",
    ),
)
def strawberry_polyethylene_disposal(db: Database) -> None:
    """Correct polyethylene disposal for strawberries in unheated plastic tunnels.

    Three datasets dispose of 18 to 126 kg of polyethylene per kg of strawberries,
    while only 0.01 to 0.04 kg of polyethylene granulate goes in. BAFU confirmed the
    error by email (12 October 2026) and gave the correct amounts, which equal each
    dataset's own polyethylene granulate input. BAFU will correct this in its next
    release.

    If a dataset doesn't have the expected amount, the patch stops: the data has
    changed (perhaps BAFU already corrected it), and the patch needs a review.
    Datasets that aren't in the input are skipped.
    """
    for dataset in db:
        if dataset.number not in CORRECTIONS:
            continue
        old, new = CORRECTIONS[dataset.number]
        (exchange,) = [e for e in dataset.exchanges if e.name == EXCHANGE]
        if exchange.mean_value != old:
            raise ValueError(
                f"Dataset {dataset.number}: expected {old} kg {EXCHANGE!r}, "
                f"found {exchange.mean_value}"
            )
        exchange.mean_value = new
