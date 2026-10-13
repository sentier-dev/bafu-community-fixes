"""Download the BAFU release, cached in the user's cache directory."""

import hashlib
import shutil
import urllib.request
import zipfile
from pathlib import Path

from platformdirs import user_cache_dir

from bafu_community_fixes.progress import ProgressCallback, tracker

LATEST_RELEASE = "https://files.brightway.dev/bafu-2026-v1-ecospold.zip"
# SHA-256 of the zip file, so a damaged or changed download is noticed
CHECKSUMS = {
    LATEST_RELEASE: "cbaeed4ae79c0be98709c854211cd72725d4f22f8b9b3fe334b7f343fca152f5",
}
_COMPLETE = ".complete"


def cache_dir() -> Path:
    return Path(user_cache_dir("bafu-community-fixes", appauthor=False))


def _download(url: str, target: Path, progress: ProgressCallback | None) -> None:
    partial = target.with_suffix(target.suffix + ".part")
    digest = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=60) as response, partial.open("wb") as f:
        total = int(response.headers.get("Content-Length") or 0) or None
        update = tracker(progress, "Downloading the latest BAFU release", total)
        done = 0
        while chunk := response.read(1 << 20):
            f.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            update(done)
    expected = CHECKSUMS.get(url)
    if expected is not None and digest.hexdigest() != expected:
        partial.unlink()
        raise OSError(f"Download of {url} is damaged or has changed (SHA-256 mismatch)")
    partial.replace(target)


def _extract(archive: Path, target: Path, progress: ProgressCallback | None) -> None:
    partial = target.with_name(target.name + ".part")
    shutil.rmtree(partial, ignore_errors=True)
    with zipfile.ZipFile(archive) as zf:
        members = [m for m in zf.infolist() if not m.is_dir()]
        update = tracker(progress, "Unpacking the release", len(members))
        for done, member in enumerate(members, start=1):
            path = (partial / member.filename).resolve()
            if not path.is_relative_to(partial.resolve()):
                raise OSError(f"Unsafe path in {archive.name}: {member.filename}")
            zf.extract(member, partial)
            update(done)
    (partial / _COMPLETE).touch()
    shutil.rmtree(target, ignore_errors=True)
    partial.replace(target)


def _folder(url: str) -> Path:
    return cache_dir() / Path(url).name.removesuffix(".zip")


def is_cached(url: str = LATEST_RELEASE) -> bool:
    return (_folder(url) / _COMPLETE).exists()


def latest_release(progress: ProgressCallback | None = None, url: str = LATEST_RELEASE) -> Path:
    """The directory with the latest release's XML files, downloading it if needed."""
    folder = _folder(url)
    if not is_cached(url):
        folder.parent.mkdir(parents=True, exist_ok=True)
        archive = cache_dir() / Path(url).name
        if not archive.exists():
            _download(url, archive, progress)
        _extract(archive, folder, progress)
        archive.unlink()
    # The archive has a single top-level folder; use it so output paths stay flat
    children = [p for p in folder.iterdir() if p.is_dir()]
    return children[0] if len(children) == 1 else folder
