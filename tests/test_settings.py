"""Tests for the stream settings."""

from phone_webcam.settings import Settings


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
