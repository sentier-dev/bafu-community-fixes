"""A terminal app for running the pipeline without using the command line.

Launch with `uv run bafu-fixes-tui`.
"""

import os
import subprocess
import sys
import threading
import time
import webbrowser
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from platformdirs import user_documents_dir
from textual import on
from textual.app import App, ComposeResult
from textual.containers import Center, Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.screen import Screen
from textual.widgets import (
    Button,
    Checkbox,
    Collapsible,
    DirectoryTree,
    Footer,
    Header,
    Input,
    Label,
    Markdown,
    ProgressBar,
    RadioButton,
    RadioSet,
    SelectionList,
    Static,
)
from textual.widgets.selection_list import Selection
from textual.worker import Worker

from bafu_community_fixes.changes import RunLog
from bafu_community_fixes.download import LATEST_RELEASE, cache_dir, is_cached, latest_release
from bafu_community_fixes.import_fixes import DEFAULT_PLACEHOLDERS, IMPORT_FIXES, Placeholders
from bafu_community_fixes.pipeline import run
from bafu_community_fixes.progress import Progress, RunCancelled
from bafu_community_fixes.registry import Patch, available_patches


class DataTree(DirectoryTree):
    """Shows folders and XML files only."""

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        return [
            p
            for p in paths
            if not p.name.startswith(".") and (p.is_dir() or p.suffix.lower() == ".xml")
        ]


# (Placeholders field, label, input type, help)
PLACEHOLDER_FIELDS = [
    ("year", "Year", "integer", "For sources without a publication year, and empty time periods."),
    ("number", "Number", "integer", "For persons without a number, and missing validators."),
    ("country", "Country", "text", "Two-letter ISO code, for persons without a country."),
    (
        "text",
        "Text",
        "text",
        "For addresses, company codes and proof reading details that are missing entirely "
        "(blank ones stay blank). 1 to 7 characters, because company codes can't be longer.",
    ),
]


def _patch_label(patch: Patch) -> Content:
    """One line (SelectionList only shows the first line of a prompt).

    The authorisation status comes first, so it's never cut off in narrow terminals.
    """
    provenance = patch.provenance
    if provenance.authorised_by:
        status = ("✓ authorised ", "$success")
        people = f" · by {provenance.authored_by}, authorised by {provenance.authorised_by}"
    else:
        status = ("⚠ not yet authorised ", "bold $warning")
        people = f" · by {provenance.authored_by}"
    return Content.assemble(status, (patch.id, "bold"), f" · {patch.description}", (people, "dim"))


@dataclass
class RunRequest:
    """Everything a run needs, collected from the setup form."""

    source: Path | None  # None: the latest BAFU release
    destination: Path
    report: Path | None
    open_report: bool
    options: dict = field(default_factory=dict)  # passed on to `pipeline.run`


@dataclass
class RunOutcome:
    status: str  # "completed", "failed" or "cancelled"
    request: RunRequest
    log: RunLog | None = None
    error: str | None = None
    report: Path | None = None  # only a report written by this run
    seconds: float = 0.0
    stages: list[tuple[str, float]] = field(default_factory=list)  # (stage, seconds)


def open_path(path: Path) -> None:
    """Open a file or folder with the system's default application."""
    if sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    elif sys.platform == "win32":
        os.startfile(path)  # noqa: S606
    else:
        subprocess.run(["xdg-open", str(path)], check=False)


def _duration(seconds: float) -> str:
    minutes, seconds = divmod(round(seconds), 60)
    return f"{minutes} min {seconds} s" if minutes else f"{seconds} s"


def summary_markdown(outcome: RunOutcome) -> str:
    """A plain-language account of a finished run."""
    log, request = outcome.log, outcome.request
    if outcome.status == "completed":
        lines = [
            f"## ✓ Finished in {_duration(outcome.seconds)}",
            "",
            f"**Output:** {log.written:,} EcoSpold files in `{request.destination}`",
        ]
    elif outcome.status == "cancelled":
        lines = [
            f"## ■ Cancelled after {_duration(outcome.seconds)}",
            "",
            "The run stopped before it finished. Files already written to "
            f"`{request.destination}` may be missing or incomplete.",
        ]
    else:
        lines = [
            f"## ✕ The run stopped after {_duration(outcome.seconds)}",
            "",
            "No output was written. The problem is shown below.",
        ]
    if outcome.report is not None:
        lines += ["", f"**Report:** `{outcome.report}`"]
    if log is not None and log.datasets:
        lines += [
            "",
            f"{log.datasets:,} datasets read, {len(log.changed_datasets):,} changed.",
            "",
            "| Step | Type | Datasets changed | Values changed |",
            "|---|---|--:|--:|",
        ]
        lines += [f"| {s.id} | {s.kind} | {s.datasets:,} | {s.changes:,} |" for s in log.steps]
    if outcome.stages:
        lines += ["", "| Stage | Time |", "|---|--:|"]
        lines += [f"| {stage} | {_duration(seconds)} |" for stage, seconds in outcome.stages]
    return "\n".join(lines)


