import pytest
from unittest.mock import Mock, patch
from app.main import create_app
from app.db.models.base import Base
from app.db.session import engine, SessionLocal
from app.db.models.character import Character
from app.scraper.tibiantis_scraper import TibiantisScraper
from app.services.character_service import CharacterService
from datetime import datetime

@pytest.fixture
def app():
    """Create and configure a Flask app for testing."""
    app = create_app()
    app.config.update({
        "TESTING": True,
    })
    yield app

@pytest.fixture
def client(app):
    """A test client for the app."""
    return app.test_client()

@pytest.fixture
def mock_scraper():
    """Mock TibiantisScraper for testing."""
    with patch('app.services.character_service.TibiantisScraper') as mock:
        scraper_instance = Mock()
        mock.return_value = scraper_instance
        yield scraper_instance

@pytest.fixture
def mock_db_session():
    """Mock database session for testing."""
    with patch('app.services.character_service.SessionLocal') as mock_session:
        session = Mock()
        mock_session.return_value = session
        yield session

@pytest.fixture
def sample_character_data():
    """Sample character data for testing."""
    return {
        "name": "TestCharacter",
        "sex": "male",
        "vocation": "Knight",
        "level": 100,
        "world": "Tibiantis",
        "residence": "Thais",
        "house": None,
        "guild_membership": None,
        "last_login": datetime(2023, 5, 1, 12, 0, 0),
        "comment": "",
        "account_status": "Premium Account"
    }

@pytest.fixture
def sample_character_deaths():
    """Sample character death data for testing."""
    return [
        {
            "date": datetime(2023, 4, 15, 14, 30, 0),
            "killed_by": "a dragon",
            "killers": ["dragon"]
        },
        {
            "date": datetime(2023, 3, 10, 18, 45, 0),
            "killed_by": "a demon",
            "killers": ["demon"]
        }
    ]