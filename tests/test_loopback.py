"""Tests for finding and provisioning the loopback devices."""

from phone_webcam import loopback


def make_sysfs(tmp_path, names):
    for node, name in names.items():
        (tmp_path / node).mkdir()
        (tmp_path / node / "name").write_text(name + "\n")
    return tmp_path


def test_find_device_matches_card_label(tmp_path):
    sysfs = make_sysfs(
        tmp_path, {"video0": "Integrated Camera", "video2": "Android Webcam"}
    )
    assert loopback.find_device("Android Webcam", sysfs) == "/dev/video2"


def test_find_device_does_not_confuse_prefixes(tmp_path):
    sysfs = make_sysfs(tmp_path, {"video3": "Android Webcam Source"})
    assert loopback.find_device("Android Webcam", sysfs) is None


def test_missing_labels_lists_only_absent_devices(tmp_path):
    sysfs = make_sysfs(tmp_path, {"video1": loopback.OUTPUT_LABEL})
    assert loopback.missing_labels(sysfs=sysfs) == [loopback.SOURCE_LABEL]


def test_module_in_use_reads_the_refcount(tmp_path):
    count = tmp_path / "refcnt"
    count.write_text("2\n")
    assert loopback.module_in_use(count) is True
    count.write_text("0\n")
    assert loopback.module_in_use(count) is False
    assert loopback.module_in_use(tmp_path / "gone") is False


def test_load_command_creates_every_device_in_one_call():
    cmd = loopback.load_command()
    assert cmd[:3] == ["pkexec", "sh", "-c"]
    assert "devices=2" in cmd[3]
    assert "exclusive_caps=1,1" in cmd[3]
    assert "'Android Webcam Source,Android Webcam'" in cmd[3]


def test_reload_command_unloads_first():
    assert loopback.reload_command()[3].startswith(
        "modprobe -r v4l2loopback && modprobe v4l2loopback"
    )


def test_add_command_only_adds_what_is_missing():
    cmd = loopback.add_command(["Android Webcam Source"])
    assert cmd[3] == ("v4l2loopback-ctl add -x 1 -n 'Android Webcam Source'")
