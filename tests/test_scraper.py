import pytest
from unittest.mock import patch, Mock
from app.scraper.tibiantis_scraper import TibiantisScraper
from bs4 import BeautifulSoup
from datetime import datetime


class TestTibiantisScraper:

    def test_init(self):
        """Test scraper initialization."""
        scraper = TibiantisScraper()
        assert scraper.base_url == "https://tibiantis.online/"
        assert scraper.time_zone_info == {"CEST": 7200, "CET": 3600}

    def test_parse_date(self):
        """Test date parsing functionality."""
        scraper = TibiantisScraper()

        # Test valid date
        date = scraper._parse_date("May 01 2023, 12:00:00 CEST")
        assert isinstance(date, datetime)
        assert date.year == 2023
        assert date.month == 5
        assert date.day == 1

        # Test invalid date
        invalid_date = scraper._parse_date("Invalid date")
        assert invalid_date is None

    def test_level_convert_str_to_int(self):
        """Test level string to int conversion."""
        scraper = TibiantisScraper()

        # Test valid level
        level = scraper._level_convert_str_to_int("100")
        assert level == 100

        # Test invalid level
        invalid_level = scraper._level_convert_str_to_int("abc")
        assert invalid_level is None

    def test_parse_killer_names(self):
        """Test parsing killer names from death messages."""
        scraper = TibiantisScraper()

        # Test single killer
        killers = scraper._parse_killer_names("Killed by a dragon.")
        assert killers == ["dragon"]

        # Test multiple killers
        killers = scraper._parse_killer_names("Killed by a dragon and a demon.")
        assert killers == ["dragon", "demon"]

    @patch('app.scraper.tibiantis_scraper.requests.Session')
    def test_get_character_data_success(self, mock_session, sample_character_data):
        """Test successful character data retrieval."""
        # Setup mock response
        mock_response = Mock()
        mock_session.return_value.get.return_value = mock_response

        # Create HTML content that mimics the Tibiantis website
        html_content = """
        <html>
            <body>
                <table>
                    <tr class="hover"><td>Name:</td><td>TestCharacter</td></tr>
                    <tr class="hover"><td>Sex:</td><td>male</td></tr>
                    <tr class="hover"><td>Vocation:</td><td>Knight</td></tr>
                    <tr class="hover"><td>Level:</td><td>100</td></tr>
                    <tr class="hover"><td>World:</td><td>Tibiantis</td></tr>
                    <tr class="hover"><td>Residence:</td><td>Thais</td></tr>
                    <tr class="hover"><td>Last login:</td><td>May 01 2023, 12:00:00 CEST</td></tr>
                    <tr class="hover"><td>Account Status:</td><td>Premium Account</td></tr>
                </table>
            </body>
        </html>
        """
        mock_response.content = html_content.encode('utf-8')

        # Test the method
        scraper = TibiantisScraper()
        with patch.object(scraper, '_parse_date', return_value=sample_character_data["last_login"]):
            result = scraper.get_character_data("TestCharacter")

        # Verify results
        assert result is not None
        assert result["name"] == "TestCharacter"
        assert result["vocation"] == "Knight"
        assert result["level"] == 100

    @patch('app.scraper.tibiantis_scraper.requests.Session')
    def test_get_character_data_not_found(self, mock_session):
        """Test character data retrieval when character not found."""
        # Setup mock response
        mock_response = Mock()
        mock_session.return_value.get.return_value = mock_response
        mock_response.content = "<html><body></body></html>".encode('utf-8')

        # Test the method
        scraper = TibiantisScraper()
        result = scraper.get_character_data("NonExistentCharacter")

        # Verify results
        assert result is None

    @patch('app.scraper.tibiantis_scraper.requests.Session')
    def test_get_character_deaths(self, mock_session, sample_character_deaths):
        """Test character death history retrieval."""
        # Setup mock response
        mock_response = Mock()
        mock_session.return_value.get.return_value = mock_response

        # Create HTML content that mimics the Tibiantis website death history
        html_content = """
        <html>
            <body>
                <table>
                    <tr class="hover">
                        <td>Apr 15 2023, 14:30:00 CEST</td>
                        <td>Died at level 95 by a dragon.</td>
                    </tr>
                    <tr class="hover">
                        <td>Mar 10 2023, 18:45:00 CEST</td>
                        <td>Died at level 90 by a demon.</td>
                    </tr>
                </table>
            </body>
        </html>
        """
        mock_response.content = html_content.encode('utf-8')

        # Test the method
        scraper = TibiantisScraper()
        with patch.object(scraper, '_parse_date') as mock_parse_date:
            mock_parse_date.side_effect = [
                sample_character_deaths[0]["date"],
                sample_character_deaths[1]["date"]
            ]
            result = scraper.get_character_deaths("TestCharacter")

        # Verify results
        assert len(result) == 2
        assert result[0]["killed_by"] == "Died at level 95 by a dragon."
        assert result[0]["killers"] == ["dragon"]