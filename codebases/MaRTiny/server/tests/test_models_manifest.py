import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

MODELS = Path(__file__).resolve().parents[2] / "models"
spec = importlib.util.spec_from_file_location("verify_models", MODELS / "verify_models.py")
vm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vm)


def manifest(path: Path, content: bytes, **override):
    entry = {"name": "m", "file": "w/m.pth", "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest(), "obtain": "somewhere", "checked": True}
    entry.update(override)
    return {"models": [entry]}


def test_real_manifest_is_well_formed():
    data = json.loads((MODELS / "models.json").read_text(encoding="utf-8"))
    for m in data["models"]:
        assert {"name", "file", "obtain", "license", "checked"} <= set(m)
        if m["checked"]:
            assert len(m["sha256"]) == 64 and m["bytes"] > 0


def test_every_state_is_reported(tmp_path):
    data = b"pretend weights"
    (tmp_path / "w").mkdir()
    f = tmp_path / "w" / "m.pth"
    assert vm.verify(tmp_path, manifest(tmp_path, data))[0][2] == "missing"
    f.write_bytes(data)
    assert vm.verify(tmp_path, manifest(tmp_path, data))[0][2] == "ok"
    f.write_bytes(b"x" * len(data))                                  # same size, different content
    assert vm.verify(tmp_path, manifest(tmp_path, data))[0][2] == "wrong-hash"
    f.write_bytes(b"short")
    assert vm.verify(tmp_path, manifest(tmp_path, data))[0][2] == "wrong-size"
    assert vm.verify(tmp_path, manifest(tmp_path, data, checked=False))[0][2] == "unchecked"


def test_exit_code_is_nonzero_only_when_a_checked_file_is_wrong(tmp_path):
    data = b"w"
    m = tmp_path / "models.json"
    m.write_text(json.dumps(manifest(tmp_path, data)), encoding="utf-8")
    assert vm.main(["--dir", str(tmp_path), "--manifest", str(m)]) == 1       # missing
    (tmp_path / "w").mkdir(); (tmp_path / "w" / "m.pth").write_bytes(data)
    assert vm.main(["--dir", str(tmp_path), "--manifest", str(m)]) == 0


@pytest.mark.skipif(not os.environ.get("MARTINY_LAB_MODELS_DIR"), reason="set MARTINY_LAB_MODELS_DIR to the folder holding BDRAR/ckpt/3000.pth to check your real files")
def test_the_labs_real_weight_files_match_the_manifest():
    assert vm.main(["--dir", os.environ["MARTINY_LAB_MODELS_DIR"]]) == 0


def test_the_repository_itself_holds_no_weights():
    assert not list(MODELS.rglob("*.pth")) and not list(MODELS.rglob("*.pt"))
