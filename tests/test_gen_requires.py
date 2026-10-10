"""Tests for the dependency lists the package builders use."""

import importlib.util
from pathlib import Path

import pytest

from phone_webcam import deps

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "gen_requires.py"
spec = importlib.util.spec_from_file_location("gen_requires", SCRIPT)
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)


# The kernel module is required by the app, but it comes from third-party
# repositories (RPM Fusion on Fedora), so a hard dependency would make the
# package impossible to install for anyone without them. It is recommended,
# and the app's own dependency check tells the user when it is missing.
THIRD_PARTY = {"v4l2loopback"}


def test_every_gate_the_app_enforces_is_a_requirement():
    """A package must not omit a tool the app refuses to start without."""
    required_keys = {
        r.key
        for r in deps.run_system_checks()
        if r.required and r.key in deps.PACKAGES
    } - THIRD_PARTY
    assert required_keys <= set(gen.REQUIRED)


def test_the_third_party_requirements_are_at_least_recommended():
    assert THIRD_PARTY <= set(gen.RECOMMENDED)


def test_recommended_tools_are_the_optional_ones():
    optional_keys = {r.key for r in deps.run_system_checks() if not r.required}
    assert optional_keys <= set(gen.RECOMMENDED)


def test_ffmpeg_is_asked_for_by_command_on_fedora_only():
    assert "/usr/bin/ffmpeg" in gen.requirements("fedora", "required")
    assert "ffmpeg-free" not in gen.requirements("fedora", "required")
    assert "ffmpeg" in gen.requirements("debian", "required")


def test_debian_has_no_scrcpy_package_to_ask_for():
    assert "scrcpy" not in gen.requirements("debian", "required")
    assert "scrcpy" in gen.requirements("fedora", "required")


@pytest.mark.parametrize("family", ["debian", "fedora"])
def test_no_name_is_listed_twice(family):
    for kind in ("required", "recommended"):
        names = gen.requirements(family, kind)
        assert len(names) == len(set(names))


def test_the_qt_libraries_are_all_required():
    for name in deps.PACKAGES["qt_libs"]["debian"]:
        assert name in gen.requirements("debian", "required")


def test_cli_prints_one_name_per_line(capsys):
    assert gen.main(["--family", "debian", "--kind", "recommended"]) == 0
    assert capsys.readouterr().out.split() == gen.requirements(
        "debian", "recommended"
    )
