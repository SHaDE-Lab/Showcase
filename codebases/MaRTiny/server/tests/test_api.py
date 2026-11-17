import base64
import json
from io import BytesIO

import pytest
from PIL import Image

from martiny_server.api import create_app
from martiny_server.config import Settings
from martiny_server.detectors import NullDetector, NullShadowDetector
from martiny_server.pipeline import Pipeline
from martiny_server.store import MemDb, RESULTS, Store

MAC = "24_6F_28_AA_BB_CC"


def png(size=(32, 24)):
    buf = BytesIO(); Image.new("RGB", size, (10, 200, 30)).save(buf, "PNG"); return buf.getvalue()


@pytest.fixture
def parts():
    settings = Settings(max_upload_mb=1.0)
    store = Store(MemDb())
    app = create_app(Pipeline(NullDetector(), NullShadowDetector()), store, settings)
    return app.test_client(), store


def post(client, path="/api/v1/", **form):
    data = {k: v for k, v in form.items()}
    return client.post(path, data=data, content_type="multipart/form-data")


def test_photo_upload_is_analysed_and_stored(parts):
    client, store = parts
    r = post(client, uuid=MAC, image=(BytesIO(png()), "esp32-cam.jpg"))
    assert r.status_code == 200 and r.get_data(as_text=True) == "Success"
    docs = store.db[RESULTS].docs
    assert len(docs) == 1 and docs[0]["mac"] == "24:6F:28:AA:BB:CC" and docs[0]["isInShadow"] == []


def test_device_id_with_colons_is_accepted(parts):
    client, store = parts
    assert post(client, uuid="24:6F:28:AA:BB:CC", image=(BytesIO(png()), "a.jpg")).status_code == 200


def test_get_all_results_returns_the_stored_document(parts):
    client, store = parts
    r = post(client, "/api/v1/getAllResults", uuid=MAC, image=(BytesIO(png()), "a.jpg"))
    body = r.get_json()
    assert r.status_code == 200 and body["mac"] == "24:6F:28:AA:BB:CC" and body["_id"] == store.db[RESULTS].docs[0]["_id"]


def test_base64_image_field_works(parts):
    client, store = parts
    r = post(client, uuid=MAC, image=base64.b64encode(png()).decode())
    assert r.status_code == 200 and len(store.db[RESULTS].docs) == 1


@pytest.mark.parametrize("form,message", [
    ({"uuid": MAC}, "Image must be attached"),
    ({"image": base64.b64encode(png()).decode()}, "UUID must be attached"),
    ({"uuid": "../../etc/passwd", "image": base64.b64encode(png()).decode()}, "MAC address"),
    ({"uuid": "{'$ne': 1}", "image": base64.b64encode(png()).decode()}, "MAC address"),
    ({"uuid": MAC, "image": "not base64 !!!"}, "Invalid image"),
    ({"uuid": MAC, "image": base64.b64encode(b"this is not a picture").decode()}, "Invalid image"),
])
def test_bad_requests_get_400_and_store_nothing(parts, form, message):
    client, store = parts
    r = post(client, **form)
    assert r.status_code == 400 and message in r.get_data(as_text=True)
    assert store.db[RESULTS].docs == []


def test_non_image_file_upload_is_rejected(parts):
    client, store = parts
    r = post(client, uuid=MAC, image=(BytesIO(b"plain text"), "a.jpg"))
    assert r.status_code == 400 and store.db[RESULTS].docs == []


def test_oversized_upload_is_refused(parts):
    client, store = parts
    r = post(client, uuid=MAC, image=(BytesIO(b"0" * (2 * 1024 * 1024)), "big.jpg"))
    assert r.status_code == 413 and store.db[RESULTS].docs == []


def test_unknown_verb_still_answers(parts):
    client, _ = parts
    r = post(client, "/api/v1/whatever", uuid=MAC, image=(BytesIO(png()), "a.jpg"))
    assert r.status_code == 200 and "getAllResults" in r.get_data(as_text=True)


def test_healthz(parts):
    assert parts[0].get("/healthz").get_json() == {"status": "ok"}


def test_cors_header_only_when_configured():
    store = Store(MemDb())
    for origin in (None, "https://viewer.example.org"):
        app = create_app(Pipeline(NullDetector(), NullShadowDetector()), store, Settings(cors_origin=origin))
        header = app.test_client().get("/healthz").headers.get("Access-Control-Allow-Origin")
        assert header == origin
