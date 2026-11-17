# MaRTiny server

The software that receives what a MaRTiny sends and looks after the database. Two small services, as in the lab's deployment:

| Service | Folder | Receives | Does |
|---|---|---|---|
| **Image server** (Python, Flask) | `martiny_server/`, `server.py` | the photo, as a multipart POST (port 8080) | finds people (YOLO), finds the shadow, counts who is in shade, stores the result in MongoDB |
| **Data collector** (Node, Express) | `edge/` | the sensor message, as an HTTP GET (port 8081) | checks it, stores it in MongoDB, and serves data to a viewer |

Plus `tools/db_admin.py` for looking after the database, and `../models/` for the machine-learning models.

```
ESP32-CAM ──photo──►  image server (8080) ──► MongoDB "shadow"  ◄── data collector (8081) ◄──data── ESP32-CAM
                       YOLO + shadow map         people, in shade        also serves /getLatest … to the viewer
```

## Run the image server

```bash
cd codebases/MaRTiny/server
pip install -r requirements.txt
cp .env.example .env          # then edit it
python server.py
```

With no `MONGO_URL` it keeps data in memory (development only). With `MARTINY_DETECTOR=none` and `MARTINY_SHADOW_NETWORK=none` it runs without any model, which is how to try the plumbing. For the real models see [`../models/README.md`](../models/README.md).

| Endpoint | Does |
|---|---|
| `POST /api/v1/` | form fields `uuid` (the device's MAC, `24_6F_28_AA_BB_CC`) and `image` (a file, or base64 text) → `Success` |
| `POST /api/v1/getAllResults` | the same, and returns the stored result as JSON |
| `GET /healthz` | liveness |

Each result is one document in the `shadow` collection: `mac`, `time`, `readableTime`, `boxes`, `confs`, `clss` (what was found), and `isInShadow` (1 or 0 for each box).

## Run the data collector

```bash
cd codebases/MaRTiny/server/edge
npm install
cp .env.example .env          # set MONGO_URL
node server.js
```

| Endpoint | Does |
|---|---|
| `GET /updateData?data={json}&mac=AA:BB:…` | store one sensor message. This is the firmware's request, so it stays a GET. |
| `GET /getIds` | device ids that have sent data |
| `GET /getLatest?id=…&limit=10` | newest messages, one device or all |
| `GET /getLatestImageData?id=…` | newest analysed photo of a device |
| `GET /healthz` | liveness |

## The database

MongoDB, database `martiny-studio` (set `MONGO_DB` to change it), two collections:

| Collection | One document per | Fields |
|---|---|---|
| `data` | sensor message | `mac`, `time` (ms), `Temperature`, `Humidity`, `UV_Intensity`, `Dallas1`, `Dallas2`, `Wind_Speed`, `Battery_Voltage` (each a number or `null`) |
| `shadow` | analysed photo | `_id`, `mac`, `time` (s), `readableTime`, `boxes`, `confs`, `clss`, `isInShadow`, and, only if you turn on `STORE_IMAGES`, `shadow` and `originalImage` (base64 JPEG) |

Both services create an index on `(mac, time)` at start. **Photographs are not stored unless you set `STORE_IMAGES=true`**: they show people, and the counts are what the research needs.

### Looking after it

```bash
python tools/db_admin.py stats                          # documents and devices in each collection
python tools/db_admin.py indexes                        # (re)create the indexes
python tools/db_admin.py prune --days 365 --dry-run     # see what deleting data older than a year would remove
python tools/db_admin.py prune --days 365               # do it
python tools/db_admin.py strip-images --days 7          # keep the counts, drop stored photos older than a week
python tools/db_admin.py export data --out data.csv     # or .json; add --mac and --limit
```

It manages the database in `MONGO_URL`. Run `mongodump --uri "$MONGO_URL" --out backup/` before pruning.

## What changed from the lab's working server

Same pipeline and the same document shapes. Deliberate differences:

* **Secrets out of the code.** A Sentry key was written into `server.py`; it is now the optional `SENTRY_DSN`. The database address comes from `MONGO_URL`, and the redirect to the lab's viewer from `VIEW_URL`.
* **Photographs off by default.** The working server stored every original photo and shadow map in the database; now only the counts are kept unless `STORE_IMAGES=true`.
* **Shadow map cached properly.** The old code recomputed the map for every photo (a development switch was left on). It is now reused for `SHADOW_UPDATE_INTERVAL_S` seconds per device (default 60; set 0 for the old behaviour).
* **Input checked.** The device id must be a MAC address, uploads are size-limited, and a bad image gets a 400. In the data collector, a request such as `?id[$ne]=x` could previously reach a database query; ids must now be plain MAC strings, and a sensor message may contain only the seven known numeric fields.
* **Fewer open doors.** No CORS headers unless `CORS_ORIGIN` is set (it was open to everyone), and the collector no longer accepts 50 MB request bodies it never uses.
* **Newest first by time.** Queries sort by `time` rather than insertion order.
* **Detector choice.** `torchvision` is offered next to YOLO, because YOLOv8 is AGPL-3.0 (see the models README).

## Tests

```bash
cd codebases/MaRTiny/server
python -m pytest                         # 74 tests, about 15 s (a 75th checks your real weight files if MARTINY_LAB_MODELS_DIR is set)
cd edge && npm install && npm test       # 9 tests
```

They cover the shade geometry, the detectors and shadow wrapper (including a real torchvision network and a stand-in shadow network), the caching, the database layer, the web API, the admin tool and the collector. They deliberately break the code in places to check the tests notice.

What is **not** covered: they use an in-memory stand-in for MongoDB that offers the same calls, not a real MongoDB server, so run `python tools/db_admin.py stats` against yours before relying on the database code. YOLO is tested with a stand-in model because `ultralytics` is optional. The real BDRAR network and weights were run through the shadow wrapper once by hand (see the models README), not in the automated tests, because the weights are not in this repository.

## Security

The collector and the image server have **no login**, and the firmware sends over plain HTTP. Anyone who finds the address can post data. Put both behind HTTPS and a reverse proxy that requires a token, keep the server address out of public code, and restrict who can reach MongoDB.
