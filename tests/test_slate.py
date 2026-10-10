"""Tests for drawing the cover image."""

import shutil
import threading

import numpy as np
import pytest

from phone_webcam import slate

W, H = 320, 180
needs_svg = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not slate.has_svg_support(),
    reason="needs ffmpeg with SVG support",
)


# ─────────────────────────────────────────────────────────────────| Template |──
def test_text_is_put_into_the_placeholders():
    out = slate.fill_template(
        "<t>{{title}}</t><u>{{subtitle}}</u>", "Hi", "There"
    )
    assert out == "<t>Hi</t><u>There</u>"


def test_text_cannot_break_out_of_the_svg():
    out = slate.fill_template("<t>{{title}}</t>", "</t><script>x</script>&", "")
    assert "<script>" not in out
    assert "&lt;/t&gt;" in out and "&amp;" in out


def test_the_default_template_has_both_placeholders():
    svg = slate.DEFAULT_TEMPLATE.read_text(encoding="utf-8")
    assert "{{title}}" in svg and "{{subtitle}}" in svg


def test_solid_frame_is_a_whole_i420_frame():
    assert len(slate.solid_frame(W, H)) == W * H * 3 // 2


# ───────────────────────────────────────────────────────────────| Rendering |──
@needs_svg
def test_the_default_slate_is_drawn_with_ffmpeg():
    frame, error = slate.render_frame(None, "Be right back", "Soon", 1920, 1080)
    assert error == ""
    assert len(frame) == 1920 * 1080 * 3 // 2
    luma = np.frombuffer(frame, np.uint8)[: 1920 * 1080]
    assert luma.min() < luma.max()  # text and shapes, not one flat colour


@needs_svg
def test_a_different_size_svg_is_padded_not_stretched(tmp_path):
    svg = tmp_path / "small.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
        '<rect width="100" height="100" fill="white"/></svg>'
    )
    frame, error = slate.render_frame(svg, "", "", 320, 180)
    assert error == "" and len(frame) == 320 * 180 * 3 // 2
    luma = np.frombuffer(frame, np.uint8)[: 320 * 180].reshape(180, 320)
    assert luma[90, 160] > 200  # white square in the middle
    assert luma[90, 5] < 30  # black bar at the side


def test_a_missing_file_falls_back_to_a_plain_frame(tmp_path):
    frame, error = slate.render_frame(tmp_path / "gone.svg", "", "", W, H)
    assert frame == slate.solid_frame(W, H)
    assert "cannot be read" in error


def test_a_huge_file_is_refused(tmp_path):
    big = tmp_path / "big.svg"
    big.write_bytes(b" " * (slate.MAX_SVG_BYTES + 1))
    frame, error = slate.render_frame(big, "", "", W, H)
    assert frame == slate.solid_frame(W, H)
    assert "larger than 2 MB" in error


def test_a_file_that_is_not_text_falls_back(tmp_path):
    binary = tmp_path / "x.svg"
    binary.write_bytes(b"\xff\xfe\x00\x80")
    frame, error = slate.render_frame(binary, "", "", W, H)
    assert frame == slate.solid_frame(W, H)
    assert error


@needs_svg
def test_broken_svg_falls_back_and_says_why(tmp_path):
    broken = tmp_path / "broken.svg"
    broken.write_text("this is not an svg")
    frame, error = slate.render_frame(broken, "", "", W, H)
    assert frame == slate.solid_frame(W, H)
    assert "ffmpeg could not draw it" in error


