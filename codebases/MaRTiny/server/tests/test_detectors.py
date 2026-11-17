import sys
import textwrap

import numpy as np
import pytest
from PIL import Image

torch = pytest.importorskip("torch")

from martiny_server.config import Settings
from martiny_server.detectors import (NullDetector, NullShadowDetector, ShadowDetector, TorchvisionDetector, YoloDetector,
                                      load_detector, load_shadow_detector)


# ---------- YOLO wrapper, with a fake model so no weights or ultralytics are needed ----------

class _Boxes:
    def __init__(self, xyxy, conf, cls):
        self.xyxy, self.conf, self.cls = np.array(xyxy, float), np.array(conf, float), np.array(cls, float)


class _Result:
    def __init__(self, boxes): self.boxes = boxes
    def numpy(self): return self


class _FakeYolo:
    def __init__(self, boxes): self.boxes, self.calls = boxes, []
    def __call__(self, image, **kw):
        self.calls.append(kw)
        return [_Result(self.boxes)]


def test_yolo_keeps_confident_people_and_pets_and_rounds_boxes():
    fake = _FakeYolo(_Boxes([[10.2, 20.7, 50.1, 90.9], [1, 1, 5, 5], [0, 0, 9, 9], [30, 30, 60, 80]],
                            conf=[0.9, 0.2, 0.8, 0.95], cls=[0, 0, 2, 16]))
    boxes, confs, clss = YoloDetector(model=fake, device="cpu").detect(Image.new("RGB", (64, 48)))
    assert boxes == [[10, 21, 50, 91], [30, 30, 60, 80]]          # low confidence and the car (class 2) are dropped
    assert clss == [0, 16] and confs == [0.9, 0.95]
    assert fake.calls[0]["device"] == "cpu" and fake.calls[0]["imgsz"] == (640, 480)


def test_yolo_confidence_threshold_is_strict():
    fake = _FakeYolo(_Boxes([[0, 0, 5, 5]], conf=[0.3], cls=[0]))
    assert YoloDetector(model=fake, confidence=0.3).detect(Image.new("RGB", (8, 8)))[0] == []


def test_yolo_without_ultralytics_explains_what_to_do(monkeypatch):
    monkeypatch.setitem(sys.modules, "ultralytics", None)          # makes "import ultralytics" fail
    with pytest.raises(RuntimeError, match="ultralytics"):
        YoloDetector()


# ---------- torchvision detector ----------

class _FakeTv(torch.nn.Module):
    def forward(self, images):
        return [{"boxes": torch.tensor([[1.4, 2.6, 30.0, 40.0], [0.0, 0.0, 9.0, 9.0], [5.0, 5.0, 20.0, 20.0], [2.0, 2.0, 8.0, 8.0], [3.0, 3.0, 9.0, 9.0]]),
                 "scores": torch.tensor([0.9, 0.95, 0.8, 0.2, 0.7]),
                 "labels": torch.tensor([1, 3, 18, 1, 28])}]       # person, car, dog, person (weak), umbrella


def test_torchvision_detector_maps_classes_to_yolo_numbers():
    boxes, confs, clss = TorchvisionDetector(model=_FakeTv()).detect(Image.new("RGB", (64, 48)))
    assert clss == [0, 16, 25]                                      # person, dog, umbrella; the car and the weak person are dropped
    assert boxes[0] == [1, 3, 30, 40] and len(boxes) == len(confs) == 3


def test_torchvision_detector_runs_a_real_network_end_to_end():
    pytest.importorskip("torchvision")
    det = TorchvisionDetector(weights=None)                         # random weights: checks the plumbing, not the accuracy
    boxes, confs, clss = det.detect(Image.new("RGB", (96, 72), (120, 110, 100)))
    assert isinstance(boxes, list) and len(boxes) == len(confs) == len(clss)
    assert all(c in (0, 1, 15, 16, 25) for c in clss)


# ---------- shadow detector, with stand-in networks ----------

class _Const(torch.nn.Module):
    def __init__(self, v): super().__init__(); self.v = v
    def forward(self, x): return torch.full((1, 1, x.shape[2], x.shape[3]), self.v)


class _LeftHalf(torch.nn.Module):
    def forward(self, x):
        out = torch.zeros(1, 1, x.shape[2], x.shape[3])
        out[..., : x.shape[3] // 2] = 1.0
        return out


def test_shadow_map_has_the_size_of_the_photo_and_is_8_bit():
    result = ShadowDetector(_Const(0.8)).find_shadow(Image.new("RGB", (80, 60)))
    arr = np.array(result)
    assert result.size == (80, 60) and result.mode == "L" and arr.dtype == np.uint8
    assert abs(int(arr.mean()) - 204) <= 2                          # 0.8 of 255


def test_shadow_map_follows_the_network_output():
    arr = np.array(ShadowDetector(_LeftHalf()).find_shadow(Image.new("RGB", (120, 80))))
    assert arr[:, :40].mean() > 200 and arr[:, 80:].mean() < 50


def test_shadow_refine_hook_receives_rgb_and_map_of_the_same_size():
    seen = {}
    def refine(rgb, m):
        seen["rgb"], seen["map"] = rgb.shape, m.shape
        return np.zeros_like(m)
    out = ShadowDetector(_Const(1.0), refine=refine).find_shadow(Image.new("RGB", (50, 30)))
    assert seen == {"rgb": (30, 50, 3), "map": (30, 50)} and np.array(out).max() == 0


def test_shadow_detector_accepts_grayscale_and_rgba_photos():
    for mode in ("L", "RGBA"):
        assert ShadowDetector(_Const(0.5)).find_shadow(Image.new(mode, (40, 30))).size == (40, 30)


def test_null_detectors_do_nothing_safely():
    assert NullDetector().detect(Image.new("RGB", (4, 4))) == ([], [], [])
    assert np.array(NullShadowDetector().find_shadow(Image.new("RGB", (6, 4)))).max() == 0


def test_network_factory_spec(tmp_path, monkeypatch):
    (tmp_path / "my_shadow_net.py").write_text(textwrap.dedent("""
        import torch
        def build():
            return torch.nn.Identity()
        def build_with_refine():
            return torch.nn.Identity(), (lambda rgb, m: m)
    """))
    monkeypatch.syspath_prepend(str(tmp_path))
    assert isinstance(load_shadow_detector("my_shadow_net:build"), ShadowDetector)
    assert load_shadow_detector("my_shadow_net:build_with_refine").refine is not None
    assert isinstance(load_shadow_detector("none"), NullShadowDetector)
    with pytest.raises(ValueError, match="module:function"):
        load_shadow_detector("nonsense")
    with pytest.raises(RuntimeError, match="cannot import"):
        load_shadow_detector("no_such_module_xyz:build")
    with pytest.raises(RuntimeError, match="no function"):
        load_shadow_detector("my_shadow_net:missing")


def test_load_detector_from_settings():
    assert isinstance(load_detector(Settings(detector="none")), NullDetector)
    with pytest.raises(ValueError, match="unknown MARTINY_DETECTOR"):
        load_detector(Settings(detector="mystery"))
