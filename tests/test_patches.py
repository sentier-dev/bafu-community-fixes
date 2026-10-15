import copy

import pytest

from bafu_community_fixes.models import InputGroup
from bafu_community_fixes.pipeline import apply_patch
from bafu_community_fixes.registry import available_patches


def _patch(id):
    return next(p for p in available_patches() if p.id == id)


def test_strawberry_disposal(db, dataset):
    from bafu_community_fixes.patches.p0001_strawberry_polyethylene_disposal import EXCHANGE

    dataset.number = 188725
    exchange = dataset.exchanges[2]
    exchange.name, exchange.mean_value = EXCHANGE, 126.22
    (changed,) = apply_patch(db, _patch("0001-strawberry-polyethylene-disposal"))
    assert changed.exchanges[2].mean_value == 0.00957


def test_strawberry_disposal_stops_on_unexpected_amount(db, dataset):
    from bafu_community_fixes.patches.p0001_strawberry_polyethylene_disposal import EXCHANGE

    dataset.number = 188725
    dataset.exchanges[2].name, dataset.exchanges[2].mean_value = EXCHANGE, 0.0096
    with pytest.raises(ValueError, match="expected 126.22"):
        apply_patch(db, _patch("0001-strawberry-polyethylene-disposal"))


def test_supplier_locations(db, dataset):
    supplier = copy.deepcopy(dataset)
    supplier.number = 2
    supplier.meta_information.process_information.geography.location = "ENTSO-E"
    next(iter(db.documents.values())).datasets.append(supplier)
    dataset.exchanges[0].location = "ENTSO"
    apply_patch(db, _patch("0002-supplier-locations"))
    assert dataset.exchanges[0].location == "ENTSO-E"


def test_supplier_locations_needs_matching_supplier(db, dataset):
    dataset.exchanges[0].location = "ENTSO"  # the supplier exists, but only in EURwoCH
    with pytest.raises(ValueError, match="No supplier"):
        apply_patch(db, _patch("0002-supplier-locations"))


def test_flag_not_maintained(db, dataset):
    from bafu_community_fixes.changes import RunLog

    dataset.reference_function.name = "xx Electricity, at plant"
    log = RunLog("test", {})
    (changed,) = apply_patch(db, _patch("0003-flag-not-maintained"), log=log)
    assert changed.ext.maintenance == "not maintained"
    assert changed.ext.patches == ["0003-flag-not-maintained"]
    (step,) = log.steps
    assert [(c.path, c.old, c.new) for c in step.examples[0][1]] == [
        ("extensions/@maintenance", None, "not maintained")
    ]


def _elementary(dataset, name, cas=None, category="emissions to air", sub="unspecified"):
    """Turn the fixture's SO2 exchange (an emission to air) into another elementary flow."""
    exchange = dataset.exchanges[1]
    exchange.name, exchange.cas_number = name, cas
    exchange.category, exchange.sub_category = category, sub
    return exchange


def test_corrections_set_ion_cas_number(db, dataset):
    exchange = _elementary(dataset, "Cadmium II", "007440-43-9", sub="high. pop.")
    apply_patch(db, _patch("0005-flow-cas-numbers-replaced"))
    assert exchange.cas_number == "022537-48-0"


def test_corrections_remove_wrong_cas_number(db, dataset):
    exchange = _elementary(dataset, "Nitrogen, organic bound", "007727-37-9", "emissions to water")
    apply_patch(db, _patch("0006-flow-cas-numbers-removed"))
    assert exchange.cas_number is None


def test_corrections_move_compartment(db, dataset):
    exchange = _elementary(dataset, "Carbon dioxide, in air", category="resources", sub="biotic")
    exchange.output_group, exchange.input_group = None, InputGroup.FROM_NATURE
    apply_patch(db, _patch("0008-flow-compartments"))
    assert (exchange.category, exchange.sub_category) == ("resources", "in air")