def test_no_temporary_file_is_left_behind(tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    slate.render_frame(slate.DEFAULT_TEMPLATE, "a", "b", W, H)
    assert list(tmp_path.glob("phone-webcam-*")) == []


# ─────────────────────────────────────────────────────────────────| The cache |──
def fake_render(calls):
    def render(path, title, subtitle, width, height):
        calls.append((path, title, subtitle))
        return f"{title}|{subtitle}".encode(), ""

    return render


def test_a_frame_is_drawn_once_and_kept():
    calls = []
    slates = slate.Slates(W, H, fake_render(calls))
    slates.configure(None, "Away", "Back soon")
    assert slates.frame(slate.SHUTTER) == b"Away|Back soon"
    slates.frame(slate.SHUTTER)
    assert len(calls) == 1


def test_notices_use_their_own_text_not_the_shutters():
    slates = slate.Slates(W, H, fake_render([]))
    slates.configure(None, "Away", "Back soon")
    assert slates.frame("switching") == b"One moment|Switching camera"


def test_changing_the_text_draws_again():
    calls = []
    slates = slate.Slates(W, H, fake_render(calls))
    slates.configure(None, "One", "")
    slates.frame(slate.SHUTTER)
    slates.configure(None, "Two", "")
    assert slates.frame(slate.SHUTTER) == b"Two|"
    assert len(calls) == 2


def test_a_frame_drawn_during_a_change_is_not_kept():
    slates = slate.Slates(W, H, lambda *a: (b"old", ""))
    slates.configure(None, "One", "")
    started, release = threading.Event(), threading.Event()

    def slow(path, title, subtitle, width, height):
        started.set()
        release.wait(5)
        return b"stale", ""

    slates._render = slow
    thread = threading.Thread(target=slates.frame, args=(slate.SHUTTER,))
    thread.start()
    started.wait(5)
    slates.configure(None, "Two", "")
    release.set()
    thread.join()
    slates._render = fake_render([])
    assert slates.frame(slate.SHUTTER) == b"Two|"


def test_warm_draws_the_shutter_and_every_notice():
    calls = []
    slates = slate.Slates(W, H, fake_render(calls))
    slates.configure(None, "A", "B")
    slates.warm()
    assert len(calls) == 1 + len(slate.NOTICES)


def test_a_render_error_is_remembered():
    slates = slate.Slates(W, H, lambda *a: (b"x", "it broke"))
    slates.configure(None, "", "")
    slates.frame(slate.SHUTTER)
    assert slates.error == "it broke"


@needs_svg
def test_a_good_svg_passes_the_check_and_a_bad_one_does_not(tmp_path):
    assert slate.check_svg(slate.DEFAULT_TEMPLATE) == ""
    broken = tmp_path / "broken.svg"
    broken.write_text("nope")
    assert slate.check_svg(broken) != ""


# ──────────────────────────────────────────────────────────────────| The icon |──
def test_the_icon_is_embedded_as_a_data_address():
    import base64

    address = slate.icon_address()
    prefix = "data:image/svg+xml;base64,"
    assert address.startswith(prefix)
    assert base64.b64decode(address[len(prefix) :]) == slate.ICON.read_bytes()


def test_the_icon_placeholder_is_filled_in():
    out = slate.fill_template('<image href="{{icon}}"/>', "", "")
    assert "{{icon}}" not in out and "data:image/svg+xml;base64," in out


def test_a_missing_icon_leaves_the_picture_out_and_nothing_else(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(slate, "ICON", tmp_path / "gone.svg")
    slate.icon_address.cache_clear()
    try:
        assert slate.icon_address() == ""
        out = slate.fill_template("<t>{{title}}</t>{{icon}}", "Hi", "")
        assert out == "<t>Hi</t>"
    finally:
        slate.icon_address.cache_clear()


def test_the_default_template_shows_the_icon():
    svg = slate.DEFAULT_TEMPLATE.read_text(encoding="utf-8")
    assert "{{icon}}" in svg
    assert "<circle" not in svg  # the old stand-in shapes are gone


@needs_svg
def test_the_icon_is_drawn_on_the_default_slate():
    frame, error = slate.render_frame(None, "Back soon", "", 1920, 1080)
    assert error == ""
    luma = np.frombuffer(frame, np.uint8)[: 1920 * 1080].reshape(1080, 1920)
    icon_area = luma[140:460, 800:1120]
    background = luma[20:100, 20:100]
    assert icon_area.std() > 15  # a picture, not the flat background
    assert background.std() < 1


def test_the_icon_is_a_real_svg_file():
    import xml.etree.ElementTree as ET

    root = ET.parse(slate.ICON).getroot()
    assert root.tag.endswith("svg")
