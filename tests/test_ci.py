"""Tests for the CI pipeline files and the scripts they run.

GitLab's own linter needs a server, so these check what can go wrong without
one: a job in a stage that does not exist, a `needs` that points nowhere, a
commit type that skips the wrong jobs, and a release that links files the
publish job never uploaded.
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / ".gitlab-ci.yml"
NIGHTLY = ROOT / ".gitlab" / "ci" / "nightly.yml"

# What the publish job uploads, and so what a release may link to.
PUBLISHED = (
    "phone-webcam",
    "phone-webcam.deb",
    "phone-webcam.rpm",
    "SHA256SUMS",
)


class Loader(yaml.SafeLoader):
    """Reads GitLab's !reference tag, which plain YAML does not know."""


Loader.add_constructor(
    "!reference",
    lambda loader, node: {"reference": loader.construct_sequence(node)},
)


def load(path):
    return yaml.load(path.read_text(encoding="utf-8"), Loader=Loader)


@pytest.fixture(scope="module")
def main():
    return load(MAIN)


@pytest.fixture(scope="module")
def nightly():
    return load(NIGHTLY)


def jobs(config):
    """The real jobs, which are the entries that are not keywords or templates."""
    keywords = {"workflow", "default", "stages", "variables", "include"}
    return {
        name: body
        for name, body in config.items()
        if name not in keywords and not name.startswith(".")
    }


def everything(config):
    keywords = {"workflow", "default", "stages", "variables", "include"}
    return {n: b for n, b in config.items() if n not in keywords}


# ─────────────────────────────────────────────────────────────| The structure |──
@pytest.mark.parametrize("path", [MAIN, NIGHTLY], ids=["main", "nightly"])
def test_the_pipeline_files_are_valid_yaml(path):
    assert isinstance(load(path), dict)


@pytest.mark.parametrize("which", ["main", "nightly"])
def test_every_job_is_in_a_stage_that_exists(which, main, nightly):
    config = main if which == "main" else nightly
    stages = set(config["stages"]) | {".pre", ".post"}
    for name, body in jobs(config).items():
        # A job that extends a template may get its stage from there.
        if "stage" in body:
            assert body["stage"] in stages, name


@pytest.mark.parametrize("which", ["main", "nightly"])
def test_needs_and_extends_point_at_real_jobs(which, main, nightly):
    config = main if which == "main" else nightly
    known = set(everything(config))
    for name, body in jobs(config).items():
        for need in body.get("needs", []):
            target = need["job"] if isinstance(need, dict) else need
            assert target in known, f"{name} needs {target}"
        extends = body.get("extends", [])
        for parent in [extends] if isinstance(extends, str) else extends:
            assert parent in known, f"{name} extends {parent}"


def test_a_job_never_needs_one_in_a_later_stage(main):
    order = {name: i for i, name in enumerate(main["stages"])}
    order[".pre"] = -1
    stage_of = {}
    for name, body in everything(main).items():
        parent = (
            main.get(body.get("extends"))
            if isinstance(body.get("extends"), str)
            else None
        )
        stage_of[name] = body.get("stage") or (parent or {}).get("stage")
    for name, body in jobs(main).items():
        for need in body.get("needs", []):
            target = need["job"] if isinstance(need, dict) else need
            assert order[stage_of[target]] <= order[stage_of[name]], (
                name,
                target,
            )


def test_the_stages_follow_the_process(main):
    assert main["stages"] == ["test", "build", "publish", "release"]


def test_every_job_runs_on_a_linux_runner(main, nightly):
    assert main["default"]["tags"] == ["linux"]
    assert nightly["default"]["tags"] == ["linux"]


def test_long_running_work_can_be_cancelled_but_publishing_cannot(
    main, nightly
):
    assert main["default"]["interruptible"] is True
    assert main[".publish"]["interruptible"] is False
    assert main["release"]["interruptible"] is False
    assert nightly[".publish"]["interruptible"] is False


# ─────────────────────────────────────────────────────────| The commit filters |──
def rule_patterns(rules):
    """The regular expressions in `$CI_COMMIT_MESSAGE =~ /.../` conditions."""
    found = []
    for rule in rules:
        match = re.search(r"\$CI_COMMIT_MESSAGE =~ /(.*)/", rule.get("if", ""))
        if match:
            found.append((re.compile(match.group(1)), rule.get("when")))
    return found


def skipped_by_workflow(main, message):
    for pattern, when in rule_patterns(main["workflow"]["rules"]):
        if pattern.search(message) and when == "never":
            return True
    return False


@pytest.mark.parametrize(
    "message",
    [
        "docs: explain the cover image",
        "docs(readme)!: rewrite",
        "chore(deps): bump black",
        "chore: tidy",
        "style: format",
    ],
)
def test_commits_with_nothing_to_ship_skip_the_whole_pipeline(main, message):
    assert skipped_by_workflow(main, message)


@pytest.mark.parametrize(
    "message",
    [
        "feat(webcam): add the privacy shutter",
        "fix(deps): find Qt in a compiled build",
        "perf(pipeline): skip a copy",
        "refactor(packaging): use the real reverse domain",
        "build(rpm): add a spec",
        "ci: add the pipeline",
        "test: cover the revert",
        "feat!: break something",
    ],
)
def test_other_commits_start_a_pipeline(main, message):
    assert not skipped_by_workflow(main, message)


