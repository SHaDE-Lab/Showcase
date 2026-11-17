"""Tests for the MaRTiny firmware logic.

The two C++ programs in this folder compile the same header files the Arduino Uno and ESP32-CAM sketches use, and run them on
this computer. This file builds and runs them, then checks their output with independent Python code:
the JSON line must parse, the averages must match a Python calculation, and URL encoding must round-trip.

It needs a C++ compiler (g++, clang++, or Visual Studio Build Tools on Windows). Without one the tests are skipped.
Run:  python -m pytest
"""
import glob
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import unquote_plus

import pytest

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"


def _find_compiler():
    """Returns a function build(source, exe) -> None, or None when no compiler is available."""
    for name in ("g++", "clang++", "c++"):
        path = shutil.which(name)
        if path:
            def build(src, exe, path=path):
                subprocess.run([path, "-std=c++17", "-Wall", "-Wextra", "-O1", "-o", str(exe), str(src)],
                               check=True, capture_output=True, text=True)
            return build
    pattern = "C:/Program Files*/Microsoft Visual Studio/*/*/VC/Auxiliary/Build/vcvars64.bat"
    found = sorted(glob.glob(pattern))
    if os.name == "nt" and found:
        vcvars = found[-1]
        def build(src, exe):
            obj = Path(exe).parent
            bat = obj / "build.bat"                       # a batch file avoids cmd's quoting rules
            lines = ["@echo off", f'cd /d "{obj}"', f'call "{vcvars}" >nul 2>nul', f'cl /nologo /std:c++17 /EHsc /W3 /Fe"{exe}" "{src}"']   # objects land in the temp folder
            bat.write_text("\r\n".join(lines) + "\r\n")
            subprocess.run([str(bat)], check=True, capture_output=True, text=True)
        return build
    return None


BUILD = _find_compiler()
needs_compiler = pytest.mark.skipif(BUILD is None, reason="no C++ compiler found (install g++, clang++ or Visual Studio Build Tools)")


@pytest.fixture(scope="session")
def results():
    """Builds and runs both test programs once; returns their output lines."""
    if BUILD is None:
        pytest.skip("no C++ compiler")
    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        for name in ("test_sensors", "test_net"):
            exe = Path(tmp) / (name + (".exe" if os.name == "nt" else ""))
            try:
                BUILD(TESTS / f"{name}.cpp", exe)
            except subprocess.CalledProcessError as e:
                pytest.fail(f"{name}.cpp failed to compile:\n{e.stdout}\n{e.stderr}")
            run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
            out[name] = (run.returncode, run.stdout.splitlines())
    return out


def _data(lines, key):
    return [l.split(" ", 2)[2] for l in lines if l.startswith(f"DATA {key} ")]


@needs_compiler
@pytest.mark.parametrize("name", ["test_sensors", "test_net"])
def test_every_cpp_check_passes(results, name):
    code, lines = results[name]
    failed = [l for l in lines if l.startswith("FAIL")]
    assert not failed, "\n".join(failed)
    assert code == 0
    assert any("checks, 0 failed" in l for l in lines)


@needs_compiler
def test_message_is_valid_json_with_correct_averages(results):
    _, lines = results["test_sensors"]
    msg = json.loads(_data(lines, "message")[0])
    assert list(msg) == ["Temperature", "Humidity", "UV_Intensity", "Dallas1", "Dallas2", "Wind_Speed", "Battery_Voltage"]
    assert msg["Temperature"] == pytest.approx((20.0 + 30.0) / 2)        # the failed DHT22 read is not counted
    assert msg["Humidity"] == pytest.approx((40.0 + 60.0) / 2)
    assert msg["UV_Intensity"] == pytest.approx((2.0 + 4.0) / 2)
    assert msg["Wind_Speed"] == pytest.approx((4.0 + 6.0) / 2)
    assert msg["Dallas1"] == pytest.approx((25.0 + 27.0) / 2)            # the -127 reading is not counted
    assert msg["Dallas2"] is None                                        # no valid reading: null, not a made-up number
    assert msg["Battery_Voltage"] == pytest.approx(7.25)


@needs_compiler
def test_message_with_no_readings_is_valid_json(results):
    _, lines = results["test_sensors"]
    msg = json.loads(_data(lines, "empty")[0])
    assert msg["Temperature"] is None and msg["UV_Intensity"] is None and msg["Wind_Speed"] is None
    assert msg["Battery_Voltage"] == 0


