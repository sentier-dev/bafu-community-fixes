import hashlib
import zipfile

import pytest

from bafu_community_fixes import download


@pytest.fixture
def release(tmp_path, monkeypatch):
    """A local zip 'release' and an empty cache."""
    archive = tmp_path / "release-v1.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("release-v1/a.xml", "<ecoSpold/>")
        zf.writestr("release-v1/b.xml", "<ecoSpold/>")
    url = archive.as_uri()
    monkeypatch.setattr(download, "cache_dir", lambda: tmp_path / "cache")
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    monkeypatch.setitem(download.CHECKSUMS, url, checksum)
    return url


def test_download_extract_and_cache(release, tmp_path):
    stages = []
    folder = download.latest_release(lambda p: stages.append(p.stage), url=release)
    assert folder == tmp_path / "cache" / "release-v1" / "release-v1"
    assert sorted(p.name for p in folder.iterdir()) == ["a.xml", "b.xml"]
    assert "Downloading the latest BAFU release" in stages
    assert download.is_cached(release)

    stages.clear()
    assert download.latest_release(lambda p: stages.append(p.stage), url=release) == folder
    assert stages == []  # served from the cache


def test_checksum_mismatch(release, monkeypatch):
    monkeypatch.setitem(download.CHECKSUMS, release, "0" * 64)
    with pytest.raises(OSError, match="SHA-256 mismatch"):
        download.latest_release(url=release)
    assert not download.is_cached(release)
