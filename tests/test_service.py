import pytest
from unittest.mock import patch, Mock
from app.services.character_service import CharacterService


class TestCharacterService:

    def test_init(self):
        """Test service initialization."""
        with patch('app.services.character_service.TibiantisScraper') as mock_scraper:
            service = CharacterService()
            assert service.scraper == mock_scraper.return_value

    def test_get_character_data(self, mock_scraper, sample_character_data):
        """Test getting character data from service."""
        # Setup mock
        mock_scraper.get_character_data.return_value = sample_character_data

        # Test the method
        service = CharacterService()
        result = service.get_character_data("TestCharacter")

        # Verify results
        assert result == sample_character_data
        mock_scraper.get_character_data.assert_called_once_with(character_name="TestCharacter")

    def test_get_character_deaths(self, mock_scraper, sample_character_deaths):
        """Test getting character death history from service."""
        # Setup mock
        mock_scraper.get_character_deaths.return_value = sample_character_deaths

        # Test the method
        service = CharacterService()
        result = service.get_character_deaths("TestCharacter")

        # Verify results
        assert result == sample_character_deaths
        mock_scraper.get_character_deaths.assert_called_once_with(character_name="TestCharacter")

    def test_add_character_success(self, mock_scraper, mock_db_session, sample_character_data):
        """Test successfully adding a character to the database."""
        # Setup mocks
        mock_scraper.get_character_data.return_value = sample_character_data
        mock_db_session.query.return_value.filter.return_value.first.return_value = None

        # Test the method
        service = CharacterService()
        result, status_code = service.add_character("TestCharacter")

        # Verify results
        assert status_code == 201
        assert "added successfully" in result["message"]
        mock_db_session.add.assert_called_once()
        mock_db_session.commit.assert_called_once()
        mock_db_session.close.assert_called_once()

    def test_add_character_already_exists(self, mock_scraper, mock_db_session, sample_character_data):
        """Test adding a character that already exists in the database."""
        # Setup mocks
        mock_scraper.get_character_data.return_value = sample_character_data
        mock_db_session.query.return_value.filter.return_value.first.return_value = Mock()

        # Test the method
        service = CharacterService()
        result, status_code = service.add_character("TestCharacter")

        # Verify results
        assert status_code == 200
        assert "already exists" in result["message"]
        mock_db_session.add.assert_not_called()
        mock_db_session.commit.assert_not_called()
        mock_db_session.close.assert_called_once()

    def test_add_character_not_found(self, mock_scraper, mock_db_session):
        """Test adding a character that doesn't exist on the server."""
        # Setup mocks
        mock_scraper.get_character_data.return_value = None

        # Test the method
        service = CharacterService()
        result, status_code = service.add_character("NonExistentCharacter")

        # Verify results
        assert status_code == 404
        assert "does not exist" in result["error"]
        mock_db_session.add.assert_not_called()
        mock_db_session.commit.assert_not_called()

    def test_add_character_exception(self, mock_scraper, mock_db_session, sample_character_data):
        """Test handling exceptions when adding a character."""
        # Setup mocks
        mock_scraper.get_character_data.return_value = sample_character_data
        mock_db_session.query.return_value.filter.return_value.first.return_value = None
        mock_db_session.add.side_effect = Exception("Database error")

        # Test the method
        service = CharacterService()
        result, status_code = service.add_character("TestCharacter")

        # Verify results
        assert status_code == 500
        assert "Database error" in result["error"]
        mock_db_session.rollback.assert_called_once()
        mock_db_session.close.assert_called_once()