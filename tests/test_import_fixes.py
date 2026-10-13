import pytest
from lxml import etree

from bafu_community_fixes.changes import Change
from bafu_community_fixes.import_fixes import (
    IMPORT_FIXES,
    ImportFixError,
    Placeholders,
    apply_import_fixes,
    run_fix,
)
from bafu_community_fixes.models import OutputGroup


def test_fixed_values(dataset):
    meta = dataset.meta_information
    process = meta.process_information
    assert dataset.timestamp.isoformat() == "2025-09-04T18:38:44.741718"
    assert process.time_period.start_date.isoformat() == "2021-02-01"
    assert process.time_period.end_date.isoformat() == "2022-12-31"
    assert process.time_period.data_valid_for_entire_period is True
    assert process.geography.location == "EURwoCH"
    assert meta.modelling_and_validation.representativeness.percent == 100.0

    (source,) = meta.modelling_and_validation.sources
    assert source.year == 1111
    assert source.volume_no is None
    assert source.publisher == "A publisher whose name is far too long for EcoSpold"[:40]
    assert source.additional_authors == ""  # not turned into "false"

    validation = meta.modelling_and_validation.validation
    assert validation.proof_reading_details == ""  # blank is allowed, so kept

    persons = meta.administrative_information.persons
    assert [(p.company_code, p.country_code, p.address) for p in persons] == [
        ("CARBOTE", "CH", "Somewhere"),
        ("", "AQ", "UNKNOWN"),  # blank company code kept; missing address filled in
    ]
    dgp = meta.administrative_information.data_generator_and_publication
    assert dgp.copyright is False
    assert dgp.reference_to_published_source is None


def test_exchanges(dataset):
    reference, so2, heat = dataset.exchanges
    assert [e.number for e in dataset.exchanges] == [1, 2, 3]
    assert [e.ext.original_number for e in dataset.exchanges] == ["100", "7", "7"]
    assert reference.output_group is OutputGroup.REFERENCE_PRODUCT
    assert reference.location == "EURwoCH"
    assert reference.general_comment == ""
    assert so2.cas_number == "007446-09-5"
    assert heat.cas_number is None


def test_applied_fixes_recorded(dataset):
    assert "boolean-spelling" in dataset.ext.import_fixes
    assert "renumber-exchanges" in dataset.ext.import_fixes


def _dataset(xml: str) -> etree._Element:
    return etree.fromstring(f"<dataset>{xml}</dataset>")


def _fix(id: str):
    return next(f for f in IMPORT_FIXES if f.id == id)


def test_booleans_only_touch_boolean_attributes():
    ds = _dataset('<flowData><exchange infrastructureProcess="" generalComment=""/></flowData>')
    assert run_fix(_fix("boolean-spelling"), ds)[0] == [
        Change("flowData/exchange/@infrastructureProcess", "", "false")
    ]
    exchange = ds.find("flowData/exchange")
    assert exchange.get("infrastructureProcess") == "false"
    assert exchange.get("generalComment") == ""


def test_validation_keeps_non_empty_elements():
    ds = _dataset(
        "<metaInformation><modellingAndValidation>"
        '<validation proofReadingDetails="a" proofReadingValidator="1"/>'
        '<validation proofReadingDetails="b" proofReadingValidator="1"/>'
        "</modellingAndValidation></metaInformation>"
    )
    assert run_fix(_fix("validation"), ds) == ([], None)
    assert len(ds.findall(".//validation")) == 2  # left for the schema check to reject


def test_reference_function_text_must_exist_elsewhere():
    ds = _dataset(
        "<metaInformation><processInformation>"
        '<referenceFunction text="unique" generalComment="other"/>'
        "</processInformation></metaInformation>"
    )
    with pytest.raises(ImportFixError):
        run_fix(_fix("reference-function-text"), ds)


def test_changes_are_recorded_with_paths():
    ds = _dataset(
        "<metaInformation><modellingAndValidation>"
        '<validation proofReadingDetails="" proofReadingValidator="1"/><validation/>'
        "</modellingAndValidation></metaInformation>"
        '<flowData><exchange number="7"/><exchange number="7"/></flowData>'
    )
    by_id = {fix.id: changes for fix, changes, _ in apply_import_fixes(ds)}
    assert by_id["validation"] == [
        Change("metaInformation/modellingAndValidation/validation[2]", "<validation/>", None),
    ]
    assert by_id["renumber-exchanges"] == [
        Change("flowData/exchange[1]/@number", "7", "1"),
        Change("flowData/exchange[2]/@number", "7", "2"),
    ]
    assert all(c.field == "flowData/exchange/@number" for c in by_id["renumber-exchanges"])