@needs_compiler
def test_urlencode_round_trips_through_python(results):
    _, lines = results["test_net"]
    pairs = _data(lines, "enc")
    assert len(pairs) >= 5
    for entry in pairs:
        original_hex, encoded = entry.split(" ", 1)
        original = bytes.fromhex(original_hex).decode("utf-8")
        assert re.fullmatch(r"[A-Za-z0-9+%]*", encoded), encoded        # nothing that could break a URL query
        assert unquote_plus(encoded) == original


@needs_compiler
def test_end_to_end_message_survives_the_wire(results):
    _, lines = results["test_net"]
    wire = _data(lines, "wire")[0]
    original = _data(lines, "original")[0]
    assert unquote_plus(wire) == original
    msg = json.loads(unquote_plus(wire))
    assert msg["Temperature"] == pytest.approx(31.5) and msg["Dallas2"] == pytest.approx(54.9)


# ---- these tests need no compiler ----

FIRMWARE = ROOT / "firmware"
TEXT = {".ino", ".h", ".cpp", ".py", ".md", ".cff", ".js", ".json", ".yml", ".yaml", ".txt", ".example", ".toml", ".gitignore"}
SOURCES = [p for p in ROOT.rglob("*") if p.is_file() and (p.suffix in TEXT or p.name.startswith(".env")) and "__pycache__" not in p.parts and "node_modules" not in p.parts]


def test_no_credentials_or_private_addresses_in_the_repository():
    """The original sketch had a Wi-Fi password and the lab's server address in it. Neither may come back."""
    forbidden = ["MaRTiny123", "MaRTinyAP", "sensableheatscapes", "martiny.sensable", "ingest.sentry.io", "mongodb+srv://", "vercel.app", "o4506160943071232"]
    hits = []
    for p in SOURCES:
        if p.name == "test_firmware.py":
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        hits += [f"{p.relative_to(ROOT)}: {w}" for w in forbidden if w in text]
    assert not hits, hits


def test_sketches_read_settings_from_config_h():
    esp = (FIRMWARE / "MaRTiny-ESP32" / "MaRTiny-ESP32.ino").read_text(encoding="utf-8")
    assert '#include "config.h"' in esp
    for macro in ("MARTINY_WIFI_SSID", "MARTINY_WIFI_PASSWORD", "MARTINY_SERVER_HOST", "MARTINY_DATA_PORT", "MARTINY_IMAGE_PORT"):
        assert macro in esp
    assert not re.search(r'WiFi\.begin\(\s*"', esp), "Wi-Fi credentials must not be string literals"


def test_example_config_has_only_placeholders_and_real_config_is_ignored():
    cfg = (FIRMWARE / "MaRTiny-ESP32" / "config.example.h").read_text(encoding="utf-8")
    assert "your-wifi-password" in cfg and "your-server.example.org" in cfg
    assert not (FIRMWARE / "MaRTiny-ESP32" / "config.h").exists() or "config.h" in (ROOT / ".gitignore").read_text()
    assert "config.h" in (ROOT / ".gitignore").read_text()


def test_every_source_carries_the_license_notice():
    for p in [*FIRMWARE.rglob("*.ino"), FIRMWARE / "MaRTiny-Arduino" / "martiny_sensors.h", FIRMWARE / "MaRTiny-ESP32" / "martiny_net.h"]:
        assert "CERN-OHL-P v2" in p.read_text(encoding="utf-8"), p.name


def test_no_model_weights_or_large_files_are_committed():
    """The weights are 170 MB and 177 MB and their licenses are unclear: they must stay out of the repository."""
    banned = {".pt", ".pth", ".onnx", ".weights", ".ckpt", ".safetensors"}
    files = [p for p in ROOT.rglob("*") if p.is_file() and "node_modules" not in p.parts and ".pytest_cache" not in p.parts]
    assert not [p for p in files if p.suffix in banned], "model weights found"
    assert not [p for p in files if p.stat().st_size > 5 * 1024 * 1024], "file larger than 5 MB found"


def test_server_and_model_sources_carry_the_license_notice():
    for p in [*(ROOT / "server").rglob("*.py"), *(ROOT / "server" / "edge").glob("*.js"), *(ROOT / "models").glob("*.py")]:
        if "tests" in p.parts or "__pycache__" in p.parts or p.name == "conftest.py":
            continue
        assert "CERN-OHL-P-2.0" in p.read_text(encoding="utf-8"), str(p.relative_to(ROOT))


def test_environment_files_in_the_repository_are_only_examples():
    envs = [p for p in ROOT.rglob(".env*") if p.is_file() and "node_modules" not in p.parts]
    assert envs and all(p.name == ".env.example" for p in envs), [str(p) for p in envs]
    for p in envs:
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.startswith(("MONGO_URL=", "SENTRY_DSN=")):
                assert line.split("=", 1)[1].strip() == "", f"{p.name}: {line}"          # no real address or key in an example
