import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))  # lets tests `from fixtures import scenarios`

from fixtures import scenarios  # noqa: E402

from backend.detector.config import DetectorConfig  # noqa: E402
from backend.domain.catalog import Catalog  # noqa: E402
from backend.telemetry.fakes import (FixtureChangeFeed, FixtureLogClient, FixtureProber, FixturePromClient,  # noqa: E402
                                     Scenario, build_query_index)


@pytest.fixture(scope="session")
def catalog():
    return Catalog.load()


@pytest.fixture(scope="session")
def cfg():
    return DetectorConfig.load()


class World:
    """All fake telemetry for one scenario."""

    def __init__(self, data, cfg, catalog):
        self.scenario = Scenario(data)
        self.prom = FixturePromClient(self.scenario, build_query_index(cfg, catalog))
        self.logs = FixtureLogClient(self.scenario)
        self.feed = FixtureChangeFeed(self.scenario)
        self.prober = FixtureProber(self.scenario)


@pytest.fixture()
def world(cfg, catalog):
    def make(name_or_data):
        data = scenarios.ALL[name_or_data]() if isinstance(name_or_data, str) else name_or_data
        return World(data, cfg, catalog)

    return make
