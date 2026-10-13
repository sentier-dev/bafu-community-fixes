import pytest

from bafu_community_fixes import registry
from bafu_community_fixes.changes import Provenance
from bafu_community_fixes.models import UncertaintyType
from bafu_community_fixes.pipeline import PatchError, run
from bafu_community_fixes.registry import Patch


def _set_uncertainty(db):
    """Set an uncertainty type."""
    for dataset in db:
        dataset.exchanges[0].uncertainty_type = UncertaintyType.LOGNORMAL


def _break_keys(db):
    for dataset in db:
        dataset.exchanges[1].number = 1


def test_report(raw_bafu, tmp_path, monkeypatch):
    provenance = Provenance(
        "Ann Author", reported_by="Rita Reporter", confirmed_by="Carl Confirmer, BAFU"
    )
    patch = Patch("0001-test", "Set `uncertaintyType`", _set_uncertainty, provenance)
    monkeypatch.setitem(registry._REGISTRY, patch.id, patch)
    log = run(raw_bafu, tmp_path / "out", xsd_check="every-step", report=tmp_path / "report.html")
    html = (tmp_path / "report.html").read_text()

    (step,) = [s for s in log.steps if s.id == "0001-test"]
    assert step.datasets == 1
    assert [(c.path, c.old, c.new) for c in step.examples[0][1]] == [
        ("flowData/exchange[1]/@uncertaintyType", "0", "1")
    ]
    assert "Run completed" in html
    assert "Set <code>uncertaintyType</code>" in html
    assert "Ann Author" in html
    assert "Reported by</dt><dd>Rita Reporter" in html
    assert "Confirmed by</dt><dd>Carl Confirmer, BAFU" in html
    assert "Not yet authorised" in html
    assert "renumber-exchanges" in html
    assert "Why this change is needed" in html
    assert "Location codes can be at most 7 characters long." in html
    assert "Our convention" in html
    assert "year 1111, number 1111, country AQ, text UNKNOWN" in html
    assert "<script" not in html  # static, self-contained


def test_report_lists_evidence_with_links(raw_bafu, tmp_path):
    run(raw_bafu, tmp_path / "out", report=tmp_path / "report.html")
    html = (tmp_path / "report.html").read_text()
    assert "Cadmium II</td>" in html
    assert "CAS number <code>7440-43-9</code> → <code>22537-48-0</code>" in html
    assert 'href="https://flows.brightway.dev/flows/' in html


def test_report_written_when_run_fails(raw_bafu, tmp_path, monkeypatch):
    patch = Patch("0002-broken", "Break things", _break_keys, Provenance("Ann Author"))
    monkeypatch.setitem(registry._REGISTRY, patch.id, patch)
    with pytest.raises(PatchError):
        run(raw_bafu, tmp_path / "out", report=tmp_path / "report.html")
    html = (tmp_path / "report.html").read_text()
    assert "Run failed" in html
    assert "Duplicate exchange numbers" in html
    assert not (tmp_path / "out").exists()
