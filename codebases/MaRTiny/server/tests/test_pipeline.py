import base64
from io import BytesIO

import numpy as np
from PIL import Image

from martiny_server.pipeline import Pipeline


class FakeDetector:
    def __init__(self, boxes): self.boxes, self.calls = boxes, 0
    def detect(self, image):
        self.calls += 1
        return [list(b) for b in self.boxes], [0.9] * len(self.boxes), [0] * len(self.boxes)


class FakeShadow:
    """Left half of the photo in shadow."""
    def __init__(self): self.calls = 0
    def find_shadow(self, image):
        self.calls += 1
        a = np.zeros((image.size[1], image.size[0]), np.uint8)
        a[:, : image.size[0] // 2] = 255
        return Image.fromarray(a)


class Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t


def make(boxes=((0, 0, 20, 20), (70, 0, 95, 30)), **kw):
    det, sh, clock = FakeDetector(boxes), FakeShadow(), Clock()
    return Pipeline(det, sh, clock=clock, **kw), det, sh, clock


PHOTO = Image.new("RGB", (100, 50), (90, 120, 150))
MAC = "24_6F_28_AA_BB_CC"


def test_result_has_the_fields_the_viewer_reads():
    pipe, *_ = make()
    doc = pipe.process(PHOTO, MAC)
    assert doc["mac"] == "24:6F:28:AA:BB:CC" and doc["_id"].startswith(MAC + "_")
    assert doc["boxes"] == [[0, 0, 20, 20], [70, 0, 95, 30]] and doc["clss"] == [0, 0] and doc["confs"] == [0.9, 0.9]
    assert doc["isInShadow"] == [1, 0]                             # first person on the shadowed half, second in sun
    assert isinstance(doc["time"], int) and len(doc["readableTime"]) >= 19


def test_photographs_are_not_stored_unless_asked():
    pipe, *_ = make()
    doc = pipe.process(PHOTO, MAC)
    assert "originalImage" not in doc and "shadow" not in doc


def test_photographs_are_stored_when_asked_and_decode_back():
    pipe, *_ = make(store_images=True)
    doc = pipe.process(PHOTO, MAC)
    assert Image.open(BytesIO(base64.b64decode(doc["originalImage"]))).size == (100, 50)
    assert Image.open(BytesIO(base64.b64decode(doc["shadow"]))).size == (100, 50)


def test_shadow_map_is_reused_until_the_interval_has_passed():
    pipe, det, sh, clock = make(shadow_update_interval_s=60)
    for _ in range(3):
        pipe.process(PHOTO, MAC); clock.t += 10
    assert sh.calls == 1 and det.calls == 3                       # people are detected on every photo
    clock.t += 31                                                  # 61 s after the first map
    pipe.process(PHOTO, MAC)
    assert sh.calls == 2


def test_interval_zero_recomputes_the_shadow_every_time():
    pipe, _, sh, _ = make(shadow_update_interval_s=0)
    for _ in range(3):
        pipe.process(PHOTO, MAC)
    assert sh.calls == 3


def test_each_device_has_its_own_shadow_map():
    pipe, _, sh, _ = make()
    pipe.process(PHOTO, "24_6F_28_AA_BB_CC")
    pipe.process(PHOTO, "24_6F_28_AA_BB_DD")
    assert sh.calls == 2


def test_overlap_fraction_is_configurable():
    pipe, *_ = make(boxes=((40, 0, 59, 19),), overlap_fraction=0.5)   # 10 of 20 columns in shadow = exactly 50 %
    assert pipe.process(PHOTO, MAC)["isInShadow"] == [1]
    pipe, *_ = make(boxes=((40, 0, 59, 19),), overlap_fraction=0.51)
    assert pipe.process(PHOTO, MAC)["isInShadow"] == [0]
