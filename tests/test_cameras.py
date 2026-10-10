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


def test_label_names_facing_id_best_size_and_the_frame_rate_limit():
    label = cameras.parse_cameras(SAMPLE)[1].label
    assert label == "Front camera 1, 3264x2448, up to 30 fps"


def test_label_leaves_the_rate_out_when_it_is_not_known():
    assert cameras.Camera("0", "back", ("1920x1080",)).label == (
        "Back camera 0, 1920x1080"
    )


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


# A Samsung Galaxy S10+ with scrcpy 5.0.1, as the phone really printed it. The
# frame rates are in braces, not square brackets, which the app once did not read.
REAL_S10 = """\
scrcpy 5.0.1 <https://github.com/Genymobile/scrcpy>
INFO: ADB device found:
INFO:     -->   (usb)  RF8MB08632Z                     device  SM_G975F
[server] INFO: Device: [samsung] samsung SM-G975F (Android 16)
[server] INFO: List of cameras:
    --camera-id=0    (back, 4032x3024, fps={15, 20, 24, 30}, zoom-range=[1, 8])
    --camera-id=1    (front, 3648x2736, fps={15, 20, 24, 30}, zoom-range=[1, 4])
    --camera-id=2    (back, 4608x3456, fps={15, 20, 24, 30}, zoom-range=[1, 8])
    --camera-id=3    (front, 3216x2208, fps={15, 20, 24, 30}, zoom-range=[1, 4])
    --camera-id=52    (back, 4032x3024, fps={15, 20, 24, 30}, zoom-range=[1, 8])
"""


def test_the_real_s10_listing_is_read_in_full():
    found = cameras.parse_cameras(REAL_S10)
    assert [(c.id, c.facing) for c in found] == [
        ("0", "back"),
        ("1", "front"),
        ("2", "back"),
        ("3", "front"),
        ("52", "back"),
    ]
    assert [c.sizes for c in found][0] == ("4032x3024",)
    for camera in found:
        assert camera.fps == (15, 20, 24, 30)


def test_a_request_for_60_fps_is_held_to_30_on_every_s10_camera():
    for camera in cameras.parse_cameras(REAL_S10):
        assert cameras.pick_fps(camera.fps, 60) == 30


def test_the_labels_of_the_s10_cameras_show_their_limit():
    labels = [c.label for c in cameras.parse_cameras(REAL_S10)]
    assert labels[0] == "Back camera 0, 4032x3024, up to 30 fps"
    assert labels[4] == "Back camera 52, 4032x3024, up to 30 fps"


def test_both_ways_of_writing_the_rates_are_read():
    braces = "--camera-id=7    (back, 1920x1080, fps={15, 30})"
    brackets = "--camera-id=7    (back, 1920x1080, fps=[15, 30])"
    assert cameras.parse_cameras(braces)[0].fps == (15, 30)
    assert cameras.parse_cameras(brackets)[0].fps == (15, 30)


def test_a_header_without_rates_still_parses():
    found = cameras.parse_cameras("--camera-id=7    (back, 1920x1080)")
    assert found[0].fps == () and found[0].sizes == ("1920x1080",)
