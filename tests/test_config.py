"""Tests for the saved user preferences."""

from phone_webcam import config


def test_prefs_round_trip(tmp_path):
    path = tmp_path / "nested" / "prefs.json"
    config.save_prefs({"rotation": 90, "mirror": True}, path)
    assert config.load_prefs(path) == {"rotation": 90, "mirror": True}


def test_missing_or_broken_prefs_are_empty(tmp_path):
    assert config.load_prefs(tmp_path / "gone.json") == {}
    broken = tmp_path / "prefs.json"
    broken.write_text("{not json")
    assert config.load_prefs(broken) == {}
    broken.write_text("[1, 2]")
    assert config.load_prefs(broken) == {}


def test_prefs_follow_xdg_config_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config.prefs_path() == tmp_path / "phone-webcam" / "prefs.json"
