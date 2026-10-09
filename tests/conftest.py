import pytest


@pytest.fixture(autouse=True)
def isolated_prefs(monkeypatch, tmp_path):
    """Keep tests away from the real user preferences."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
