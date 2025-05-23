import pytest
import json
from unittest.mock import patch
from flask import Flask


class TestCharacterRoutes:

    def test_get_character_success(self, client, mock_scraper, sample_character_data):
        """Test successful character data retrieval endpoint."""
        # Setup mock
        with patch('app.routes.character_routes.character_service.get_character_data') as mock_get:
            mock_get.return_value = sample_character_data

            # Test the endpoint
            response = client.get('/api/v1/characters/TestCharacter')

            # Verify results
            assert response.status_code == 200
            data = json.loads(response.data)
            assert "data" in data
            assert data["data"]["name"] == "TestCharacter"
            mock_get.assert_called_once_with("TestCharacter")

    def test_get_character_not_found(self, client):
        """Test character data retrieval when character not found."""
        # Setup mock
        with patch('app.routes.character_routes.character_service.get_character_data') as mock_get:
            mock_get.return_value = None

            # Test the endpoint
            response = client.get('/api/v1/characters/NonExistentCharacter')

            # Verify results
            assert response.status_code == 404
            data = json.loads(response.data)
            assert "error" in data

    def test_get_character_exception(self, client):
        """Test character data retrieval when an exception occurs."""
        # Setup mock
        with patch('app.routes.character_routes.character_service.get_character_data') as mock_get:
            mock_get.side_effect = Exception("Test error")

            # Test the endpoint
            response = client.get('/api/v1/characters/TestCharacter')

            # Verify results
            assert response.status_code == 500
            data = json.loads(response.data)
            assert "error" in data
            assert "Test error" in data["error"]

    def test_get_character_deaths_success(self, client, sample_character_deaths):
        """Test successful character death history retrieval endpoint."""
        # Setup mock
        with patch('app.routes.character_routes.character_service.get_character_deaths') as mock_get:
            mock_get.return_value = sample_character_deaths

            # Test the endpoint
            response = client.get('/api/v1/characters/TestCharacter/deaths')

            # Verify results
            assert response.status_code == 200
            data = json.loads(response.data)
            assert "data" in data
            assert len(data["data"]) == 2
            assert data["data"][0]["killed_by"] == "a dragon"
            mock_get.assert_called_once_with("TestCharacter")

    def test_get_character_deaths_not_found(self, client):
        """Test character death history retrieval when character not found."""
        # Setup mock
        with patch('app.routes.character_routes.character_service.get_character_deaths') as mock_get:
            mock_get.return_value = None

            # Test the endpoint
            response = client.get('/api/v1/characters/NonExistentCharacter/deaths')

            # Verify results
            assert response.status_code == 404
            data = json.loads(response.data)
            assert "error" in data

    def test_add_character_success(self, client):
        """Test successfully adding a character."""
        # Setup mock
        with patch('app.routes.character_routes.character_service.add_character') as mock_add:
            mock_add.return_value = ({"message": "Character TestCharacter added successfully"}, 201)

            # Test the endpoint
            response = client.post('/api/v1/characters/add/TestCharacter',
                                   json={"name": "TestCharacter"})

            # Verify results
            assert response.status_code == 201
            data = json.loads(response.data)
            assert "message" in data
            assert "added successfully" in data["message"]
            mock_add.assert_called_once_with("TestCharacter")

    def test_add_character_missing_name(self, client):
        """Test adding a character with missing name."""
        # Test the endpoint
        response = client.post('/api/v1/characters/add/TestCharacter', json={})

        # Verify results
        assert response.status_code == 400
        data = json.loads(response.data)
        assert "error" in data
        assert "Name is required" in data["error"]

    def test_add_character_not_found(self, client):
        """Test adding a character that doesn't exist on the server."""
        # Setup mock
        with patch('app.routes.character_routes.character_service.add_character') as mock_add:
            mock_add.return_value = ({"error": "Character NonExistentCharacter does not exist"}, 404)

            # Test the endpoint
            response = client.post('/api/v1/characters/add/NonExistentCharacter',
                                   json={"name": "NonExistentCharacter"})

            # Verify results
            assert response.status_code == 404
            data = json.loads(response.data)
            assert "error" in data
            assert "does not exist" in data["error"]