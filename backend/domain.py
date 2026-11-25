from pathlib import Path

from fastapi import APIRouter
from fleet_api import router as fleet
from readings_api import router as readings
from demand_api import router as demand
from rounds_api import router as rounds
from forecast_job import run_job

router = APIRouter(prefix="/api")
router.include_router(fleet)
router.include_router(readings)
router.include_router(demand)
router.include_router(rounds)


def seed(connection):
    connection.execute(Path(__file__).with_name("demo.sql").read_text())
