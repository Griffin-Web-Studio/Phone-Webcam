"""Tests for the bridge's debugging switch."""

import pytest

from phone_webcam import api, config


@pytest.fixture(autouse=True)
def own_prefs(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))


def test_debugging_is_off_by_default():
    assert api.Api().get_debug() is False


def test_the_choice_is_remembered_between_runs():
    api.Api().set_debug(True)
    assert config.load_prefs()["debug"] is True
    assert api.Api().get_debug() is True
    api.Api().set_debug(False)
    assert api.Api().get_debug() is False


def test_the_flag_turns_it_on_without_changing_what_is_remembered():
    assert api.Api(debug=True).get_debug() is True
    assert "debug" not in config.load_prefs()


def test_the_flag_prints_the_log_to_the_terminal(capsys):
    bridge = api.Api(debug=True)
    bridge._push({"type": "log", "line": "hello"})
    bridge._push({"type": "state", "state": "running"})
    assert capsys.readouterr().err.count("hello") == 1
    assert "running" not in capsys.readouterr().err


def test_without_the_flag_the_terminal_stays_quiet(capsys):
    api.Api()._push({"type": "log", "line": "hello"})
    assert capsys.readouterr().err == ""
