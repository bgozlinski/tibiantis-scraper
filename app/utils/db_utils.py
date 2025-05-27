from contextlib import contextmanager
import logging
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


@contextmanager
def get_db_session():
    """
    Context manager for database sessions.

    Yields:
        SQLAlchemy session object

    Example:
        with get_db_session() as db:
            characters = db.query(Character).all()
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Database session error: {str(e)}")
        raise
    finally:
        session.close()