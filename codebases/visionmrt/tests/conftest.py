import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pipeline as P  # noqa: E402

SITES = ["site_a_open", "site_b_enclosed"]
DATE = "2018-06-09"


@pytest.fixture(scope="session")
def weather():
    return P.load_weather(ROOT / "data" / "weather" / "tempe_2018-06-09.json")


@pytest.fixture(scope="session")
def expected():
    return {s: json.loads((ROOT / "data" / "expected" / f"{s}.json").read_text()) for s in SITES}


@pytest.fixture(scope="session")
def runs(weather, tmp_path_factory):
    """The full one-day pipeline on both example sites, computed once for the whole test session."""
    out = tmp_path_factory.mktemp("runs")
    return {s: P.run_site(ROOT / "data" / "sites" / s, out / s, DATE, weather) for s in SITES}
