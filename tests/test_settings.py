"""Tests for the stream settings."""

from phone_webcam.settings import Settings, SlateSettings


def test_defaults_are_1080p_30_at_8_megabits():
    assert Settings().as_dict() == {
        "resolution": "1080p",
        "fps": 30,
        "bitrate": 8,
        "preview_fps": 30,
    }
    assert Settings().size == (1920, 1080)


def test_good_values_are_kept():
    chosen = Settings.from_dict(
        {"resolution": "720p", "fps": 60, "bitrate": 24, "preview_fps": 15}
    )
    assert chosen.size == (1280, 720)
    assert (chosen.fps, chosen.bitrate, chosen.preview_fps) == (60, 24, 15)


def test_bad_values_fall_back_one_by_one():
    chosen = Settings.from_dict({"resolution": "8k", "fps": 60, "bitrate": "x"})
    assert chosen.resolution == "1080p"
    assert chosen.fps == 60
    assert chosen.bitrate == 8


def test_nonsense_input_gives_the_defaults():
    assert Settings.from_dict(None) == Settings()
    assert Settings.from_dict("fast") == Settings()
    assert Settings.from_dict([1, 2]) == Settings()


def test_preview_never_runs_faster_than_the_output():
    assert Settings(fps=15, preview_fps=60).preview_rate == 15
    assert Settings(fps=60, preview_fps=30).preview_rate == 30


# ───────────────────────────────────────────────────────────────────| Slate |──
def test_slate_defaults():
    assert SlateSettings().as_dict() == {
        "title": "Be right back",
        "subtitle": "Camera is covered",
        "svg": "",
        "notices": True,
        "mirror": True,
    }


def test_slate_good_values_are_kept():
    chosen = SlateSettings.from_dict(
        {
            "title": "Lunch",
            "subtitle": "Back at 2",
            "svg": "/a.svg",
            "notices": False,
            "mirror": False,
        }
    )
    assert chosen == SlateSettings("Lunch", "Back at 2", "/a.svg", False, False)


def test_slate_text_is_limited_and_kept_to_one_line():
    chosen = SlateSettings.from_dict(
        {"title": "x" * 99, "subtitle": "one\ntwo\r\n  three"}
    )
    assert len(chosen.title) == 32
    assert chosen.subtitle == "one two three"
    assert len(SlateSettings.from_dict({"subtitle": "y" * 200}).subtitle) == 64


def test_slate_bad_values_fall_back_one_by_one():
    chosen = SlateSettings.from_dict(
        {"title": 5, "subtitle": None, "svg": 3, "notices": "yes", "mirror": 1}
    )
    assert chosen == SlateSettings()


def test_slate_nonsense_input_gives_the_defaults():
    assert SlateSettings.from_dict(None) == SlateSettings()
    assert SlateSettings.from_dict("cover") == SlateSettings()
