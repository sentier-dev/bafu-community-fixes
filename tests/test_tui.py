from pathlib import Path

import pytest
from textual.widgets import Button, Checkbox, Input, Markdown, RadioButton, SelectionList

from bafu_community_fixes import registry, tui
from bafu_community_fixes.changes import Provenance
from bafu_community_fixes.registry import Patch
from bafu_community_fixes.tui import PipelineApp

FIXTURE = Path(__file__).parent / "fixtures" / "raw_bafu.xml"


def _fake_patch(monkeypatch, authorised_by=None):
    patch = Patch("0001-test", "Do nothing", lambda db: None, Provenance("Jane Doe", authorised_by))
    monkeypatch.setitem(registry._REGISTRY, patch.id, patch)
    return patch


@pytest.fixture(autouse=True)
def opened(monkeypatch):
    """URLs the app opened in a browser (none are really opened in tests)."""
    urls = []
    monkeypatch.setattr(tui.webbrowser, "open", urls.append)
    return urls


async def _run_to_results(app, pilot):
    """Press Run, wait for the run to finish, and return the results screen."""
    await pilot.press("ctrl+r")
    await pilot.pause()
    await app.pipeline_worker.wait()
    for _ in range(50):  # the worker switches screens through the event loop
        if isinstance(app.screen, tui.ResultsScreen):
            return app.screen
        await pilot.pause(0.05)
    raise AssertionError(f"Still on {app.screen}")


def _use_local(app, source):
    app.query_one("#local", RadioButton).value = True
    app.query_one("#source", Input).value = str(source)


@pytest.mark.asyncio
async def test_app_starts(tmp_path):
    app = PipelineApp(start=tmp_path)
    async with app.run_test(size=(140, 50)) as pilot:
        await pilot.pause()
        assert app.query_one("#source", Input).value == ""
        assert app.query_one("#source", Input).disabled  # the latest release is the default
        assert app.use_latest


@pytest.mark.asyncio
async def test_patches_listed_and_selected(tmp_path, monkeypatch):
    _fake_patch(monkeypatch)
    app = PipelineApp(start=tmp_path)
    async with app.run_test(size=(140, 50)) as pilot:
        selection = app.query_one("#patches", SelectionList)
        assert "0001-test" in selection.selected
        index = [p.id for p in app.patches].index("0001-test")
        assert "not yet authorised" in str(selection.get_option_at_index(index).prompt)
        selection.focus()
        selection.highlighted = index
        await pilot.pause()
        assert "Written by Jane Doe" in str(app.query_one("#patch-details").render())


@pytest.mark.asyncio
async def test_report_path_follows_output(tmp_path):
    app = PipelineApp(start=tmp_path)
    async with app.run_test(size=(140, 50)) as pilot:
        app.query_one("#destination", Input).value = str(tmp_path / "out")
        await pilot.pause()
        assert app.query_one("#report", Input).value == str(tmp_path / "out" / "report.html")


@pytest.mark.asyncio
async def test_missing_source_is_not_run(tmp_path):
    app = PipelineApp(start=tmp_path)
    async with app.run_test(size=(140, 50)) as pilot:
        _use_local(app, tmp_path / "missing")
        app.query_one("#destination", Input).value = str(tmp_path / "out")
        await pilot.press("ctrl+r")
        await pilot.pause()
        assert app.pipeline_worker is None
        assert not (tmp_path / "out").exists()


@pytest.mark.asyncio
async def test_run_writes_output_and_summary(tmp_path, monkeypatch):
    _fake_patch(monkeypatch, authorised_by="John Doe")
    app = PipelineApp(start=tmp_path)
    async with app.run_test(size=(140, 50)) as pilot:
        _use_local(app, FIXTURE)
        app.query_one("#destination", Input).value = str(tmp_path / "out")
        app.query_one("#report-on", Checkbox).value = False  # the report is tested separately
        results = await _run_to_results(app, pilot)
        assert (tmp_path / "out" / "raw_bafu.xml").exists()
        assert results.outcome.status == "completed"
        assert "Finished" in results.query_one("#result-summary", Markdown).source
        assert not results.query("#error-box")
        assert results.query_one("#open-output", Button)
        await pilot.click("#new-run")
        await pilot.pause()
        assert app.query_one("#destination", Input).value == str(tmp_path / "out")


