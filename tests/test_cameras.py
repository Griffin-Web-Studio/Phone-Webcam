"""Tests for reading the camera list and choosing a size."""

import subprocess

from phone_webcam import cameras

SAMPLE = """\
scrcpy 5.0.1 <https://github.com/Genymobile/scrcpy>
INFO: ADB device found:
INFO:     -->   (usb)  HH0001ZRM04C0605068             device  HMD_Skyline
[server] INFO: List of cameras:
    --camera-id=0    (back, 4000x3000, fps=[15, 24, 30])
        - 4000x3000
        - 3840x2160
        - 1920x1080
        - 1280x720
        High speed capture modes:
            - 1280x720 (fps=[120, 240])
    --camera-id=1    (front, 3264x2448, fps=[15, 24, 30])
        - 3264x2448
        - 1600x1200
        - 1280x960
    --camera-id=2    (back, 2592x1944, fps=[15, 30])
        - 2592x1944
"""


def test_parse_finds_every_camera_with_its_facing():
    found = cameras.parse_cameras(SAMPLE)
    assert [(c.id, c.facing) for c in found] == [
        ("0", "back"),
        ("1", "front"),
        ("2", "back"),
    ]


def test_parse_collects_sizes_and_skips_high_speed_modes():
    back = cameras.parse_cameras(SAMPLE)[0]
    assert back.sizes == ("4000x3000", "3840x2160", "1920x1080", "1280x720")


def test_parse_of_nonsense_is_empty():
    assert cameras.parse_cameras("ERROR: no device\n") == []


def test_label_names_facing_id_and_best_size():
    assert cameras.parse_cameras(SAMPLE)[1].label == "Front camera 1, 3264x2448"


def test_pick_size_takes_1080p_when_offered():
    back = cameras.parse_cameras(SAMPLE)[0]
    assert cameras.pick_size(back.sizes) == "1920x1080"


def test_pick_size_prefers_wide_sizes_that_fit():
    assert cameras.pick_size(("1600x1200", "1280x720")) == "1280x720"


def test_pick_size_uses_the_largest_fitting_size_if_none_are_wide():
    front = cameras.parse_cameras(SAMPLE)[1]
    assert cameras.pick_size(front.sizes) == "1280x960"


def test_pick_size_falls_back_to_the_default():
    assert cameras.pick_size(()) == cameras.DEFAULT_SIZE
    assert cameras.pick_size(("4000x3000",)) == cameras.DEFAULT_SIZE


def test_list_cameras_is_empty_when_scrcpy_is_missing(monkeypatch):
    def gone(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", gone)
    assert cameras.list_cameras() == []


def test_parse_reads_the_frame_rates():
    found = cameras.parse_cameras(SAMPLE)
    assert found[0].fps == (15, 24, 30)
    assert found[2].fps == (15, 30)


def test_pick_size_respects_a_smaller_limit():
    back = cameras.parse_cameras(SAMPLE)[0]
    assert cameras.pick_size(back.sizes, (1280, 720)) == "1280x720"


def test_pick_size_falls_back_to_the_limit_itself():
    assert cameras.pick_size((), (1280, 720)) == "1280x720"


def test_pick_fps_keeps_a_supported_rate():
    assert cameras.pick_fps((15, 30, 60), 60) == 60


def test_pick_fps_drops_to_the_closest_rate_below():
    assert cameras.pick_fps((15, 24, 30), 60) == 30


def test_pick_fps_takes_the_slowest_if_all_are_too_fast():
    assert cameras.pick_fps((60, 120), 30) == 60


def test_pick_fps_trusts_the_wish_when_nothing_is_known():
    assert cameras.pick_fps((), 60) == 60
