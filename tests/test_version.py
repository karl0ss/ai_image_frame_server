import tomllib

import libs.generic as generic


def test_version_comes_from_bumpversion_file():
    with open(".bumpversion.toml", "rb") as f:
        expected = tomllib.load(f)["tool"]["bumpversion"]["current_version"]
    generic.get_current_version.cache_clear()
    assert generic.get_current_version() == expected


def test_version_is_only_read_once(monkeypatch):
    generic.get_current_version.cache_clear()
    generic.get_current_version()
    monkeypatch.setattr("builtins.open", lambda *a, **k: (_ for _ in ()).throw(AssertionError("read again")))
    assert generic.get_current_version() != "unknown"


def test_missing_version_file_is_reported_as_unknown(monkeypatch, tmp_path):
    generic.get_current_version.cache_clear()
    monkeypatch.chdir(tmp_path)
    assert generic.get_current_version() == "unknown"
    generic.get_current_version.cache_clear()
