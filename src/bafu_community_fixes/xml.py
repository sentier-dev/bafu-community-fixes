"""Read and write EcoSpold 1 XML using the field mappings declared in `models.py`.

Reading has two steps so that import fixes can run in between:

1. `parse` loads raw lxml trees. EcoSpold elements lose their namespace, so
   fixes can use plain tag names like `"exchange"`.
2. `build` turns each raw tree into an `EcoSpold` model. It rejects anything it
   doesn't understand: unknown attributes or elements, repeated single elements,
   and text that isn't valid for its XSD type.

The order of child elements doesn't matter when reading. Writing always uses the
order defined in the schema.
"""

import types
from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any, Union, get_args, get_origin

from lxml import etree
from pydantic import BaseModel, ValidationError

from bafu_community_fixes.models import (
    ECOSPOLD_NS,
    EXT_NS,
    Attr,
    Child,
    Dataset,
    DatasetExtension,
    EcoSpold,
    Exchange,
    ExchangeExtension,
    Model,
    Text,
)
from bafu_community_fixes.progress import ProgressCallback, tracker
from bafu_community_fixes.xsd import Lexical, LexicalError

EXT_PREFIX = "bcf"
_PARSER = etree.XMLParser(remove_blank_text=True, huge_tree=True)


class EcoSpoldError(Exception):
    """Data that doesn't fit the EcoSpold 1 model, with one message per problem."""

    def __init__(self, messages: list[str]):
        self.messages = messages
        shown = "\n".join(f"  {m}" for m in messages[:50])
        more = f"\n  ... and {len(messages) - 50} more" if len(messages) > 50 else ""
        super().__init__(f"{len(messages)} problem(s):\n{shown}{more}")


@dataclass(frozen=True)
class FieldSpec:
    name: str
    marker: Attr | Text | Child
    lexical: Lexical | None
    many: bool
    model: type[Model] | None


def _find(tp: Any, kind: type | tuple[type, ...]) -> Any:
    if isinstance(tp, kind):
        return tp
    for meta in getattr(tp, "__metadata__", ()):
        if isinstance(meta, kind):
            return meta
    for arg in get_args(tp):
        if (found := _find(arg, kind)) is not None:
            return found
    return None


def _is_list(tp: Any) -> bool:
    if get_origin(tp) is list:
        return True
    if get_origin(tp) in (Union, types.UnionType):
        return any(_is_list(arg) for arg in get_args(tp))
    return False


def _model_in(tp: Any) -> type[Model] | None:
    if isinstance(tp, type) and issubclass(tp, BaseModel):
        return tp
    for arg in get_args(tp):
        if (found := _model_in(arg)) is not None:
            return found
    return None


@cache
def fields_of(cls: type[Model]) -> tuple[FieldSpec, ...]:
    """XML-mapped fields of a model, in schema order (`ext` fields are excluded)."""
    specs = []
    for name, info in cls.model_fields.items():
        sources = [*info.metadata, info.annotation]
        marker = next(
            (m for s in sources if (m := _find(s, (Attr, Text, Child))) is not None), None
        )
        if marker is None:
            continue
        lexical = next((m for s in sources if (m := _find(s, Lexical)) is not None), None)
        model = _model_in(info.annotation) if isinstance(marker, Child) else None
        if not isinstance(marker, Child) and lexical is None:
            raise TypeError(f"{cls.__name__}.{name} has no lexical type")
        specs.append(FieldSpec(name, marker, lexical, _is_list(info.annotation), model))
    return tuple(specs)


def attributes_with(lexical: Lexical) -> set[tuple[str, str]]:
    """All `(element tag, attribute name)` pairs that use a given lexical type."""
    found, todo, seen = set(), [("dataset", Dataset)], set()
    while todo:
        tag, cls = todo.pop()
        if cls in seen:
            continue
        seen.add(cls)
        for spec in fields_of(cls):
            if isinstance(spec.marker, Attr) and spec.lexical == lexical:
                found.add((tag, spec.marker.name))
            elif isinstance(spec.marker, Child):
                todo.append((spec.marker.tag, spec.model))
    return found


# --- Reading -------------------------------------------------------------------------


def _local(tag: str) -> tuple[str | None, str]:
    qname = etree.QName(tag)
    return qname.namespace, qname.localname