def test_every_import_fix_has_provenance():
    for fix in IMPORT_FIXES:
        assert fix.provenance.authored_by
        assert fix.description
        assert any(rule.schema for rule in fix.rules), f"{fix.id} cites no schema rule"


def test_snippet_shows_element_before_and_after():
    ds = _dataset(
        '<flowData><exchange name="SO2" CASNumber=""><outputGroup>4</outputGroup>'
        "</exchange></flowData>"
    )
    changes, snippet = run_fix(_fix("cas-numbers-blank"), ds, capture=True)
    assert snippet.before.splitlines() == [
        "<exchange",
        '    name="SO2"',
        '    CASNumber="">',
        "  <outputGroup>4</outputGroup>",
        "</exchange>",
    ]
    assert snippet.after.splitlines() == [
        "<exchange",
        '    name="SO2">',
        "  <outputGroup>4</outputGroup>",
        "</exchange>",
    ]
    assert run_fix(_fix("cas-numbers-blank"), ds, capture=True) == ([], None)


def test_every_changing_step_has_a_snippet(raw_bafu):
    from bafu_community_fixes.changes import RunLog
    from bafu_community_fixes.pipeline import import_database

    log = RunLog(str(raw_bafu), {})
    import_database(raw_bafu, log=log)
    for step in log.steps:
        assert (step.snippet is not None) == bool(step.datasets), step.id
    dataset, snippet = next(s.snippet for s in log.steps if s.id == "location-codes")
    assert dataset.name == "Electricity, at plant"
    assert 'location="Europe without Switzerland"' in snippet.before
    assert 'location="EURwoCH"' in snippet.after


@pytest.mark.parametrize(
    "kwargs",
    [{"year": 0}, {"number": 0}, {"country": "XX"}, {"text": ""}, {"text": "TOO LONG"}],
)
def test_invalid_placeholders(kwargs):
    with pytest.raises(ValueError):
        Placeholders(**kwargs)


def test_custom_placeholders(raw_bafu):
    from bafu_community_fixes.pipeline import import_database

    placeholders = Placeholders(year=1900, country="CH", text="n/a")
    (dataset,) = import_database(raw_bafu, placeholders=placeholders, strict=True)
    meta = dataset.meta_information
    assert meta.modelling_and_validation.sources[0].year == 1900
    assert meta.modelling_and_validation.validation.proof_reading_details == ""
    persons = meta.administrative_information.persons
    assert [(p.company_code, p.country_code, p.address) for p in persons][1] == ("", "CH", "n/a")


def test_missing_published_source_is_copied():
    ds = _dataset(
        "<metaInformation><modellingAndValidation>"
        '<source number="1" firstAuthor="A"/>'
        "</modellingAndValidation><administrativeInformation>"
        '<dataGeneratorAndPublication person="1" referenceToPublishedSource="2"/>'
        "</administrativeInformation></metaInformation>"
    )
    index = {"2": {"number": "2", "firstAuthor": "B", "title": "Report"}}
    changes, _ = run_fix(_fix("copy-missing-published-source"), ds, sources=index)
    copied = ds.find("metaInformation/modellingAndValidation/source[2]")
    assert dict(copied.attrib) == index["2"]
    assert changes[0].path == "metaInformation/modellingAndValidation/source[2]"
    dgp = ds.find(".//dataGeneratorAndPublication")
    assert dgp.get("referenceToPublishedSource") == "2"


def test_index_sources_prefers_most_common_version(tmp_path):
    from bafu_community_fixes.import_fixes import index_sources

    for i, title in enumerate(["Full", "Full", "Short"]):
        (tmp_path / f"{i}.xml").write_text(
            f'<ecoSpold><dataset><source number="7" title="{title}"/></dataset></ecoSpold>'
        )
    assert index_sources(sorted(tmp_path.glob("*.xml"))) == {"7": {"number": "7", "title": "Full"}}
