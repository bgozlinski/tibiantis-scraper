import pytest
from unittest.mock import patch, Mock
from app.scraper.tibiantis_scraper import TibiantisScraper
import requests


@pytest.fixture
def sample_online_characters():
    """Sample online characters data for testing."""
    return ["Character1", "Character2", "Character3"]


class TestGetOnlineCharactersList:

    @patch('app.scraper.tibiantis_scraper.requests.Session')
    def test_get_online_characters_list_success(self, mock_session, sample_online_characters):
        """Test successful retrieval of an online characters list."""
        # Setup mock response
        mock_response = Mock()
        mock_session.return_value.get.return_value = mock_response

        # Create HTML content that mimics the Tibiantis website online characters page
        html_content = """
        <html>
            <body>
                <table class="tabi">
                    <tr><th>Header1</th><th>Header2</th></tr>
                    <tr><td>Some info</td><td>More info</td></tr>
                    <tr><td>Character1</td><td>Knight, Level 100</td></tr>
                    <tr><td>Character2</td><td>Paladin, Level 85</td></tr>
                    <tr><td>Character3</td><td>Sorcerer, Level 120</td></tr>
                </table>
            </body>
        </html>
        """
        mock_response.content = html_content.encode('utf-8')

        # Test the method
        scraper = TibiantisScraper()
        result = scraper.get_online_characters_list()

        # Verify results
        assert result is not None
        assert len(result) == 3
        assert result == sample_online_characters

    @patch('app.scraper.tibiantis_scraper.requests.Session')
    def test_get_online_characters_list_empty_table(self, mock_session):
        """Test online characters list retrieval with an empty table."""
        # Setup mock response
        mock_response = Mock()
        mock_session.return_value.get.return_value = mock_response

        # Create HTML content with an empty table
        html_content = """
        <html>
            <body>
                <table class="tabi">
                    <tr><th>Header1</th><th>Header2</th></tr>
                </table>
            </body>
        </html>
        """
        mock_response.content = html_content.encode('utf-8')

        # Test the method
        scraper = TibiantisScraper()
        result = scraper.get_online_characters_list()

        # Verify results
        assert result == []

    @patch('app.scraper.tibiantis_scraper.requests.Session')
    def test_get_online_characters_list_no_table(self, mock_session):
        """Test online characters list retrieval when a table is not found."""
        # Setup mock response
        mock_response = Mock()
        mock_session.return_value.get.return_value = mock_response
        mock_response.content = "<html><body></body></html>".encode('utf-8')

        # Test the method
        scraper = TibiantisScraper()
        result = scraper.get_online_characters_list()

        # Verify results
        assert result is None

    @patch('app.scraper.tibiantis_scraper.requests.Session')
    def test_get_online_characters_list_request_exception(self, mock_session):
        """Test handling of request exceptions."""
        # Setup mock to raise exception
        mock_session.return_value.get.side_effect = requests.RequestException("Connection error")

        # Test the method
        scraper = TibiantisScraper()
        with pytest.raises(Exception) as excinfo:
            scraper.get_online_characters_list()

        # Verify exception message
        assert "Error fetching online characters list" in str(excinfo.value)

    @patch('app.scraper.tibiantis_scraper.requests.Session')
    def test_get_online_characters_list_processing_exception(self, mock_session):
        """Test handling of processing exceptions."""
        # Setup mock response with invalid HTML
        mock_response = Mock()
        mock_session.return_value.get.return_value = mock_response
        mock_response.content = "Invalid HTML".encode('utf-8')

        # Mock BeautifulSoup to raise exception during processing
        with patch('app.scraper.tibiantis_scraper.BeautifulSoup', side_effect=Exception("Processing error")):
            scraper = TibiantisScraper()
            with pytest.raises(Exception) as excinfo:
                scraper.get_online_characters_list()

            # Verify exception message
            assert "Error processing online characters" in str(excinfo.value)