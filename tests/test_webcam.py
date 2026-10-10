"""Tests for the webcam helpers and the start/stop state machine."""

import subprocess
import threading
import time
import types
from pathlib import Path

import pytest

from phone_webcam import cameras, webcam
from phone_webcam import slate as slate_module
from phone_webcam.settings import Settings, SlateSettings


# ───────────────────────────────────────────────────────────────| Controller |──
def make(monkeypatch, *, prepared="/dev/video0", lines=(), code=0):
    events: list[dict] = []
    cam = webcam.Webcam(events.append)
    monkeypatch.setattr(cam, "_prepare", lambda: prepared)

    class FakeProcess:
        def terminate(self):
            pass

        def poll(self):
            return code

        def wait(self):
            return code

    monkeypatch.setattr(
        cam, "_spawn", lambda args: (FakeProcess(), iter(lines))
    )
    monkeypatch.setattr(cam, "_start_pipeline", lambda *a: True)
    return cam, events


def run_to_end(cam):
    cam.start()
    for thread in threading.enumerate():
        if thread.name == "webcam-worker":
            thread.join(timeout=5)


def states(events):
    return [e["state"] for e in events if e["type"] == "state"]


def logs(events):
    return [e["line"] for e in events if e["type"] == "log"]


def test_run_ends_stopped_and_running_waits_for_the_first_frame(monkeypatch):
    cam, events = make(monkeypatch)
    run_to_end(cam)
    assert states(events) == ["starting", "stopped"]
    cam.state = webcam.STARTING
    cam._on_first_frame()
    assert states(events)[-1] == "running"


def test_prepare_failure_goes_straight_back_to_stopped(monkeypatch):
    cam, events = make(monkeypatch, prepared=None)
    run_to_end(cam)
    assert states(events) == ["starting", "stopped"]


def test_nonzero_exit_is_logged(monkeypatch):
    cam, events = make(monkeypatch, code=1)
    run_to_end(cam)
    assert "scrcpy exited with code 1" in logs(events)


def test_user_stop_with_sigterm_is_not_an_error(monkeypatch):
    cam, events = make(monkeypatch, code=webcam.SIGTERM_EXIT)
    cam._stop_requested = True
    cam.state = webcam.STARTING
    cam._stream("/dev/video0")
    assert not any("exited" in line for line in logs(events))


def test_sigterm_without_a_stop_request_is_an_error(monkeypatch):
    cam, events = make(monkeypatch, code=webcam.SIGTERM_EXIT)
    cam._stream("/dev/video0")
    assert "scrcpy exited with code -15" in logs(events)


def test_start_is_ignored_while_a_run_is_under_way(monkeypatch):
    cam, events = make(monkeypatch)
    cam.state = webcam.RUNNING
    cam.start()
    assert events == []


# ─────────────────────────────────────────────────────────────| Orientation |──
def test_orientation_is_applied_to_the_live_pipeline(monkeypatch):
    cam, events = make(monkeypatch)
    turns = []
    cam._pipeline = types.SimpleNamespace(
        set_orientation=lambda r, m: turns.append((r, m))
    )
    cam.set_orientation(90, True)
    assert turns == [(90, True)]
    assert cam.orientation() == {"rotation": 90, "mirror": True}
    assert events[-1] == {"type": "orientation", "rotation": 90, "mirror": True}


def test_orientation_rejects_odd_angles(monkeypatch):
    cam, _ = make(monkeypatch)
    with pytest.raises(ValueError):
        cam.set_orientation(45, False)


def test_pipeline_starts_before_scrcpy_and_gets_the_fifo(monkeypatch):
    cam, events = make(monkeypatch)
    order = []
    monkeypatch.setattr(
        cam,
        "_start_pipeline",
        lambda f, o: order.append(("pipeline", f, o)) or True,
    )
    monkeypatch.setattr(
        cam,
        "_spawn",
        lambda args: order.append(("scrcpy", args))
        or (
            types.SimpleNamespace(
                poll=lambda: 0, wait=lambda: 0, terminate=lambda: None
            ),
            iter([]),
        ),
    )
    run_to_end(cam)
    assert [step[0] for step in order] == ["pipeline", "scrcpy"]
    fifo = order[0][1]
    assert f"--record={fifo}" in order[1][1]
    assert order[0][2] == "/dev/video0"


