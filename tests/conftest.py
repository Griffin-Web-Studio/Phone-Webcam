import pytest


@pytest.fixture(autouse=True)
def isolated_prefs(monkeypatch, tmp_path):
    """Keep tests away from the real user preferences."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))


@pytest.fixture(autouse=True)
def no_real_adb(monkeypatch):
    """No test should talk to a real adb, so the phone is reported missing."""
    from phone_webcam import phone

    monkeypatch.setattr(
        phone, "check_phone", lambda *a, **k: phone.Phone(phone.MISSING)
    )
