"""Initialize the database, creating all tables and seed data."""

import logging
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from packages.db.session import engine, Base, SessionLocal
from packages.db.models import *  # noqa: F401,F403 — ensure all models are imported

logger = logging.getLogger(__name__)


def _seed_default_admin() -> None:
    """Ensure the default-admin user exists in DB (used when REQUIRE_AUTH=false)."""
    db = SessionLocal()
    try:
        existing = db.get(User, "default-admin")  # noqa: F405
        if existing is None:
            admin = User(  # noqa: F405
                id="default-admin",
                username="admin",
                email=None,
                hashed_password="!",
                role=UserRole.ADMIN,  # noqa: F405
                is_active=True,
            )
            db.add(admin)
            db.commit()
            logger.info("Seeded default-admin user.")
    except Exception:
        logger.exception("Could not seed default-admin")
        db.rollback()
    finally:
        db.close()


def init_db() -> None:
    """Create all database tables."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    data_dir = project_root / "data"
    data_dir.mkdir(exist_ok=True)

    logger.info("Creating tables in: %s", engine.url)
    Base.metadata.create_all(bind=engine)
    _seed_default_admin()
    logger.info("Database initialized successfully.")


if __name__ == "__main__":
    init_db()