class ProgressScreen(Screen):
    """Shows the run's progress, and lets the user cancel it."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, request: RunRequest):
        super().__init__()
        self.request = request
        self.cancel_requested = threading.Event()
        self.stages: list[tuple[str, float]] = []  # finished stages and their seconds
        self._stage: str | None = None
        self._stage_started = 0.0

    def compose(self) -> ComposeResult:
        yield Header()
        with Center(), Vertical(id="progress-panel"):
            yield Label("Running the pipeline", classes="title")
            yield Static(id="stages-done")
            yield Label("▶ Starting…", id="stage")
            yield ProgressBar(id="progress", show_eta=False)
            yield Button("Cancel", variant="error", id="cancel")
        yield Footer()

    def on_mount(self) -> None:
        # On the app, not this screen, so replacing the screen doesn't cancel the worker
        self.app.pipeline_worker = self.app.run_worker(
            self.run_pipeline, thread=True, exclusive=True, group="pipeline"
        )

    @on(Button.Pressed, "#cancel")
    def action_cancel(self) -> None:
        if self.cancel_requested.is_set():
            return
        self.cancel_requested.set()
        button = self.query_one("#cancel", Button)
        button.label, button.disabled = "Cancelling…", True
        self.query_one("#stage", Label).update(
            f"▶ {self._stage or 'Starting'}… stopping at the next safe point"
        )

    def run_pipeline(self) -> None:
        """Run in a thread, then show the results."""
        request, started = self.request, time.time()

        def progress(update: Progress) -> None:
            if self.cancel_requested.is_set():
                raise RunCancelled
            self.app.call_from_thread(self.show_progress, update)

        outcome = RunOutcome("completed", request)
        try:
            source = request.source or latest_release(progress)
            outcome.log = run(
                source,
                request.destination,
                report=request.report,
                progress=progress,
                **request.options,
            )
        except RunCancelled:
            outcome.status = "cancelled"
        except Exception as e:
            outcome.status, outcome.error = "failed", str(e)
        outcome.seconds = time.time() - started
        # Only show a report written by this run, not one left over from an earlier run
        report = request.report
        if report is not None and report.exists() and report.stat().st_mtime >= started:
            outcome.report = report
            if request.open_report and outcome.status != "cancelled":
                webbrowser.open(report.resolve().as_uri())
        self.app.call_from_thread(self._finish_stage)
        outcome.stages = list(self.stages)
        self.app.call_from_thread(self.app.switch_screen, ResultsScreen(outcome))

    def _finish_stage(self) -> None:
        if self._stage is not None:
            seconds = time.monotonic() - self._stage_started
            self.stages.append((self._stage, seconds))
            done = self.query_one("#stages-done", Static)
            done.update(f"{done.content}✓ {self._stage} ({_duration(seconds)})\n")
            self._stage = None

    def show_progress(self, update: Progress) -> None:
        if update.stage != self._stage:
            self._finish_stage()
            self._stage, self._stage_started = update.stage, time.monotonic()
            if not self.cancel_requested.is_set():
                self.query_one("#stage", Label).update(f"▶ {update.stage}…")
        self.query_one("#progress", ProgressBar).update(total=update.total, progress=update.done)


class ResultsScreen(Screen):
    """What the run did, and where its output is."""

    BINDINGS = [("n", "new_run", "New run"), ("q", "app.quit", "Quit")]

    def __init__(self, outcome: RunOutcome):
        super().__init__()
        self.outcome = outcome

    def compose(self) -> ComposeResult:
        outcome = self.outcome
        yield Header()
        with Horizontal(id="result-actions"):
            if outcome.report is not None:
                yield Button("Open report", variant="primary", id="open-report")
            if outcome.status != "failed" and outcome.request.destination.exists():
                yield Button("Open output folder", id="open-output")
            yield Button("New run", id="new-run")
            yield Button("Quit", id="quit")
        with VerticalScroll(id="results", classes=outcome.status):
            yield Markdown(summary_markdown(outcome), id="result-summary")
            if outcome.error:
                with VerticalScroll(id="error-box"):
                    yield Static(outcome.error, id="error", markup=False)
        yield Footer()

    @on(Button.Pressed, "#open-report")
    def open_report(self) -> None:
        webbrowser.open(self.outcome.report.resolve().as_uri())

    @on(Button.Pressed, "#open-output")
    def open_output(self) -> None:
        open_path(self.outcome.request.destination)

    @on(Button.Pressed, "#new-run")
    def action_new_run(self) -> None:
        self.app.pop_screen()  # back to the settings, as they were

    @on(Button.Pressed, "#quit")
    def quit(self) -> None:
        self.app.exit()


class PipelineApp(App):
    """Choose the data, the options and the patches, then run."""

    TITLE = "BAFU community fixes"
    SUB_TITLE = "Correct and export the BAFU LCA database"
    CSS_PATH = "tui.tcss"
    BINDINGS = [("ctrl+r", "run", "Run"), ("ctrl+q", "quit", "Quit")]

    def __init__(self, start: Path | None = None):
        super().__init__()
        self.start = start or Path.cwd()
        self.patches = available_patches()
        self._report_edited = False
        self._browsed: Path | None = None
        self.pipeline_worker: Worker | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="browser"):
                yield Label("Browse your files", classes="heading")
                yield Static(
                    "Select a folder or XML file to use it as the data source.", classes="help"
                )
                yield DataTree(self.start, id="tree")
            with VerticalScroll(id="form"):
                yield Label("1. Which BAFU data should be used?", classes="heading")
                with RadioSet(id="source-kind"):
                    yield RadioButton(
                        "Download the latest BAFU release (recommended)", value=True, id="latest"
                    )
                    yield RadioButton("Use data on this computer", id="local")
                yield Static(self._download_note(), id="download-note", classes="help")
                yield Input(
                    placeholder="A folder with EcoSpold XML files, or a single XML file",
                    id="source",
                    disabled=True,
                )

                yield Label("2. Where should the results go?", classes="heading")
                with Horizontal(classes="row"):
                    yield Input(
                        str(Path(user_documents_dir()) / "BAFU community fixes"),
                        placeholder="Output folder",
                        id="destination",
                    )
                    yield Button("Use browsed folder", id="use-browsed")

                yield Label("3. Output options", classes="heading")
                with RadioSet(id="format"):
                    yield RadioButton(
                        "EcoSpold 1 with extra information (recommended)", value=True, id="ext"
                    )
                    yield RadioButton("Plain EcoSpold 1, without extra information", id="plain")
                yield Static(
                    "Double-check the data against the official EcoSpold schema:",
                    classes="help",
                )
                with RadioSet(id="xsd-check"):
                    yield RadioButton("Don't check (fastest)", value=True, id="xsd-off")
                    yield RadioButton("Check the final result once", id="xsd-end")
                    yield RadioButton(
                        "Check after every step (slowest; shows which step caused a problem)",
                        id="xsd-every-step",
                    )
                yield Checkbox("Write an HTML report of all changes", value=True, id="report-on")
                yield Input(placeholder="Report file", id="report")
                yield Checkbox(
                    "Open the report in my web browser when the run is finished",
                    value=True,
                    id="open-report",
                )
                with Collapsible(title="Placeholders for missing required information"):
                    yield Static(
                        "Some required information is missing in the BAFU data. These values "
                        "are filled in instead, so that missing information stays recognisable.",
                        classes="help",
                    )
                    for key, label, kind, help_text in PLACEHOLDER_FIELDS:
                        with Horizontal(classes="placeholder"):
                            yield Label(label, classes="placeholder-label")
                            yield Input(
                                str(getattr(DEFAULT_PLACEHOLDERS, key)),
                                type=kind,
                                id=f"placeholder-{key}",
                            )
                        yield Static(help_text, classes="help placeholder-help")

                yield Label("4. Which community patches should be applied?", classes="heading")
                if self.patches:
                    yield SelectionList(
                        *(Selection(_patch_label(p), p.id, True) for p in self.patches),
                        id="patches",
                    )
                    yield Static(id="patch-details", markup=False)
                else:
                    yield Static("No community patches are available yet.", classes="help")
                with Collapsible(title=f"Always applied: {len(IMPORT_FIXES)} import fixes"):
                    yield Static(
                        Content.assemble(
                            *(
                                part
                                for fix in IMPORT_FIXES
                                for part in ((fix.id, "bold"), (f"  {fix.description}\n", ""))
                            )
                        ),
                        id="import-fixes",
                    )

                yield Button("Run", variant="primary", id="run")
        yield Footer()

    @staticmethod
    def _download_note() -> str:
        if is_cached():
            return f"Already downloaded; kept in {cache_dir()}."
        return (
            f"Downloaded once (about 37 MB) from {LATEST_RELEASE.split('/')[2]}, "
            f"then kept in {cache_dir()}."
        )

    @on(RadioSet.Changed, "#source-kind")
    def choose_source_kind(self, event: RadioSet.Changed) -> None:
        local = event.pressed.id == "local"
        self.query_one("#source", Input).disabled = not local
        self.query_one("#download-note").display = not local

    @on(DirectoryTree.DirectorySelected)
    @on(DirectoryTree.FileSelected)
    def browse(self, event: DirectoryTree.DirectorySelected | DirectoryTree.FileSelected) -> None:
        self._browsed = event.path
        self.query_one("#local", RadioButton).value = True
        self.query_one("#source", Input).value = str(event.path)

    @on(Button.Pressed, "#use-browsed")
    def use_browsed(self) -> None:
        if self._browsed is None:
            self.notify("Select a folder in the file browser first.", severity="warning")
            return
        folder = self._browsed if self._browsed.is_dir() else self._browsed.parent
        self.query_one("#destination", Input).value = str(folder)

    @on(Input.Changed, "#destination")
    def default_report(self, event: Input.Changed) -> None:
        if not self._report_edited and event.value.strip():
            report = self.query_one("#report", Input)
            with report.prevent(Input.Changed):
                report.value = str(Path(event.value.strip()) / "report.html")

    @on(Input.Changed, "#report")
    def report_edited(self) -> None:
        self._report_edited = True

    @on(Checkbox.Changed, "#report-on")
    def toggle_report(self, event: Checkbox.Changed) -> None:
        self.query_one("#report", Input).disabled = not event.value
        self.query_one("#open-report", Checkbox).disabled = not event.value

    @on(SelectionList.SelectionHighlighted, "#patches")
    def show_patch_details(self, event: SelectionList.SelectionHighlighted) -> None:
        patch = self.patches[event.selection_index]
        provenance = patch.provenance
        lines = [f"{patch.id}: {patch.description}"]
        if provenance.reported_by:
            lines.append(f"Reported by {provenance.reported_by}.")
        if provenance.confirmed_by:
            lines.append(f"Confirmed by {provenance.confirmed_by}.")
        lines += [
            f"Written by {provenance.authored_by}. "
            + (
                f"Authorised by {provenance.authorised_by}."
                if provenance.authorised_by
                else "Not yet authorised."
            ),
        ]
        if patch.rationale:
            lines += ["", patch.rationale]
        lines += [f"More information: {url}" for url in provenance.references]
        self.query_one("#patch-details", Static).update("\n".join(lines))

    def placeholders(self) -> Placeholders:
        """The placeholder values entered; raises ValueError if one isn't allowed."""
        values = {}
        for key, label, kind, _ in PLACEHOLDER_FIELDS:
            text = self.query_one(f"#placeholder-{key}", Input).value.strip()
            if not text:
                raise ValueError(f"Enter a placeholder {label.lower()}.")
            values[key] = int(text) if kind == "integer" else text
        return Placeholders(**values)

    @property
    def use_latest(self) -> bool:
        return self.query_one("#latest", RadioButton).value

    def _problems(self, source: str, destination: str) -> list[str]:
        problems = []
        if self.use_latest:
            pass  # downloaded or taken from the cache when the run starts
        elif not source:
            problems.append("Choose where the BAFU data is.")
        elif not Path(source).exists():
            problems.append(f"The data source doesn't exist: {source}")
        if not destination:
            problems.append("Choose an output folder.")
        elif Path(destination).is_file():
            problems.append(f"The output must be a folder, not a file: {destination}")
        return problems

    @on(Button.Pressed, "#run")
    def action_run(self) -> None:
        if self.screen is not self.screen_stack[0]:
            return  # only from the settings
        source = self.query_one("#source", Input).value.strip()
        destination = self.query_one("#destination", Input).value.strip()
        if problems := self._problems(source, destination):
            self.notify("\n".join(problems), title="Can't run yet", severity="error")
            return
        report = None
        if self.query_one("#report-on", Checkbox).value:
            report_path = self.query_one("#report", Input).value.strip()
            report = Path(report_path) if report_path else Path(destination) / "report.html"
        try:
            placeholders = self.placeholders()
        except ValueError as e:
            self.notify(str(e), title="Check the placeholders", severity="error")
            return
        selected = self.query_one("#patches", SelectionList).selected if self.patches else []
        request = RunRequest(
            source=None if self.use_latest else Path(source),
            destination=Path(destination),
            report=report,
            open_report=report is not None and self.query_one("#open-report", Checkbox).value,
            options={
                "skip": [p.id for p in self.patches if p.id not in selected],
                "extensions": self.query_one("#ext", RadioButton).value,
                "xsd_check": self.query_one("#xsd-check", RadioSet).pressed_button.id.removeprefix(
                    "xsd-"
                ),
                "placeholders": placeholders,
            },
        )
        self.push_screen(ProgressScreen(request))


def main() -> None:
    PipelineApp().run()


if __name__ == "__main__":
    main()
