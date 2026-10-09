import os
from pathlib import Path
import psycopg
import pytest

@pytest.fixture(scope="session",autouse=True)
def m3d_schema():
    url=os.getenv("DATABASE_URL")
    if url:
        with psycopg.connect(url) as conn:
            conn.execute(Path(__file__).resolve().parents[1].joinpath("schema/005_multimodal_worker.sql").read_text())