def parse(path: Path) -> etree._Element:
    """Parse a file and strip the EcoSpold namespace from its elements."""
    root = etree.parse(str(path), _PARSER).getroot()
    for el in root.iter():
        if not isinstance(el.tag, str):
            raise EcoSpoldError([f"{path}: comments and processing instructions not supported"])
        namespace, local = _local(el.tag)
        if namespace == ECOSPOLD_NS:
            el.tag = local
        elif namespace not in (None, EXT_NS):
            raise EcoSpoldError([f"{path}: unexpected namespace {namespace} on <{local}>"])
    etree.cleanup_namespaces(root)
    return root


def _read(cls: type[Model], el: etree._Element, errors: list[str], where: str) -> dict:
    data: dict[str, Any] = {}
    expected_ns = EXT_NS if cls.xml_namespace == EXT_NS else None
    attributes = dict(el.attrib)
    children: dict[str, list[etree._Element]] = {}
    for child in el:
        namespace, local = _local(child.tag)
        if namespace == EXT_NS and expected_ns is None:
            continue  # extensions are read separately
        if namespace != expected_ns:
            errors.append(f"{where}: unexpected element <{child.tag}>")
            continue
        children.setdefault(local, []).append(child)

    for spec in fields_of(cls):
        marker = spec.marker
        if isinstance(marker, Attr):
            if (text := attributes.pop(marker.name, None)) is not None:
                try:
                    data[spec.name] = spec.lexical.parse(text)
                except (LexicalError, ValueError) as e:
                    errors.append(f"{where}/@{marker.name}: {e}")
            continue

        found = children.pop(marker.tag, [])
        if len(found) > 1 and not spec.many:
            errors.append(f"{where}: <{marker.tag}> can occur once, found {len(found)}")
            continue
        values = []
        for i, child in enumerate(found, start=1):
            child_where = f"{where}/{marker.tag}[{i}]"
            if isinstance(marker, Child):
                values.append(_read(spec.model, child, errors, child_where))
            elif child.attrib or len(child):
                errors.append(f"{child_where}: expected only text content")
            else:
                try:
                    values.append(spec.lexical.parse(child.text or ""))
                except (LexicalError, ValueError) as e:
                    errors.append(f"{child_where}: {e}")
        if spec.many:
            data[spec.name] = values
        elif values:
            data[spec.name] = values[0]

    errors.extend(f"{where}/@{name}: attribute not in EcoSpold 1 schema" for name in attributes)
    errors.extend(f"{where}: element <{tag}> not expected here" for tag in children)
    return data


def _read_extensions(el: etree._Element, data: dict, errors: list[str], where: str) -> None:
    exchanges = {e.get("number"): e for e in data.get("flow_data", {}).get("exchanges", [])}
    for container in el.iterfind(f"{{{EXT_NS}}}extensions"):
        for child in container:
            _, local = _local(child.tag)
            child_where = f"{where}/{EXT_PREFIX}:extensions/{local}"
            if local == "dataset":
                data["ext"] = _read(DatasetExtension, child, errors, child_where)
            elif local == "exchange":
                attrs = dict(child.attrib)
                number = attrs.pop("number", None)
                target = exchanges.get(int(number)) if number and number.isdigit() else None
                if target is None:
                    errors.append(f"{child_where}: no exchange with number {number}")
                    continue
                stripped = etree.Element(child.tag, attrs)
                target["ext"] = _read(ExchangeExtension, stripped, errors, child_where)
            else:
                errors.append(f"{child_where}: unknown extension element")


