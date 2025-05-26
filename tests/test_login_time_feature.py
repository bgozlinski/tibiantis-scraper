# tests/test_login_time_feature.py
import pytest
import json
from unittest.mock import patch, Mock
from datetime import datetime, timedelta
from app.services.character_service import CharacterService
from app.schemas.character import character_login_time_schema


class TestLoginTimeService:
    """Tests for the login time tracking service methods."""

    def test_get_minutes_since_last_login_success(self, mock_scraper, sample_character_data):
        """Test successful calculation of minutes since last login."""
        # Setup mock with a known last_login time
        mock_scraper.get_character_data.return_value = sample_character_data

        # Mock datetime.now() to return a fixed time for consistent testing
        current_time = sample_character_data["last_login"] + timedelta(minutes=120)

        with patch('app.services.character_service.datetime') as mock_datetime:
            mock_datetime.now.return_value = current_time

            # Test the method
            service = CharacterService()
            result = service.get_minutes_since_last_login("TestCharacter")

            # Verify results
            assert result is not None
            assert result["name"] == "TestCharacter"
            assert result["minutes_since_last_login"] == 120
            assert result["can_login"] is True
            mock_scraper.get_character_data.assert_called_once_with(character_name="TestCharacter")

    def test_get_minutes_since_last_login_less_than_100(self, mock_scraper, sample_character_data):
        """Test when minutes since last login is less than 100."""
        # Setup mock with a known last_login time
        mock_scraper.get_character_data.return_value = sample_character_data

        # Mock datetime.now() to return a fixed time for consistent testing
        current_time = sample_character_data["last_login"] + timedelta(minutes=75)

        with patch('app.services.character_service.datetime') as mock_datetime:
            mock_datetime.now.return_value = current_time

            # Test the method
            service = CharacterService()
            result = service.get_minutes_since_last_login("TestCharacter")

            # Verify results
            assert result is not None
            assert result["minutes_since_last_login"] == 75
            assert result["can_login"] is False

    def test_get_minutes_since_last_login_character_not_found(self, mock_scraper):
        """Test when character is not found."""
        # Setup mock to return None (character not found)
        mock_scraper.get_character_data.return_value = None

        # Test the method
        service = CharacterService()
        result = service.get_minutes_since_last_login("NonExistentCharacter")

        # Verify results
        assert result is None
        mock_scraper.get_character_data.assert_called_once_with(character_name="NonExistentCharacter")

    def test_get_minutes_since_last_login_no_login_data(self, mock_scraper, sample_character_data):
        """Test when character has no last_login data."""
        # Setup mock with character data but no last_login
        character_data = sample_character_data.copy()
        character_data["last_login"] = None
        mock_scraper.get_character_data.return_value = character_data

        # Test the method
        service = CharacterService()
        result = service.get_minutes_since_last_login("TestCharacter")

        # Verify results
        assert result is None
        mock_scraper.get_character_data.assert_called_once_with(character_name="TestCharacter")


class TestLoginTimeSchema:
    """Tests for the login time schema."""

    def test_login_time_schema_serialization(self):
        """Test serialization of login time data."""
        # Sample data
        login_time_data = {
            "name": "TestCharacter",
            "minutes_since_last_login": 120,
            "can_login": True,
            # Extra fields that should be excluded
            "level": 100,
            "vocation": "Knight"
        }

        # Serialize with schema
        result = character_login_time_schema.dump(login_time_data)

        # Verify results
        assert result["name"] == "TestCharacter"
        assert result["minutes_since_last_login"] == 120
        assert result["can_login"] is True
        # Verify extra fields are excluded
        assert "level" not in result
        assert "vocation" not in result

    def test_login_time_schema_missing_fields(self):
        """Test serialization with missing fields."""
        # Sample data with missing fields
        login_time_data = {
            "name": "TestCharacter",
            # minutes_since_last_login and can_login are missing
        }

        # Serialize with schema
        result = character_login_time_schema.dump(login_time_data)

        # Verify results
        assert result["name"] == "TestCharacter"
        assert "minutes_since_last_login" not in result
        assert "can_login" not in result


class TestLoginTimeRoutes:
    """Tests for the login time API endpoint."""

    def test_get_character_login_time_success(self, client):
        """Test successful login time retrieval endpoint."""
        # Sample login time data
        login_time_data = {
            "name": "TestCharacter",
            "minutes_since_last_login": 120,
            "can_login": True
        }

        # Setup mock
        with patch('app.routes.character_routes.character_service.get_minutes_since_last_login') as mock_get:
            mock_get.return_value = login_time_data

            # Test the endpoint
            response = client.get('/api/v1/characters/TestCharacter/login-time')

            # Verify results
            assert response.status_code == 200
            data = json.loads(response.data)
            assert "data" in data
            assert data["data"]["name"] == "TestCharacter"
            assert data["data"]["minutes_since_last_login"] == 120
            assert data["data"]["can_login"] is True
            mock_get.assert_called_once_with("TestCharacter")

    def test_get_character_login_time_not_found(self, client):
        """Test login time retrieval when character not found."""
        # Setup mock
        with patch('app.routes.character_routes.character_service.get_minutes_since_last_login') as mock_get:
            mock_get.return_value = None

            # Test the endpoint
            response = client.get('/api/v1/characters/NonExistentCharacter/login-time')

            # Verify results
            assert response.status_code == 404
            data = json.loads(response.data)
            assert "error" in data
            assert "not found" in data["error"].lower() or "no login data" in data["error"].lower()

    def test_get_character_login_time_exception(self, client):
        """Test login time retrieval when an exception occurs."""
        # Setup mock
        with patch('app.routes.character_routes.character_service.get_minutes_since_last_login') as mock_get:
            mock_get.side_effect = Exception("Test error")

            # Test the endpoint
            response = client.get('/api/v1/characters/TestCharacter/login-time')

            # Verify results
            assert response.status_code == 500
            data = json.loads(response.data)
            assert "error" in data
            assert "Test error" in data["error"]