def test_the_fifo_is_removed_after_a_run(monkeypatch):
    cam, _ = make(monkeypatch)
    seen = []
    monkeypatch.setattr(
        cam, "_start_pipeline", lambda f, o: seen.append(f) or True
    )
    run_to_end(cam)
    import os

    assert seen and not os.path.exists(seen[0])


def test_scrcpy_args_record_to_the_fifo_with_frequent_keyframes():
    args = webcam.scrcpy_args("/run/x/camera.mkv")
    assert "--record=/run/x/camera.mkv" in args
    assert "--record-format=mkv" in args
    assert any(
        a.startswith("--video-codec-options=i-frame-interval=1") for a in args
    )
    assert not any(a.startswith("--v4l2-sink") for a in args)


class FakePreview:
    def __init__(self, ready=True):
        self.ready = ready
        self.stopped = False

    def start(self):
        return "http://127.0.0.1:1/secret.mjpg"

    def wait_for_first_frame(self, timeout):
        return self.ready

    def stop(self):
        self.stopped = True


def running(monkeypatch, preview):
    cam, events = make(monkeypatch)
    pipeline_calls = []
    cam._pipeline = types.SimpleNamespace(
        set_preview=lambda sink, rate=None: pipeline_calls.append(sink)
    )
    cam.state = webcam.RUNNING
    monkeypatch.setattr(webcam, "Preview", lambda *a: preview)
    return cam, events, pipeline_calls


def settle(cam, wanted):
    """Ask for the preview and let it reconcile, on this thread."""
    cam._preview_wanted = wanted
    cam._preview_failed = False
    cam._preview_busy = True
    cam._reconcile_loop()


def preview_states(events):
    return [e["state"] for e in events if e["type"] == "preview"]


def test_a_wanted_preview_goes_starting_then_open_with_the_address(monkeypatch):
    preview = FakePreview()
    cam, events, calls = running(monkeypatch, preview)
    settle(cam, True)
    assert preview_states(events) == ["starting", "open"]
    assert events[-1]["url"] == "http://127.0.0.1:1/secret.mjpg"
    assert calls == [preview]


def test_an_unwanted_preview_goes_stopping_then_closed(monkeypatch):
    preview = FakePreview()
    cam, events, calls = running(monkeypatch, preview)
    settle(cam, True)
    events.clear()
    settle(cam, False)
    assert preview_states(events) == ["stopping", "closed"]
    assert preview.stopped
    assert calls[-1] is None


def test_asking_again_for_what_is_so_does_nothing(monkeypatch):
    cam, events, _ = running(monkeypatch, FakePreview())
    settle(cam, True)
    events.clear()
    settle(cam, True)
    assert events == []
    settle(cam, False)
    events.clear()
    settle(cam, False)
    assert events == []


def test_no_preview_starts_before_the_webcam_runs(monkeypatch):
    cam, events, calls = running(monkeypatch, FakePreview())
    cam.state = webcam.STARTING
    settle(cam, True)
    assert events == [] and calls == []


def test_the_preview_survives_a_camera_switch(monkeypatch):
    cam, events, _ = running(monkeypatch, FakePreview())
    settle(cam, True)
    cam.state = webcam.SWITCHING
    events.clear()
    settle(cam, True)
    assert events == []


def test_the_preview_goes_when_the_run_ends(monkeypatch):
    preview = FakePreview()
    cam, events, _ = running(monkeypatch, preview)
    settle(cam, True)
    cam._ending = True
    events.clear()
    settle(cam, True)
    assert preview_states(events) == ["stopping", "closed"]


def test_a_preview_that_never_shows_a_picture_is_closed_and_not_retried(
    monkeypatch,
):
    preview = FakePreview(ready=False)
    cam, events, _ = running(monkeypatch, preview)
    settle(cam, True)
    assert preview_states(events) == ["starting", "closed"]
    assert preview.stopped
    assert "did not produce a picture" in logs(events)[-1]
    assert cam._preview_busy is False


