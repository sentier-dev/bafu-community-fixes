import pytest

from bafu_community_fixes import registry
from bafu_community_fixes.changes import Provenance
from bafu_community_fixes.models import UncertaintyType
from bafu_community_fixes.pipeline import PatchError, apply_patch, run, select_patches
from bafu_community_fixes.registry import Patch
from bafu_community_fixes.xml import load

AUTHOR = Provenance("Test Author")


def _set_uncertainty(db):
    for dataset in db:
        dataset.exchanges[2].uncertainty_type = UncertaintyType.UNDEFINED
        dataset.exchanges[0].uncertainty_type = UncertaintyType.LOGNORMAL


def test_changes_are_recorded(db):
    changed = apply_patch(db, Patch("0001-test", "", _set_uncertainty, AUTHOR), strict=True)
    (dataset,) = changed
    assert dataset.ext.patches == ["0001-test"]


def test_no_op_patch_records_nothing(db):
    assert apply_patch(db, Patch("0001-noop", "", lambda db: None, AUTHOR)) == []
    assert next(iter(db)).ext.patches == []


def test_invalid_patch_is_blamed(db):
    def break_keys(db):
        for dataset in db:
            dataset.exchanges[1].number = 1

    with pytest.raises(PatchError, match="0002-broken"):
        apply_patch(db, Patch("0002-broken", "", break_keys, AUTHOR))


def test_unsafe_list_mutation_is_caught(db):
    def append_junk(db):
        next(iter(db)).exchanges.append("not an exchange")

    with pytest.raises(PatchError):
        apply_patch(db, Patch("0003-junk", "", append_junk, AUTHOR))


def test_select_unknown_patch():
    with pytest.raises(KeyError):
        select_patches(only=["nope"])


def test_run(raw_bafu, tmp_path, monkeypatch):
    monkeypatch.setitem(
        registry._REGISTRY, "0001-test", Patch("0001-test", "", _set_uncertainty, AUTHOR)
    )
    run(raw_bafu, tmp_path, xsd_check="every-step")
    (dataset,) = load(tmp_path)
    assert dataset.exchanges[0].uncertainty_type is UncertaintyType.LOGNORMAL
    assert dataset.ext.patches == ["0001-test"]


@pytest.mark.parametrize(
    ("xsd_check", "stages"),
    [
        ("off", []),
        ("end", ["after all patches"]),
        ("every-step", ["after import", "after patch 0001-test"]),
    ],
)
def test_xsd_check_options(raw_bafu, tmp_path, monkeypatch, xsd_check, stages):
    from bafu_community_fixes import compliance

    checked = []
    monkeypatch.setattr(
        compliance, "check", lambda docs, stage, progress=None: checked.append(stage)
    )
    from bafu_community_fixes import pipeline

    test_patch = Patch("0001-test", "", _set_uncertainty, AUTHOR)
    monkeypatch.setattr(pipeline, "available_patches", lambda: [test_patch])
    log = run(raw_bafu, tmp_path, xsd_check=xsd_check)
    assert checked == stages
    assert (log.xsd_final_checked == 1) is (xsd_check == "end")


def test_failed_final_check_writes_nothing(raw_bafu, tmp_path, monkeypatch):
    from bafu_community_fixes import compliance

    def failing(docs, stage, progress=None):
        raise compliance.ComplianceError(stage, ["something is wrong"])

    monkeypatch.setattr(compliance, "check", failing)
    with pytest.raises(compliance.ComplianceError, match="after all patches"):
        run(raw_bafu, tmp_path / "out", xsd_check="end")
    assert not (tmp_path / "out").exists()


def test_unknown_xsd_check(raw_bafu, tmp_path):
    with pytest.raises(ValueError, match="xsd_check"):
        run(raw_bafu, tmp_path, xsd_check="sometimes")
