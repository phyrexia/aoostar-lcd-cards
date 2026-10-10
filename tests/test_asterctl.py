"""The asterctl wrapper and installer, with a fake binary: no hardware, no network."""

import hashlib
import io
import logging
import os
import shutil
import subprocess
import tarfile
import textwrap
from pathlib import Path

import pytest
from PIL import Image

from aoostar_lcd import asterctl as mod
from aoostar_lcd.asterctl import (
    Asterctl,
    AsterctlError,
    AsterctlNotFoundError,
    AsterctlVersionError,
)
from aoostar_lcd.config import DisplayConfig
from aoostar_lcd.display import AsterctlSink, make_sink

from .conftest import ROOT

pytestmark = pytest.mark.skipif(os.name != "posix", reason="fake binary is a shell script")


def fake_asterctl(directory: Path, version="0.2.0", exit_code=0, sleep=0, stderr="") -> Path:
    """A shell script that behaves like asterctl and logs its arguments."""
    path = directory / "asterctl"
    log = directory / "calls.log"
    path.write_text(
        textwrap.dedent(f"""\
        #!/bin/sh
        if [ "$1" = "--version" ]; then echo "asterctl {version}"; exit 0; fi
        echo "$@" >> "{log}"
        sleep {sleep}
        [ -n "{stderr}" ] && echo "{stderr}" >&2
        exit {exit_code}
    """)
    )
    path.chmod(0o755)
    return path


def calls(directory: Path) -> list[str]:
    log = directory / "calls.log"
    return log.read_text().splitlines() if log.exists() else []


def frame(tmp_path) -> Path:
    path = tmp_path / "frame.png"
    Image.new("RGB", (960, 376)).save(path)
    return path


def test_version_check_and_send_image_with_device(tmp_path):
    binary = fake_asterctl(tmp_path)
    tool = Asterctl(binary=str(binary), device="/dev/ttyACM0")
    assert tool.check() == (0, 2, 0)
    tool.send_image(frame(tmp_path))
    tool.off()
    tool.on()
    assert calls(tmp_path) == [
        f"--device /dev/ttyACM0 --image {tmp_path / 'frame.png'}",
        "--device /dev/ttyACM0 --off",
        "--device /dev/ttyACM0 --on",
    ]


def test_usb_and_simulate_targets(tmp_path):
    binary = fake_asterctl(tmp_path)
    Asterctl(binary=str(binary), usb="416:90A1").on()
    Asterctl(binary=str(binary), device="/dev/x", simulate=True).on()
    Asterctl(binary=str(binary)).on()
    assert calls(tmp_path) == ["--usb 416:90A1 --on", "--simulate --on", "--on"]


def test_binary_found_in_path(tmp_path, monkeypatch):
    fake_asterctl(tmp_path)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    assert Asterctl().path() == str(tmp_path / "asterctl")