def test_a_crash_while_reconciling_does_not_wedge_the_preview(monkeypatch):
    cam, events, _ = running(monkeypatch, FakePreview())

    def boom():
        raise RuntimeError("nope")

    monkeypatch.setattr(cam, "_start_preview", boom)
    settle(cam, True)
    assert "The preview failed: RuntimeError" in logs(events)[-1]
    assert cam._preview_busy is False


def test_asking_for_a_preview_reconciles_in_the_background(monkeypatch):
    preview = FakePreview()
    cam, events, _ = running(monkeypatch, preview)
    cam.set_preview_wanted(True)
    for _ in range(200):
        if "open" in preview_states(events):
            break
        time.sleep(0.01)
    assert preview_states(events) == ["starting", "open"]


# ───────────────────────────────────────────────────────────────| Confirming |──
def test_confirm_returns_the_answer(monkeypatch):
    cam, events = make(monkeypatch)
    threading.Timer(0.05, cam.answer, args=(True,)).start()
    assert cam._confirm("Reload?") is True
    assert events[0] == {"type": "confirm", "message": "Reload?"}


def test_stop_declines_a_pending_confirmation(monkeypatch):
    cam, _ = make(monkeypatch)
    cam.state = webcam.STARTING
    threading.Timer(0.05, cam.stop).start()
    assert cam._confirm("Reload?") is False


# ──────────────────────────────────────────────────────────────────| Output |──
def test_spawn_gives_lines_without_waiting_for_the_process_to_exit():
    """A child on a pty is line buffered, so output arrives while it runs."""
    import sys

    script = "import time; print('first', flush=False); time.sleep(5)"
    process, lines = webcam.Webcam._spawn([sys.executable, "-c", script])
    try:
        assert next(lines) == "first"
    finally:
        process.kill()
        process.wait()


def test_clean_line_strips_terminal_codes():
    raw = "\x1b[22;2t\x1b]0;scrcpy - HMD Skyline\x07INFO: Video decoding\x1b[K"
    assert webcam.clean_line(raw) == "INFO: Video decoding"


def test_clean_line_keeps_the_last_progress_update():
    assert webcam.clean_line("[  8%] push\r[100%] push done\x1b[K") == (
        "[100%] push done"
    )


def test_clean_line_of_only_codes_is_empty():
    assert webcam.clean_line("\x1b[K\r") == ""


# ──────────────────────────────────────────────────────────────────| Cameras |──
BACK = cameras.Camera("0", "back", ("1920x1080",))
FRONT = cameras.Camera("1", "front", ("1280x960",))


def with_cameras(cam):
    cam._cameras = {"0": BACK, "1": FRONT}


def test_scrcpy_args_pick_the_chosen_camera_and_its_size():
    args = webcam.scrcpy_args("/f", FRONT)
    assert "--camera-id=1" in args
    assert "--camera-size=1280x960" in args


def test_scrcpy_args_without_a_camera_use_the_default():
    args = webcam.scrcpy_args("/f")
    assert not any(a.startswith("--camera-id") for a in args)
    assert "--camera-size=1920x1080" in args


def test_choosing_a_camera_while_stopped_only_remembers_it(monkeypatch):
    cam, events = make(monkeypatch)
    cam.set_camera("1")
    assert cam.camera() == "1"
    assert states(events) == []
    assert events[-1] == {"type": "camera", "id": "1"}


def test_choosing_the_same_camera_does_nothing(monkeypatch):
    cam, events = make(monkeypatch)
    cam.set_camera("")
    assert events == []


def test_choosing_a_camera_while_running_switches_live(monkeypatch):
    cam, events = make(monkeypatch)
    ended = []
    cam._process = types.SimpleNamespace(terminate=lambda: ended.append(1))
    cam.state = webcam.RUNNING
    cam.set_camera("1")
    assert states(events) == ["switching"]
    assert ended == [1]
    assert cam._switching