@pytest.mark.asyncio
async def test_failed_run_shows_error(tmp_path):
    source = tmp_path / "broken.xml"
    source.write_text("<ecoSpold><dataset/></ecoSpold>")
    app = PipelineApp(start=tmp_path)
    async with app.run_test(size=(140, 50)) as pilot:
        _use_local(app, source)
        app.query_one("#destination", Input).value = str(tmp_path / "out")
        app.query_one("#report-on", Checkbox).value = False
        results = await _run_to_results(app, pilot)
        assert results.outcome.status == "failed"
        assert results.query_one("#error-box")
        assert not results.query("#open-output")


@pytest.mark.asyncio
async def test_latest_release_progress_and_report(tmp_path, monkeypatch, opened):
    def fake_latest_release(progress):
        progress(tui.Progress("Downloading the latest BAFU release", 5, 10))
        return FIXTURE.parent

    monkeypatch.setattr(tui, "latest_release", fake_latest_release)
    app = PipelineApp(start=tmp_path)
    async with app.run_test(size=(140, 50)) as pilot:
        app.query_one("#destination", Input).value = str(tmp_path / "out")
        results = await _run_to_results(app, pilot)
        assert (tmp_path / "out" / "raw_bafu.xml").exists()
        stages = [stage for stage, _ in results.outcome.stages]
        assert stages[0] == "Downloading the latest BAFU release"
        assert "Reading and preparing the data" in stages
        assert stages[-1] == "Writing the report"
        assert opened == [(tmp_path / "out" / "report.html").resolve().as_uri()]
        assert results.query_one("#open-report", Button)


@pytest.mark.asyncio
async def test_report_not_opened_when_switched_off(tmp_path, opened):
    app = PipelineApp(start=tmp_path)
    async with app.run_test(size=(140, 50)) as pilot:
        _use_local(app, FIXTURE)
        app.query_one("#destination", Input).value = str(tmp_path / "out")
        app.query_one("#open-report", Checkbox).value = False
        await _run_to_results(app, pilot)
        assert (tmp_path / "out" / "report.html").exists()
        assert opened == []


@pytest.mark.asyncio
async def test_invalid_placeholder_blocks_run(tmp_path):
    app = PipelineApp(start=tmp_path)
    async with app.run_test(size=(140, 50)) as pilot:
        _use_local(app, FIXTURE)
        app.query_one("#destination", Input).value = str(tmp_path / "out")
        app.query_one("#placeholder-text", Input).value = "MUCH TOO LONG"
        await pilot.press("ctrl+r")
        await pilot.pause()
        assert app.pipeline_worker is None


@pytest.mark.asyncio
async def test_placeholders_used_in_run(tmp_path):
    from bafu_community_fixes.xml import load

    app = PipelineApp(start=tmp_path)
    async with app.run_test(size=(140, 50)) as pilot:
        _use_local(app, FIXTURE)
        app.query_one("#destination", Input).value = str(tmp_path / "out")
        app.query_one("#report-on", Checkbox).value = False
        app.query_one("#placeholder-year", Input).value = "1900"
        app.query_one("#placeholder-text", Input).value = "n/a"
        await _run_to_results(app, pilot)
        (dataset,) = load(tmp_path / "out")
        source = dataset.meta_information.modelling_and_validation.sources[0]
        assert source.year == 1900
        assert dataset.meta_information.administrative_information.persons[1].address == "n/a"


@pytest.mark.asyncio
async def test_cancel(tmp_path, monkeypatch, opened):
    import threading

    started = threading.Event()

    def endless_run(source, destination, progress, **options):
        started.set()
        while True:  # stops when the progress callback raises RunCancelled
            progress(tui.Progress("Reading and preparing the data", 1, 10))

    monkeypatch.setattr(tui, "run", endless_run)
    app = PipelineApp(start=tmp_path)
    async with app.run_test(size=(140, 50)) as pilot:
        _use_local(app, FIXTURE)
        app.query_one("#destination", Input).value = str(tmp_path / "out")
        await pilot.press("ctrl+r")
        await pilot.pause()
        started.wait(5)
        assert isinstance(app.screen, tui.ProgressScreen)
        await pilot.click("#cancel")
        await app.pipeline_worker.wait()
        for _ in range(50):
            if isinstance(app.screen, tui.ResultsScreen):
                break
            await pilot.pause(0.05)
        assert isinstance(app.screen, tui.ResultsScreen)
        assert app.screen.outcome.status == "cancelled"
        assert "Cancelled" in app.screen.query_one("#result-summary", Markdown).source
        assert opened == []