def test_missing_binary_has_an_install_hint(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(AsterctlNotFoundError, match="install-asterctl.sh"):
        Asterctl().check()
    with pytest.raises(AsterctlNotFoundError, match="not found or not executable"):
        Asterctl(binary=str(tmp_path / "nope")).check()
    plain = tmp_path / "asterctl"
    plain.write_text("not executable")
    with pytest.raises(AsterctlNotFoundError):
        Asterctl(binary=str(plain)).check()


def test_old_version_is_rejected(tmp_path):
    binary = fake_asterctl(tmp_path, version="0.1.0")
    with pytest.raises(AsterctlVersionError, match=r"0\.1\.0 is too old.*>= 0\.2\.0"):
        Asterctl(binary=str(binary)).check()


def test_failure_and_timeout_are_reported(tmp_path):
    failing = fake_asterctl(tmp_path, exit_code=3, stderr="serial port busy")
    with pytest.raises(AsterctlError, match="exited with 3: serial port busy"):
        Asterctl(binary=str(failing)).send_image(frame(tmp_path))
    slow_dir = tmp_path / "slow"
    slow_dir.mkdir()
    slow = fake_asterctl(slow_dir, sleep=5)
    with pytest.raises(AsterctlError, match="timed out after 1 s"):
        Asterctl(binary=str(slow), timeout=1).send_image(frame(tmp_path))
    with pytest.raises(AsterctlError, match="image not found"):
        Asterctl(binary=str(failing)).send_image(tmp_path / "missing.png")


def test_unparsable_version(tmp_path):
    binary = tmp_path / "asterctl"
    binary.write_text("#!/bin/sh\necho 'something else'\n")
    binary.chmod(0o755)
    with pytest.raises(AsterctlError, match="cannot read the asterctl version"):
        Asterctl(binary=str(binary)).version()


def test_sink_logs_errors_once_and_keeps_running(tmp_path, caplog):
    failing = fake_asterctl(tmp_path, exit_code=1, stderr="no device")
    sink = AsterctlSink(Asterctl(binary=str(failing)))
    image = Image.new("RGB", (960, 376))
    with caplog.at_level(logging.ERROR):
        assert sink.show(image) is False
        assert sink.show(image) is False
    assert caplog.text.count("no device") == 1
    tmpdir = sink.tmpdir
    assert oct(os.stat(tmpdir).st_mode & 0o777) == "0o700"
    sink.close()
    assert not os.path.exists(tmpdir)


def test_make_sink_checks_asterctl_up_front(tmp_path):
    with pytest.raises(AsterctlNotFoundError):
        make_sink(DisplayConfig(asterctl=str(tmp_path / "missing")))
    sink = make_sink(DisplayConfig(asterctl=str(fake_asterctl(tmp_path))))
    assert isinstance(sink, AsterctlSink)
    sink.close()


# -- the pin file, shared by the installer, the Dockerfile and CI ------------------------


def read_pin(path: Path) -> dict[str, str]:
    pairs = {}
    for line in path.read_text().splitlines():
        if line and not line.startswith("#"):
            key, _, value = line.partition("=")
            pairs[key] = value
    return pairs


def test_pin_file_matches_the_python_wrapper():
    pin = read_pin(ROOT / "asterctl.version")
    assert pin["ASTERCTL_TAG"] == mod.PINNED_TAG
    assert mod.parse_version(pin["ASTERCTL_TAG"]) >= mod.MIN_VERSION
    assert len(pin["ASTERCTL_COMMIT"]) == 40 and len(pin["ASTERCTL_LINUX_X64_SHA256"]) == 64
    assert pin["ASTERCTL_REPO"] == "https://github.com/zehnm/aoostar-rs"


def test_dockerfile_and_ci_use_the_pin_file():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert dockerfile.count("COPY asterctl.version") == 2
    assert "install-asterctl.sh --from source" in dockerfile
    assert "install-asterctl.sh --from release" in dockerfile
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "--print-pin" in ci and "git ls-remote" in ci


INSTALLER = ROOT / "scripts" / "install-asterctl.sh"


def run_installer(*args, env=None):
    return subprocess.run(
        ["sh", str(INSTALLER), *args],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, **(env or {})},
    )


def test_installer_prints_the_pin():
    result = run_installer("--print-pin")
    assert result.returncode == 0
    assert "tag=v0.2.0" in result.stdout and "commit=078dc267" in result.stdout


@pytest.mark.skipif(shutil.which("curl") is None, reason="needs curl")
def test_installer_checks_the_checksum_and_is_idempotent(tmp_path):
    # A local "release" with a fake asterctl inside, served through file://.
    fake_dir = tmp_path / "fake"
    fake_dir.mkdir()
    fake = fake_asterctl(fake_dir, version="9.8.7")
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        tar.add(fake, arcname="./asterctl")
    archive = buffer.getvalue()
    release = tmp_path / "mirror" / "v9.8.7"
    release.mkdir(parents=True)
    (release / "asterctl-v9.8.7-Linux-x64.tar.gz").write_bytes(archive)
    good = hashlib.sha256(archive).hexdigest()

    def pin(sha):
        path = tmp_path / f"pin-{sha[:6]}"
        path.write_text(
            f"ASTERCTL_REPO=https://example.invalid/repo\nASTERCTL_TAG=v9.8.7\n"
            f"ASTERCTL_COMMIT={'a' * 40}\nASTERCTL_LINUX_X64_SHA256={sha}\n"
        )
        return path

    env = {"ASTERCTL_RELEASE_BASE_URL": f"file://{tmp_path / 'mirror'}"}
    prefix = tmp_path / "prefix"
    bad = run_installer(
        "--from", "release", "--prefix", str(prefix), "--version-file", str(pin("0" * 64)), env=env
    )
    assert bad.returncode != 0 and "checksum mismatch" in bad.stderr
    assert not (prefix / "bin" / "asterctl").exists()

    ok = run_installer(
        "--from", "release", "--prefix", str(prefix), "--version-file", str(pin(good)), env=env
    )
    assert ok.returncode == 0, ok.stderr
    assert "installed asterctl 9.8.7" in ok.stderr
    assert (prefix / "share" / "doc" / "asterctl" / "LICENSE-MIT").exists()
    again = run_installer(
        "--from", "release", "--prefix", str(prefix), "--version-file", str(pin(good)), env=env
    )
    assert again.returncode == 0 and "already installed" in again.stderr


def test_installer_rejects_a_malformed_pin(tmp_path):
    path = tmp_path / "pin"
    path.write_text("ASTERCTL_REPO=x\nASTERCTL_TAG=$(reboot)\nASTERCTL_COMMIT=1\n")
    result = run_installer("--version-file", str(path), "--print-pin")
    assert result.returncode != 0 and "missing or malformed" in result.stderr