def run_stream(monkeypatch, cam, runs):
    """Drive _stream with scripted scrcpy runs, each a (code, action)."""
    restarts = []
    cam._pipeline = types.SimpleNamespace(
        restart_reader=lambda: restarts.append(1),
        set_fps=lambda fps: None,
    )
    scripted = iter(runs)
    started = []

    def run_scrcpy(fifo):
        started.append(cam._camera_id)
        code, action = next(scripted)
        if action:
            action()
        return code

    monkeypatch.setattr(cam, "_run_scrcpy", run_scrcpy)
    monkeypatch.setattr(cam, "_start_pipeline", lambda f, o: True)
    cam._stream("/dev/video0")
    return started, restarts


def test_a_switch_restarts_scrcpy_on_the_new_camera(monkeypatch):
    cam, events = make(monkeypatch)
    with_cameras(cam)
    cam._camera_id = "0"

    def switch():
        cam._previous, cam._camera_id = ("0", Settings()), "1"
        cam._switching = cam._switched = True

    def stop():
        cam._stop_requested = True

    started, restarts = run_stream(monkeypatch, cam, [(0, switch), (0, stop)])
    assert started == ["0", "1"]
    assert restarts == [1]


def test_a_camera_that_fails_to_start_goes_back(monkeypatch):
    cam, events = make(monkeypatch)
    with_cameras(cam)
    cam._camera_id = "0"

    def switch():
        cam._previous, cam._camera_id = ("0", Settings()), "1"
        cam._switching = cam._switched = True

    def fail_then_nothing():
        cam._switching = False  # the switch itself was handled

    def stop():
        cam._stop_requested = True

    started, restarts = run_stream(
        monkeypatch, cam, [(0, switch), (1, fail_then_nothing), (0, stop)]
    )
    assert started == ["0", "1", "0"]
    assert any("going back" in line for line in logs(events))
    assert {"type": "camera", "id": "0"} in events


def test_an_ordinary_failure_still_ends_the_run(monkeypatch):
    cam, events = make(monkeypatch)
    started, _ = run_stream(monkeypatch, cam, [(1, None)])
    assert started == [None]
    assert "scrcpy exited with code 1" in logs(events)


def test_first_frame_after_a_switch_means_running_again(monkeypatch):
    cam, events = make(monkeypatch)
    cam.state = webcam.SWITCHING
    cam._switched = True
    cam._on_first_frame()
    assert cam.state == webcam.RUNNING
    assert cam._switched is False


# ─────────────────────────────────────────────────────────────────| Settings |──
def test_scrcpy_args_follow_the_settings():
    chosen = Settings(resolution="720p", fps=60, bitrate=16)
    args = webcam.scrcpy_args("/f", None, chosen)
    assert "--camera-size=1280x720" in args
    assert "--camera-fps=60" in args
    assert "--video-bit-rate=16M" in args


def test_scrcpy_args_keep_to_what_the_camera_offers():
    camera = cameras.Camera("0", "back", ("1920x1080", "1280x720"), (15, 30))
    args = webcam.scrcpy_args("/f", camera, Settings(fps=60, resolution="720p"))
    assert "--camera-size=1280x720" in args
    assert "--camera-fps=30" in args


def test_settings_change_freely_while_stopped(monkeypatch):
    cam, events = make(monkeypatch)
    applied = cam.set_settings({"fps": 60, "bitrate": 16})
    assert applied["fps"] == 60 and applied["bitrate"] == 16
    assert events[-1]["type"] == "settings"


def test_only_the_preview_rate_changes_before_the_run_settles(monkeypatch):
    cam, _ = make(monkeypatch)
    cam.state = webcam.STARTING
    applied = cam.set_settings({"fps": 60, "preview_fps": 60})
    assert applied["fps"] == 30
    assert applied["preview_fps"] == 60


def running_with_process(monkeypatch):
    cam, events = make(monkeypatch)
    ended, rates = [], []
    cam._process = types.SimpleNamespace(terminate=lambda: ended.append(1))
    cam._pipeline = types.SimpleNamespace(set_fps=rates.append)
    cam.state = webcam.RUNNING
    return cam, events, ended, rates


