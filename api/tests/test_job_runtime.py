import subprocess
import sys
import unittest
from pathlib import Path


class JobRuntimeTest(unittest.TestCase):
    def test_worker_bootstrap_loads_foreign_key_targets_in_a_fresh_process(
        self,
    ) -> None:
        api_root = Path(__file__).resolve().parents[1]
        script = """
from app.database import Base
from app.delivery.models import MessageDelivery
from app.jobs.runtime import prepare_job_runtime

assert "message_deliveries" in Base.metadata.tables
assert "tenants" not in Base.metadata.tables

prepare_job_runtime()

tenant_foreign_key = next(
    iter(MessageDelivery.__table__.c.tenant_id.foreign_keys)
)
assert tenant_foreign_key.column.table.name == "tenants"
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=api_root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(
            result.returncode,
            0,
            result.stderr or result.stdout,
        )


if __name__ == "__main__":
    unittest.main()
