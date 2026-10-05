"""Tests for loading and downloading godfat's dataset."""

import httpx

from bcgacha import data


class _Response:
    content = b"events: {}\n"
    text = content.decode()

    def raise_for_status(self):
        pass


def test_a_first_download_creates_the_data_folder_and_its_parents(tmp_path, monkeypatch):
    # Regression: fetch() made only the last folder, so a first run, before the
    # per-user bcgacha folder existed, failed with FileNotFoundError.
    folder = tmp_path / "home" / "bcgacha" / "data"
    monkeypatch.setattr(data, "DATA_DIR", folder)
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Response())
    out = data.fetch()
    assert out == folder / "bc-en.yaml"
    assert out.read_bytes() == _Response.content