def test_corrections_stop_on_unexpected_cas_number(db, dataset):
    _elementary(dataset, "Cadmium II", "007439-92-1", sub="high. pop.")  # lead's number
    with pytest.raises(ValueError, match="unexpected CAS number"):
        apply_patch(db, _patch("0005-flow-cas-numbers-replaced"))


def test_corrections_dont_need_the_crosswalk(db, dataset, monkeypatch):
    from bafu_community_fixes import brightway_flows

    def unavailable():
        raise AssertionError("the corrections must not read the crosswalk")

    monkeypatch.setattr(brightway_flows, "crosswalk", unavailable)
    exchange = _elementary(dataset, "Arsine")
    apply_patch(db, _patch("0004-flow-cas-numbers-added"))
    assert exchange.cas_number == "007784-42-1"


def test_corrections_leave_technosphere_exchanges_alone(db, dataset):
    exchange = dataset.exchanges[2]  # heat, from another process
    exchange.name, exchange.cas_number = "Cadmium II", "007440-43-9"
    apply_patch(db, _patch("0005-flow-cas-numbers-replaced"))
    assert exchange.cas_number == "007440-43-9"


def test_consistent_cas_numbers(db, dataset):
    padded = _elementary(dataset, "Benzene", "71-43-2")
    other = copy.deepcopy(dataset)
    other.number = 2
    next(iter(db.documents.values())).datasets.append(other)
    other.exchanges[1].cas_number = None
    apply_patch(db, _patch("0009-consistent-cas-numbers"))
    assert padded.cas_number == "000071-43-2"
    assert other.exchanges[1].cas_number == "000071-43-2"


def test_brightway_flows_links(db, dataset):
    exchange = _elementary(dataset, "Radon-222", sub="high. pop.")
    exchange.unit = "Bq"
    apply_patch(db, _patch("0010-brightway-flows-links"))
    assert exchange.ext.brightway_flow == (
        "https://vocab.brightway.dev/elementary-flows/fe0acd60-3ddc-11dd-abb2-0050c2490048"
    )
    assert exchange.ext.brightway_match == "closeMatch"
    assert dataset.exchanges[2].ext.brightway_flow is None  # not an elementary flow


def test_links_work_after_corrections(db, dataset):
    exchange = _elementary(dataset, "Gas, natural/m3", category="resources", sub="in ground")
    exchange.unit, exchange.output_group, exchange.input_group = "Nm3", None, InputGroup.FROM_NATURE
    apply_patch(db, _patch("0007-flow-names"))
    assert exchange.name == "Gas, natural"
    apply_patch(db, _patch("0010-brightway-flows-links"))
    assert exchange.ext.brightway_flow.startswith("https://vocab.brightway.dev/elementary-flows/")


def test_every_correction_kind_has_a_patch():
    import inspect
    import re

    from bafu_community_fixes.brightway_flows import corrections

    kinds = {c["kind"] for c in corrections()["corrections"]}
    applied = set()
    for p in available_patches():
        applied |= set(
            re.findall(r'apply_corrections\(db, "([\w-]+)"\)', inspect.getsource(p.func))
        )
    assert kinds == applied


def test_correction_patches_link_every_correction_to_brightway_flows():
    from bafu_community_fixes.brightway_flows import FLOW_PAGE, corrections

    patches = [p for p in available_patches() if p.evidence]
    assert sum(len(p.evidence) for p in patches) == len(corrections()["corrections"])
    for p in patches:
        for item in p.evidence:
            assert item.links and all(url.startswith(FLOW_PAGE) for _, url in item.links)


def test_flag_aggregated(db, dataset):
    dataset.number, dataset.reference_function.name = 351127, "Benzene, at plant"
    (changed,) = apply_patch(db, _patch("0011-flag-aggregated"))
    assert changed.meta_information.process_information.data_set_information.type == 2


def test_flag_aggregated_stops_on_unexpected_name(db, dataset):
    dataset.number, dataset.reference_function.name = 351127, "Toluene, at plant"
    with pytest.raises(ValueError, match="expected 'Benzene, at plant'"):
        apply_patch(db, _patch("0011-flag-aggregated"))

