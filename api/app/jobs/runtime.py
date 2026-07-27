from app.database import load_all_models


def prepare_job_runtime() -> None:
    """Load the complete ORM metadata before an RQ job opens a session."""
    load_all_models()
