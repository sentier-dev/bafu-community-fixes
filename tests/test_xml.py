import pytest
from lxml import etree

from bafu_community_fixes.compliance import xsd_errors
from bafu_community_fixes.models import EXT_NS
from bafu_community_fixes.xml import EcoSpoldError, build, load, to_tree, write


def _doc_bytes(db, extensions=True):
    (doc,) = db.documents.values()
    return etree.tostring(to_tree(doc, extensions))


def test_output_is_xsd_valid(db):
    (doc,) = db.documents.values()
    assert xsd_errors(doc) == []


def test_round_trip_is_stable(db, tmp_path):
    write(db, tmp_path / "a")
    again = load(tmp_path / "a")
    write(again, tmp_path / "b")
    assert (tmp_path / "a" / "raw_bafu.xml").read_bytes() == (
        tmp_path / "b" / "raw_bafu.xml"
    ).read_bytes()


def test_extensions_kept_or_dropped(db):
    assert EXT_NS.encode() in _doc_bytes(db, extensions=True)
    assert EXT_NS.encode() not in _doc_bytes(db, extensions=False)


def test_schema_order_on_output(db):
    root = etree.fromstring(_doc_bytes(db))
    admin = root.find(".//{*}administrativeInformation")
    assert [etree.QName(c).localname for c in admin] == [
        "dataEntryBy",
        "dataGeneratorAndPublication",
        "person",
        "person",
    ]


def _build(xml: bytes):
    return build(etree.fromstring(xml), "test")


def _valid_xml(db) -> bytes:
    return _doc_bytes(db, extensions=False).replace(
        b' xmlns="http://www.EcoInvent.org/EcoSpold01"', b""
    )


def test_unknown_attribute_rejected(db):
    xml = _valid_xml(db).replace(b"<technology ", b'<technology color="red" ')
    with pytest.raises(EcoSpoldError, match="color: attribute not in EcoSpold 1 schema"):
        _build(xml)


def test_repeated_single_element_rejected(db):
    xml = _valid_xml(db).replace(b"<technology ", b"<technology/><technology ")
    with pytest.raises(EcoSpoldError, match="<technology> can occur once, found 2"):
        _build(xml)


def test_invalid_lexical_value_rejected(db):
    xml = _valid_xml(db).replace(b'infrastructureProcess="false"', b'infrastructureProcess="no"')
    with pytest.raises(EcoSpoldError, match="not a valid xsd:boolean"):
        _build(xml)
