"""Render a `RunLog` as a self-contained HTML report.

The report is a single file, with the Sentier logo and the Rubik font embedded,
so it can be emailed or attached to a release as is.
"""

import base64
import re
from difflib import SequenceMatcher
from functools import cache
from importlib.resources import files
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape
from markupsafe import Markup, escape

from bafu_community_fixes.changes import RunLog

MAX_VALUE_LENGTH = 160
MAX_EXAMPLE_CHANGES = 50
TOP_TRANSITIONS = 5


@cache
def _assets() -> dict[str, str]:
    assets = files("bafu_community_fixes.report_assets")
    font = (assets / "Rubik-VariableFont_wght.ttf").read_bytes()
    logo = (assets / "sentier-logo.svg").read_text()
    logo = re.sub(r"^<\?xml[^>]*>\s*", "", logo)
    logo = logo.replace("<svg ", '<svg role="img" aria-label="Sentier.dev" ', 1)
    return {"font": base64.b64encode(font).decode(), "logo": logo}


def _value(value: str | None) -> Markup:
    """A changed value for display: absent and empty values are labelled, long ones cut."""
    if value is None:
        return Markup('<span class="absent">absent</span>')
    if value == "":
        return Markup('<span class="absent">empty</span>')
    shown = value if len(value) <= MAX_VALUE_LENGTH else value[:MAX_VALUE_LENGTH] + "…"
    return Markup('<code class="value" title="{}">{}</code>').format(value, shown)


def _inline(text: str) -> Markup:
    """Escaped text with `backticks` as code and *asterisks* as emphasis."""
    html = re.sub(r"`([^`]+)`", r"<code>\1</code>", str(escape(text)))
    return Markup(re.sub(r"(?<![\w*])\*([^*\s][^*]*)\*(?![\w*])", r"<em>\1</em>", html))


def _diff_lines(before: str, after: str) -> tuple[list, list]:
    """Each side's lines as `(line, changed)` pairs, for highlighting."""
    old, new = before.splitlines(), after.splitlines()
    old_changed, new_changed = [True] * len(old), [True] * len(new)
    for block in SequenceMatcher(a=old, b=new, autojunk=False).get_matching_blocks():
        for i in range(block.size):
            old_changed[block.a + i] = new_changed[block.b + i] = False
    return list(zip(old, old_changed, strict=True)), list(zip(new, new_changed, strict=True))


def _path(path: str) -> Markup:
    """An XML path that wraps after slashes rather than mid-word."""
    return Markup("/<wbr>").join(path.split("/"))


def _prose(text: str) -> Markup:
    """Docstring text as paragraphs, and `* ` bullet lists."""
    html = []
    for block in re.split(r"\n\s*\n", text.strip()):
        items = re.split(r"(?m)^\s*\* ", block)
        if len(items) > 1 and not items[0].strip():
            lis = (Markup("<li>{}</li>").format(_inline(" ".join(i.split()))) for i in items[1:])
            html.append(Markup("<ul>{}</ul>").format(Markup("").join(lis)))
        elif block.strip():
            html.append(Markup("<p>{}</p>").format(_inline(" ".join(block.split()))))
    return Markup("").join(html)


def _number(value: int | float) -> str:
    return f"{value:,}"


def _percent(part: int, whole: int) -> str:
    if not whole:
        return "–"
    share = 100 * part / whole
    return "<0.1%" if 0 < share < 0.1 else f"{share:.1f}%"


@cache
def _environment() -> Environment:
    env = Environment(
        loader=PackageLoader("bafu_community_fixes", "templates"),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters.update(value=_value, prose=_prose, inline=_inline, path=_path, number=_number)
    env.globals.update(percent=_percent, diff_lines=_diff_lines)
    return env


def render(log: RunLog) -> str:
    unauthorised = [s for s in log.steps if s.provenance.authorised_by is None and s.datasets]
    return (
        _environment()
        .get_template("report.html.j2")
        .render(
            log=log,
            assets=_assets(),
            import_fixes=[s for s in log.steps if s.kind == "import fix"],
            patches=[s for s in log.steps if s.kind == "patch"],
            unauthorised=unauthorised,
            total_changes=sum(s.changes for s in log.steps),
            top_transitions=TOP_TRANSITIONS,
            max_example_changes=MAX_EXAMPLE_CHANGES,
            xsd_checked=log.status == "completed"
            and log.options.get("XSD schema check", "not checked") != "not checked",
        )
    )


def write_report(log: RunLog, path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(log), encoding="utf-8")
    return path