@pytest.mark.parametrize(
    "message, builds",
    [
        ("test: cover the revert", False),
        ("test(webcam): more", False),
        ("feat: a feature", True),
        ("ci: change the pipeline", True),
        ("build(rpm): change the spec", True),
        ("fix: a bug", True),
    ],
)
def test_only_test_commits_skip_the_build(main, message, builds):
    skipping = [
        pattern
        for pattern, when in rule_patterns(main["build"]["rules"])
        if when == "never"
    ]
    assert any(p.search(message) for p in skipping) != builds


def test_the_workflow_runs_tags_schedules_main_and_merge_requests(main):
    conditions = " ".join(
        rule.get("if", "") for rule in main["workflow"]["rules"]
    )
    for needed in (
        '$CI_PIPELINE_SOURCE == "schedule"',
        "$CI_COMMIT_TAG",
        '$CI_PIPELINE_SOURCE == "merge_request_event"',
        "$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH",
    ):
        assert needed in conditions


# ─────────────────────────────────────────────────────────────| The release |──
TAG_RULE = r"$CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+/"


def test_publishing_and_releasing_only_happen_for_version_tags(main):
    assert main["publish:release"]["rules"] == [{"if": TAG_RULE}]
    assert main["release"]["rules"] == [{"if": TAG_RULE}]


def test_the_release_waits_for_the_publish_which_waits_for_the_build(main):
    assert main["release"]["needs"] == ["publish:release"]
    assert main["publish:release"]["needs"] == ["build"]


def test_the_release_links_exactly_what_the_publish_job_uploads(main):
    uploaded = main[".publish"]["script"][0]
    links = main["release"]["release"]["assets"]["links"]
    names = [link["url"].rsplit("/", 1)[1] for link in links]
    assert sorted(names) == sorted(PUBLISHED)
    for name in PUBLISHED:
        assert name in uploaded, name


def test_release_links_carry_the_tag_in_their_address(main):
    for link in main["release"]["release"]["assets"]["links"]:
        assert "$CI_COMMIT_TAG" in link["url"]
        assert link["link_type"] in ("package", "other")


def test_the_release_notes_get_a_channel_for_every_prerelease_kind(main):
    script = main["release"]["script"][0]
    for kind in ("alpha", "beta", "rc"):
        assert f"{kind}\\." in script
    assert 'CHANNEL="stable"' in script


def test_build_artifacts_are_what_publish_copies(main):
    artifacts = main[".build"]["artifacts"]["paths"]
    assert artifacts == ["dist/phone-webcam", "dist/*.deb", "dist/*.rpm"]
    publish = main[".publish"]["script"][0]
    for source in ("dist/phone-webcam", "dist/*.deb", "dist/*.rpm"):
        assert source in publish


def test_the_build_makes_the_binary_then_the_packages_then_checks_them(main):
    script = main[".build"]["script"]
    order = [
        next(i for i, line in enumerate(script) if wanted in line)
        for wanted in (
            "build.sh",
            "build-deb.sh",
            "build-rpm.sh",
            "check-packages.sh",
        )
    ]
    assert order == sorted(order)
    assert "--require-tools" in script[-1]


def test_the_test_job_reports_coverage_for_the_badge(main):
    assert "coverage" in main["test"]
    assert re.search(
        main["test"]["coverage"].strip("/"), "TOTAL   1478    145    90%"
    )
    assert "--cov-fail-under=80" in main["test"]["script"][-1]


# ─────────────────────────────────────────────────────────────| The nightly |──
def test_the_nightly_gate_runs_first_and_hands_over_to_a_child(main):
    assert main["check:nightly"]["stage"] == ".pre"
    assert ".gitlab/ci/nightly.yml" in " ".join(main["check:nightly"]["script"])
    trigger = main["trigger:nightly"]
    assert trigger["needs"] == ["check:nightly"]
    assert trigger["trigger"]["strategy"] == "depend"
    assert trigger["trigger"]["forward"] == {"yaml_variables": False}


def test_normal_jobs_stay_out_of_scheduled_pipelines(main):
    for name in ("test", "build"):
        first = main[name]["rules"][0]
        assert first == {
            "if": '$CI_PIPELINE_SOURCE == "schedule"',
            "when": "never",
        }


def test_the_nightly_child_has_the_whole_chain(nightly):
    assert nightly["stages"] == ["test", "build", "publish"]
    assert {"test", "build:nightly", "publish:nightly"} <= set(jobs(nightly))
    assert nightly["build:nightly"]["needs"] == ["test"]
    assert nightly["publish:nightly"]["needs"] == ["build:nightly"]


def test_the_nightly_build_suffixes_the_version_and_numbers_the_binary(nightly):
    build = nightly["build:nightly"]
    assert build["variables"]["BUILD_NUMBER"] == "$CI_PIPELINE_IID"
    assert any(
        "patch_nightly_version.py" in str(step)
        for step in build["before_script"]
    )


def test_the_nightly_publish_records_the_commit_it_built(nightly):
    steps = nightly["publish:nightly"]["script"]
    assert steps[0] == {"reference": [".publish", "script"]}
    assert "nightly-sha.txt" in steps[1]
    assert (
        nightly["publish:nightly"]["variables"]["PACKAGE_VERSION"] == "nightly"
    )


def test_the_gate_and_the_child_agree_on_the_package_name(main, nightly):
    assert main["variables"]["PACKAGE"] == nightly["variables"]["PACKAGE"]
    assert main["variables"]["PACKAGE"] == "phone-webcam"


def test_the_pipeline_passes_the_number_before_the_hash(nightly):
    steps = " ".join(str(s) for s in nightly["build:nightly"]["before_script"])
    assert '"$CI_PIPELINE_IID.$CI_COMMIT_SHORT_SHA"' in steps
