from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def load_all_models() -> None:
    """Import model modules so Alembic can discover every table."""
    from app.attachments import models as _attachments  # noqa: F401
    from app.channels import models as _channels  # noqa: F401
    from app.common import audit_models as _audit  # noqa: F401
    from app.contacts import models as _contacts  # noqa: F401
    from app.conversations import models as _conversations  # noqa: F401
    from app.messages import models as _messages  # noqa: F401
    from app.providers import models as _provider_events  # noqa: F401
    from app.quick_replies import models as _quick_replies  # noqa: F401
    from app.sync import models as _sync_runs  # noqa: F401
    from app.tenants import models as _tenants  # noqa: F401
    from app.users import models as _users  # noqa: F401
