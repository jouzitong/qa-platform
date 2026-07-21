import os
from pathlib import Path

TEST_DB = Path(__file__).parent / "test.db"
TEST_DB.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
