"""Tests for the scripts the CI pipeline runs.

The release notes, the nightly version, and the version handling of the package
scripts. The pipeline files themselves are in test_ci.py.
"""

import importlib.util
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


# ─────────────────────────────────────────────────────────────────| The scripts |──
def load_script(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "script",
    sorted(p.name for p in SCRIPTS.glob("*.sh")),
)
def test_every_shell_script_parses(script):
    shell = "sh" if script == "gen-release-notes.sh" else "bash"
    done = subprocess.run(
        [shell, "-n", str(SCRIPTS / script)], capture_output=True
    )
    assert done.returncode == 0, done.stderr.decode()


def test_nightly_version_is_added_to_the_first_version_only():
    patch = load_script("patch_nightly_version").patch
    text = 'name = "x"\nversion = "1.2.3"\n\n[tool.commitizen]\nversion = "1.2.3"\n'
    out = patch(text, "57.abc1234")
    assert out.count('version = "1.2.3+nightly.57.abc1234"') == 1
    assert out.count('version = "1.2.3"') == 1
    assert out.index("nightly") < out.index("[tool.commitizen]")


@pytest.mark.parametrize(
    "bad", ["", "a b", "a/b", "../x", "ab-c", ".a", "a.", "a..b"]
)
def test_a_nightly_suffix_must_be_plain(bad):
    with pytest.raises(ValueError):
        load_script("patch_nightly_version").patch('version = "1.0.0"', bad)


def test_a_file_without_a_version_is_refused():
    with pytest.raises(ValueError, match="no version"):
        load_script("patch_nightly_version").patch("name = 'x'", "abc")


def test_the_patcher_needs_exactly_one_argument(capsys):
    main = load_script("patch_nightly_version").main
    assert main(["patch_nightly_version.py"]) == 1
    assert "usage" in capsys.readouterr().err


def test_both_package_scripts_turn_a_prerelease_dash_into_a_tilde():
    for name in ("build-deb.sh", "build-rpm.sh"):
        text = (SCRIPTS / name).read_text()
        assert r'VERSION="${VERSION//-/\~}"' in text, name
    for version, expected in (
        ("1.0.0", "1.0.0"),
        ("1.0.0-rc.0", "1.0.0~rc.0"),
        ("0.2.0-nightly.abc1234", "0.2.0~nightly.abc1234"),
    ):
        done = subprocess.run(
            [
                "bash",
                "-c",
                f'VERSION={version}; VERSION="${{VERSION//-/\\~}}"; echo "$VERSION"',
            ],
            capture_output=True,
            text=True,
        )
        assert done.stdout.strip() == expected


def test_the_binary_gets_a_fourth_version_part_from_the_build_number():
    text = (SCRIPTS / "build.sh").read_text()
    assert 'FILE_VERSION="$FILE_VERSION.$BUILD_NUMBER"' in text


def notes(tag, channel="stable", changelog=None, tmp_path=None):
    env = {"PATH": "/usr/bin:/bin"}
    if changelog is not None:
        path = tmp_path / "CHANGELOG.md"
        path.write_text(changelog)
        env["CHANGELOG_FILE"] = str(path)
    done = subprocess.run(
        [
            "sh",
            str(SCRIPTS / "gen-release-notes.sh"),
            tag,
            channel,
            "https://x/pkg/" + tag,
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def test_release_notes_fill_in_every_placeholder():
    out = notes("v1.2.3", "rc")
    assert "{{" not in out
    assert "## Phone Webcam v1.2.3" in out and "**Channel:** rc" in out
    assert "https://x/pkg/v1.2.3/phone-webcam.rpm" in out
    assert "https://x/pkg/v1.2.3/phone-webcam.deb" in out
    assert "https://x/pkg/v1.2.3/SHA256SUMS" in out


def test_release_notes_use_only_the_tags_own_changelog_section(tmp_path):
    changelog = (
        "## v1.0.0 (2026-10-10)\n\n### Features\n\n- **a**: final\n\n"
        "## v1.0.0-rc.0 (2026-10-01)\n\n- **b**: candidate\n\n"
        "## v0.9.0 (2026-09-01)\n\n- **c**: old\n"
    )
    out = notes("v1.0.0", changelog=changelog, tmp_path=tmp_path)
    assert "**a**: final" in out
    assert "candidate" not in out and "old" not in out
    assert "candidate" in notes(
        "v1.0.0-rc.0", changelog=changelog, tmp_path=tmp_path
    )


def test_release_notes_work_without_a_changelog(tmp_path):
    out = notes("v1.0.0", changelog="", tmp_path=tmp_path)
    assert out.lstrip().startswith("## Phone Webcam v1.0.0")


def test_every_template_the_pipeline_reads_exists():
    assert (
        ROOT / ".gitlab" / "release_notes_templates" / "default.md"
    ).is_file()
    for script in (
        "gen_requires.py",
        "patch_nightly_version.py",
        "check-packages.sh",
    ):
        assert (SCRIPTS / script).is_file()


def test_a_nightly_version_is_valid_pep_440_which_uv_insists_on():
    """uv refuses any other version, which stopped the first rehearsal."""
    from packaging.version import Version

    patched = load_script("patch_nightly_version").patch(
        'version = "1.4.0"', "57.abc1234"
    )
    version = Version(re.search(r'"(.+)"', patched).group(1))
    assert version.local == "nightly.57.abc1234"
    assert version > Version("1.4.0")  # newer than the release it is built on


def test_a_nightly_of_a_prerelease_is_still_valid():
    from packaging.version import Version

    patched = load_script("patch_nightly_version").patch(
        'version = "1.0.0-rc.0"', "9.abc"
    )
    assert Version(re.search(r'"(.+)"', patched).group(1)).is_prerelease