def test_frame_rate_and_bitrate_apply_live_by_restarting_scrcpy(monkeypatch):
    cam, events, ended, rates = running_with_process(monkeypatch)
    applied = cam.set_settings({"fps": 60, "bitrate": 16})
    assert (applied["fps"], applied["bitrate"]) == (60, 16)
    assert states(events) == ["applying"]
    assert ended == [1]
    assert rates == [60]
    assert cam._previous == (None, Settings())


def test_the_resolution_cannot_change_while_running(monkeypatch):
    cam, events, ended, _ = running_with_process(monkeypatch)
    applied = cam.set_settings({"resolution": "720p"})
    assert applied["resolution"] == "1080p"
    assert ended == []
    assert states(events) == []


def test_the_preview_rate_alone_does_not_restart_scrcpy(monkeypatch):
    cam, events, ended, rates = running_with_process(monkeypatch)
    cam.set_settings({"preview_fps": 60})
    assert ended == [] and rates == []
    assert states(events) == []


def test_a_setting_scrcpy_refuses_goes_back(monkeypatch):
    cam, events = make(monkeypatch)
    old = Settings()
    cam._settings = Settings(fps=60)
    cam._previous = (None, old)

    def switch():
        cam._switching = cam._switched = True

    def fail():
        cam._switching = False

    def stop():
        cam._stop_requested = True

    run_stream(monkeypatch, cam, [(0, switch), (1, fail), (0, stop)])
    assert cam._settings == old
    assert events[-1]["type"] == "settings"
    assert events[-1]["fps"] == 30


def test_bad_settings_are_ignored(monkeypatch):
    cam, _ = make(monkeypatch)
    applied = cam.set_settings({"fps": 999, "resolution": "8k"})
    assert applied == Settings().as_dict()


def test_the_pipeline_is_built_from_the_settings(monkeypatch):
    built = {}

    class FakePipeline:
        def __init__(self, *args):
            built["args"] = args

        def set_orientation(self, *_):
            pass

        def start(self):
            pass

    monkeypatch.setattr(webcam.pipeline, "Pipeline", FakePipeline)
    cam = webcam.Webcam(
        lambda e: None, settings=Settings(resolution="720p", fps=60)
    )
    monkeypatch.setattr(cam, "_draw_slates", lambda w, h: FakeSlates())
    assert cam._start_pipeline("/fifo", "/dev/video0")
    assert built["args"][4:] == (1280, 720, 60)


# ─────────────────────────────────────────────────────────────────| The cover |──
class FakeSlates:
    """Stands in for the drawn frames, each one named by its kind."""

    def __init__(self, drawn=True):
        self.drawn = drawn
        self.configured = []
        self.calls = []

    def cached(self, kind):
        return f"frame:{kind}".encode() if self.drawn else None

    def frame(self, kind):
        self.calls.append(kind)
        self.drawn = True
        return self.cached(kind)

    def configure(self, path, title, subtitle):
        self.configured.append((path, title, subtitle))


class FakeLive:
    def __init__(self):
        self.shown = []

    def set_slate(self, frame, mirror=True):
        self.shown.append((frame, mirror))


def covered(monkeypatch, state=webcam.RUNNING, drawn=True):
    cam, events = make(monkeypatch)
    cam._pipeline = FakeLive()
    cam._slates = FakeSlates(drawn)
    cam.state = state
    return cam, events


def test_nothing_covers_the_camera_by_default(monkeypatch):
    cam, _ = covered(monkeypatch)
    assert cam._slate_kind() is None
    cam._apply_slate()
    assert cam._pipeline.shown == [(None, True)]


def test_the_shutter_covers_the_camera_and_reports_it(monkeypatch):
    cam, events = covered(monkeypatch)
    cam.set_shutter(True)
    assert cam._pipeline.shown[-1] == (b"frame:shutter", True)
    assert {"type": "shutter", "on": True} in events
    cam.set_shutter(False)
    assert cam._pipeline.shown[-1] == (None, True)


def test_the_shutter_can_be_set_before_the_webcam_starts(monkeypatch):
    cam, events = make(monkeypatch)
    cam.set_shutter(True)
    assert cam.shutter() is True
    assert {"type": "shutter", "on": True} in events