def build(root: etree._Element, source: str = "") -> EcoSpold:
    """Turn a parsed (and import-fixed) tree into a validated `EcoSpold` model."""
    if _local(root.tag) != (None, "ecoSpold"):
        raise EcoSpoldError([f"{source}: root element is <{root.tag}>, not <ecoSpold>"])
    errors: list[str] = []
    data = _read(EcoSpold, root, errors, f"{source}:/ecoSpold")
    for i, (dataset_el, dataset) in enumerate(
        zip(root.iterfind("dataset"), data.get("datasets", []), strict=True), start=1
    ):
        _read_extensions(dataset_el, dataset, errors, f"{source}:/ecoSpold/dataset[{i}]")
    if errors:
        raise EcoSpoldError(errors)
    try:
        return EcoSpold.model_validate(data)
    except ValidationError as e:
        raise EcoSpoldError(
            [f"{source}: {'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()]
        ) from None


# --- Writing -------------------------------------------------------------------------


def _write(model: Model, tag: str, nsmap: dict | None = None) -> etree._Element:
    el = etree.Element(f"{{{model.xml_namespace}}}{tag}", nsmap=nsmap)
    for spec in fields_of(type(model)):
        value = getattr(model, spec.name)
        if value is None:
            continue
        marker = spec.marker
        if isinstance(marker, Attr):
            el.set(marker.name, spec.lexical.format(value))
            continue
        for item in value if spec.many else [value]:
            if isinstance(marker, Child):
                el.append(_write(item, marker.tag))
            else:
                child = etree.SubElement(el, f"{{{model.xml_namespace}}}{marker.tag}")
                child.text = spec.lexical.format(item)
    return el


def _write_extensions(dataset: Dataset, el: etree._Element) -> None:
    container = etree.Element(f"{{{EXT_NS}}}extensions")
    if dataset.ext is not None:
        container.append(_write(dataset.ext, "dataset"))
    for exchange in dataset.exchanges:
        if exchange.ext is not None:
            child = _write(exchange.ext, "exchange")
            attributes = dict(child.attrib)
            child.attrib.clear()
            child.attrib.update({"number": str(exchange.number), **attributes})
            container.append(child)
    if len(container):
        el.append(container)


def to_tree(doc: EcoSpold, extensions: bool = True) -> etree._ElementTree:
    nsmap = {None: ECOSPOLD_NS} | ({EXT_PREFIX: EXT_NS} if extensions else {})
    root = _write(doc, "ecoSpold", nsmap)
    if extensions:
        for dataset, el in zip(doc.datasets, root, strict=True):
            _write_extensions(dataset, el)
    tree = etree.ElementTree(root)
    etree.indent(tree, space="  ")
    return tree


# --- Collections of files ----------------------------------------------------------


@dataclass
class Database:
    """EcoSpold documents keyed by their path relative to the input directory."""

    documents: dict[Path, EcoSpold] = field(default_factory=dict)

    def __iter__(self) -> Iterator[Dataset]:
        for doc in self.documents.values():
            yield from doc.datasets

    def __len__(self) -> int:
        return sum(len(doc.datasets) for doc in self.documents.values())

    def exchanges(self) -> Iterator[tuple[Dataset, Exchange]]:
        for dataset in self:
            for exchange in dataset.exchanges:
                yield dataset, exchange


def find_files(source: Path) -> tuple[Path, list[Path]]:
    """The root directory and the sorted list of XML files to read."""
    if source.is_file():
        return source.parent, [source]
    files = sorted(p for p in source.rglob("*") if p.suffix.lower() == ".xml")
    if not files:
        raise FileNotFoundError(f"No XML files found in {source}")
    return source, files


def load(source: Path | str) -> Database:
    """Read EcoSpold files with no import fixes, e.g. this pipeline's own output."""
    root, files = find_files(Path(source))
    documents, errors = {}, []
    for path in files:
        try:
            documents[path.relative_to(root)] = build(parse(path), str(path.relative_to(root)))
        except EcoSpoldError as e:
            errors.extend(e.messages)
    if errors:
        raise EcoSpoldError(errors)
    return Database(documents)


def write(
    db: Database,
    destination: Path | str,
    extensions: bool = True,
    progress: ProgressCallback | None = None,
) -> list[Path]:
    destination = Path(destination)
    written = []
    update = tracker(progress, "Writing EcoSpold files", len(db.documents))
    for done, (relative, doc) in enumerate(db.documents.items(), start=1):
        update(done)
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        to_tree(doc, extensions).write(str(path), xml_declaration=True, encoding="UTF-8")
        written.append(path)
    return written


def flatten(model: Model, prefix: str = "") -> dict[str, str]:
    """Every value of a model as `{xml path: lexical value}`, e.g. for diffing.

    Paths match `import_fixes.element_path`: repeated elements are indexed
    (`flowData/exchange[3]/@meanValue`), single ones aren't. Extensions are under
    `extensions/`.
    """
    flat = {}
    for spec in fields_of(type(model)):
        value = getattr(model, spec.name)
        if value is None:
            continue
        marker = spec.marker
        if isinstance(marker, Attr):
            flat[f"{prefix}@{marker.name}"] = spec.lexical.format(value)
            continue
        items = value if spec.many else [value]
        for i, item in enumerate(items, start=1):
            path = prefix + marker.tag + (f"[{i}]" if len(items) > 1 else "")
            if isinstance(marker, Child):
                flat.update(flatten(item, path + "/"))
            else:
                flat[path] = spec.lexical.format(item)
    if (ext := getattr(model, "ext", None)) is not None:
        flat.update(flatten(ext, prefix + "extensions/"))
    return flat
