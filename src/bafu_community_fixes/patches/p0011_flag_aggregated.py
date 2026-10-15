"""Mark aggregated datasets that BAFU left as unit processes as system terminated."""

from bafu_community_fixes.changes import Rule
from bafu_community_fixes.registry import patch
from bafu_community_fixes.xml import Database

ID = "0011-flag-aggregated"
UNIT_PROCESS, SYSTEM_TERMINATED = 1, 2
HACKATHON = "https://github.com/LouisFreboeuf/brightcon-hacktlon_reverse-engineering-bafu"
# dataset number: name in BAFU 2026 v1. PlasticsEurope / APME eco-profiles; their only
# technosphere inputs are disposal services.
ECO_PROFILES = {
    561964: "xx Acetone cyanohydrin, at plant",
    441771: "Acetone, liquid, at plant",
    350561: "xxx Acrylonitrile, at plant",
    605750: "Acrylonitrile-butadiene-styrene copolymer, ABS, at plant",
    351127: "Benzene, at plant",
    209733: "Butadiene, at plant",
    562756: "Butene, mixed, at plant",
    570118: "Carbon tetrachloride, at plant",
    296388: "Dichloromethane, at plant",
    406984: "Epoxy resin, liquid, at plant",
    488463: "xx Ethylene, pipeline system, at plant",
    303084: "Hydrogen cyanide, at plant",
    261169: "Hydrogen, cracking, APME, at plant",
    498718: "Methyl methacrylate, at plant",
    435536: "Methylchloride, at plant",
    249972: "Methylene diphenyl diisocyanate, at plant",
    344264: "Naphtha, APME mix, at refinery",
    399817: "Nylon 6, at plant",
    439559: "xx Nylon 6, glass-filled, at plant",
    429266: "Nylon 66, at plant",
    580252: "Nylon 66, glass-filled, at plant",
    492185: "Pentane, at plant",
    258922: "Polybutadiene, at plant",
    573301: "Polycarbonate, at plant",
    278063: "Polymethyl methacrylate, beads, at plant",
    293300: "Polymethyl methacrylate, sheet, at plant",
    291451: "Polyols, at plant",
    564621: "Polystyrene, general purpose, GPPS, at plant",
    220342: "Polystyrene, high impact, HIPS, at plant",
    502491: "Polyvinylidenchloride, granulate, at plant",
    377039: "Propylene, at plant",
    302266: "xx Propylene, pipeline system, at plant",
    475847: "Styrene, at plant",
    512669: "Styrene-acrylonitrile copolymer, SAN, at plant",
    265110: "Tetrachloroethylene, at plant",
    164469: "Toluene diisocyanate, at plant",
    396501: "Toluene, liquid, at plant",
    234177: "Trichloroethylene, at plant",
}
# Datasets without any technosphere input, but with the emissions of a whole supply chain
OTHERS = {
    585647: "Iridium production",
    461049: "Cabinet panel",
}
DATASETS = ECO_PROFILES | OTHERS


@patch(
    ID,
    authored_by="Claude Code",
    authorised_by="Chris Mutel",
    reported_by="Brightcon 2026 hackathon, reverse-engineering BAFU team",
    references=(
        HACKATHON,
        "https://github.com/Depart-de-Sentier/brightcon-2026-material/issues/38",
    ),
    rules=(
        Rule(
            "A dataset holding the cumulative elementary flows of a whole supply chain is "
            "'System terminated' (type 2), not 'Unit process' (type 1). This deviates from "
            "the schema documentation, which reserves type 2 for datasets calculated within "
            "ecoinvent and classifies LCI results from outside it as unit processes. We "
            "follow BAFU's own practice instead: it already uses type 2 for 102 such "
            "datasets.",
            "dataSetInformation/@type",
            schema=False,
        ),
    ),
)
def flag_aggregated(db: Database) -> None:
    """Mark 40 aggregated datasets as system terminated (type 2) instead of unit process.

    These datasets contain the life cycle inventory of a whole supply chain, collapsed
    into one dataset, but are marked as unit processes, so users can't tell them apart
    from transparent data. 38 are PlasticsEurope / APME eco-profiles; 37 of them were
    found by the Brightcon 2026 hackathon on dis-aggregating BAFU system processes,
    and `xxx Acrylonitrile, at plant` has the same structure. `Iridium production`
    calls itself an aggregated inventory, and `Cabinet panel` has the supply chain's
    emissions but no inputs.

    If a dataset doesn't have the expected name, or isn't a unit process or system
    terminated, the patch stops: the data has changed, and the patch needs a review.
    Datasets that aren't in the input are skipped.
    """
    for dataset in db:
        if dataset.number not in DATASETS:
            continue
        info = dataset.meta_information.process_information.data_set_information
        if dataset.name != DATASETS[dataset.number] or info.type not in (
            UNIT_PROCESS,
            SYSTEM_TERMINATED,
        ):
            raise ValueError(
                f"Dataset {dataset.number}: expected unit process "
                f"{DATASETS[dataset.number]!r}, found type {info.type} {dataset.name!r}"
            )
        info.type = SYSTEM_TERMINATED