@pytest.mark.parametrize(
    "state, kind",
    [
        (webcam.STARTING, "starting"),
        (webcam.SWITCHING, "switching"),
        (webcam.APPLYING, "applying"),
    ],
)
def test_a_busy_camera_shows_its_notice(monkeypatch, state, kind):
    cam, _ = covered(monkeypatch, state=state)
    assert cam._slate_kind() == kind


def test_a_running_camera_has_no_notice(monkeypatch):
    cam, _ = covered(monkeypatch, state=webcam.RUNNING)
    assert cam._slate_kind() is None


def test_notices_can_be_switched_off(monkeypatch):
    cam, _ = covered(monkeypatch, state=webcam.SWITCHING)
    cam.set_cover_settings({"notices": False})
    assert cam._slate_kind() is None


def test_the_shutter_wins_over_a_notice(monkeypatch):
    cam, _ = covered(monkeypatch, state=webcam.SWITCHING)
    cam._shutter = True
    assert cam._slate_kind() == slate_module.SHUTTER


def test_a_state_change_shows_or_clears_the_notice(monkeypatch):
    cam, _ = covered(monkeypatch, state=webcam.RUNNING)
    cam._set_state(webcam.SWITCHING)
    assert cam._pipeline.shown[-1][0] == b"frame:switching"
    cam._set_state(webcam.RUNNING)
    assert cam._pipeline.shown[-1][0] is None


def test_the_shutter_stays_when_the_camera_comes_back(monkeypatch):
    cam, _ = covered(monkeypatch, state=webcam.SWITCHING)
    cam._shutter = True
    cam._set_state(webcam.RUNNING)
    assert cam._pipeline.shown[-1][0] == b"frame:shutter"


def test_mirroring_the_cover_follows_the_setting(monkeypatch):
    cam, _ = covered(monkeypatch)
    cam.set_cover_settings({"mirror": False})
    cam.set_shutter(True)
    assert cam._pipeline.shown[-1] == (b"frame:shutter", False)


def test_a_frame_not_drawn_yet_is_drawn_without_waiting(monkeypatch):
    cam, _ = covered(monkeypatch, drawn=False)
    cam._shutter = True
    cam._apply_slate()
    for _ in range(200):
        if cam._pipeline.shown and cam._pipeline.shown[-1][0]:
            break
        time.sleep(0.01)
    assert cam._slates.calls == ["shutter"]
    assert cam._pipeline.shown[-1][0] == b"frame:shutter"


def test_changing_the_cover_redraws_it(monkeypatch):
    cam, events = covered(monkeypatch)
    applied = cam.set_cover_settings({"title": "Lunch", "svg": "/x/a.svg"})
    assert applied["title"] == "Lunch"
    assert cam._slates.configured[-1] == (
        Path("/x/a.svg"),
        "Lunch",
        "Camera is covered",
    )
    assert events[-1]["type"] == "cover"


def test_bad_cover_settings_are_ignored(monkeypatch):
    cam, _ = covered(monkeypatch)
    applied = cam.set_cover_settings({"notices": "yes", "title": 3})
    assert applied == SlateSettings().as_dict()


def test_the_output_opens_already_covered(monkeypatch):
    shown = []

    class FakePipeline:
        def __init__(self, *args):
            pass

        def set_orientation(self, *_):
            pass

        def set_slate(self, frame, mirror=True):
            shown.append((frame, mirror))

        def start(self):
            assert shown, "the cover must be set before the output opens"

    monkeypatch.setattr(webcam.pipeline, "Pipeline", FakePipeline)
    cam = webcam.Webcam(lambda e: None)
    monkeypatch.setattr(cam, "_draw_slates", lambda w, h: FakeSlates())
    cam.state = webcam.STARTING
    assert cam._start_pipeline("/fifo", "/dev/video0")
    assert shown == [(b"frame:starting", True)]


def test_nothing_is_shown_when_the_camera_is_off(monkeypatch):
    cam, _ = make(monkeypatch)
    cam._set_state(webcam.SWITCHING)  # no pipeline, no slates, no error
