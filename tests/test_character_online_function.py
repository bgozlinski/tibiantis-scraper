import pytest
from unittest.mock import patch, Mock, call
from app.services.character_service import CharacterService


class TestCharacterServiceOnlineFunctions:

    def test_get_online_characters_list(self, mock_scraper):
        """Test getting online characters list from service."""
        # Setup mock
        mock_scraper.get_online_characters_list.return_value = ["Character1", "Character2", "Character3"]

        # Test the method
        service = CharacterService()
        result = service.get_online_characters_list()

        # Verify results
        assert result == ["Character1", "Character2", "Character3"]
        mock_scraper.get_online_characters_list.assert_called_once()

    def test_get_all_characters_from_db(self, mock_db_session):
        """Test getting all characters from database."""
        # Setup mock
        mock_db_session.query.return_value.all.return_value = [("Character1",), ("Character2",)]

        # Test the method
        service = CharacterService()
        result = service.get_all_characters_from_db()

        # Verify results
        assert result == ["Character1", "Character2"]
        mock_db_session.query.assert_called_once()
        mock_db_session.close.assert_called_once()

    def test_get_all_characters_from_db_exception(self, mock_db_session):
        """Test handling exceptions when getting all characters from database."""
        # Setup mock
        mock_db_session.query.side_effect = Exception("Database error")

        # Test the method
        service = CharacterService()
        with pytest.raises(Exception) as excinfo:
            service.get_all_characters_from_db()

        # Verify results
        assert "Error fetching characters from database" in str(excinfo.value)
        mock_db_session.close.assert_called_once()

    def test_add_new_online_characters_success(self, mock_scraper, mock_db_session):
        """Test successfully adding new online characters to the database."""
        # Setup mocks
        mock_scraper.get_online_characters_list.return_value = ["Character1", "Character2", "Character3"]
        mock_db_session.query.return_value.all.return_value = [("Character2",)]

        # Mock add_character method to return success for Character1 and Character3
        with patch.object(CharacterService, 'add_character') as mock_add_character:
            mock_add_character.side_effect = [
                ({"message": "Character1 added successfully"}, 201),
                ({"message": "Character3 added successfully"}, 201)
            ]

            # Test the method
            service = CharacterService()
            result = service.add_new_online_characters()

        # Verify results
        assert result["total_online"] == 3
        assert result["already_in_db"] == 1
        assert result["new_characters"] == 2
        assert result["added"] == 2
        assert result["failed"] == 0
        assert len(result["failures"]) == 0

        # Verify add_character was called with correct parameters
        assert mock_add_character.call_count == 2
        mock_add_character.assert_has_calls([
            call("Character1"),
            call("Character3")
        ])

    def test_add_new_online_characters_all_exist(self, mock_scraper, mock_db_session):
        """Test when all online characters are already in the database."""
        # Setup mocks
        mock_scraper.get_online_characters_list.return_value = ["Character1", "Character2"]
        mock_db_session.query.return_value.all.return_value = [("Character1",), ("Character2",)]

        # Test the method
        service = CharacterService()
        result = service.add_new_online_characters()

        # Verify results
        assert result["total_online"] == 2
        assert result["already_in_db"] == 2
        assert result["new_characters"] == 0
        assert result["added"] == 0
        assert result["failed"] == 0
        assert len(result["failures"]) == 0

    def test_add_new_online_characters_fetch_fails(self, mock_scraper):
        """Test when fetching online characters fails."""
        # Setup mock
        mock_scraper.get_online_characters_list.return_value = None

        # Test the method
        service = CharacterService()
        with pytest.raises(Exception) as excinfo:
            service.add_new_online_characters()

        # Verify results
        assert "Failed to fetch online characters" in str(excinfo.value)

    def test_add_new_online_characters_add_fails(self, mock_scraper, mock_db_session):
        """Test when adding a character fails."""
        # Setup mocks
        mock_scraper.get_online_characters_list.return_value = ["Character1", "Character2"]
        mock_db_session.query.return_value.all.return_value = []

        # Mock add_character method to return success for Character1 and failure for Character2
        with patch.object(CharacterService, 'add_character') as mock_add_character:
            mock_add_character.side_effect = [
                ({"message": "Character1 added successfully"}, 201),
                ({"error": "Failed to add Character2"}, 500)
            ]

            # Test the method
            service = CharacterService()
            result = service.add_new_online_characters()

        # Verify results
        assert result["total_online"] == 2
        assert result["already_in_db"] == 0
        assert result["new_characters"] == 2
        assert result["added"] == 1
        assert result["failed"] == 1
        assert len(result["failures"]) == 1
        assert result["failures"][0]["name"] == "Character2"
        assert result["failures"][0]["reason"] == "Failed to add Character2"

    def test_add_new_online_characters_add_exception(self, mock_scraper, mock_db_session):
        """Test when adding a character raises an exception."""
        # Setup mocks
        mock_scraper.get_online_characters_list.return_value = ["Character1", "Character2"]
        mock_db_session.query.return_value.all.return_value = []

        # Mock add_character method to return success for Character1 and raise exception for Character2
        with patch.object(CharacterService, 'add_character') as mock_add_character:
            mock_add_character.side_effect = [
                ({"message": "Character1 added successfully"}, 201),
                Exception("Unexpected error")
            ]

            # Test the method
            service = CharacterService()
            result = service.add_new_online_characters()

        # Verify results
        assert result["total_online"] == 2
        assert result["already_in_db"] == 0
        assert result["new_characters"] == 2
        assert result["added"] == 1
        assert result["failed"] == 1
        assert len(result["failures"]) == 1
        assert result["failures"][0]["name"] == "Character2"
        assert result["failures"][0]["reason"] == "Unexpected error"
