"""pytest 公共夹具。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from medshift import Scheduler, load_config  # noqa: E402
from medshift.models import Assignment  # noqa: E402

EXAMPLE_DIR = ROOT / "examples" / "radiology"
EXAMPLE_CSV = EXAMPLE_DIR / "assignments" / "2026-W42.csv"


@pytest.fixture(scope="session")
def project_root() -> Path:
    return ROOT


@pytest.fixture(scope="session")
def example_dir() -> Path:
    return EXAMPLE_DIR


@pytest.fixture(scope="session")
def example_csv() -> Path:
    return EXAMPLE_CSV


@pytest.fixture(scope="session")
def config():
    return load_config(EXAMPLE_DIR)


@pytest.fixture(scope="session")
def scheduler(config) -> Scheduler:
    return Scheduler(config)


@pytest.fixture(scope="session")
def assignments() -> list[Assignment]:
    return Scheduler(load_config(EXAMPLE_DIR)).load_assignments(EXAMPLE_CSV)
