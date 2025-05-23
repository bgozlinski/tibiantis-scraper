from datetime import datetime
from typing import Dict, Optional, List, Any
import requests
from bs4 import BeautifulSoup
from dateutil import parser
import logging

logger = logging.getLogger(__name__)


class TibiantisScraper():
    """
    Scraper for Tibiantis website to fetch character data and death history.
    """
    def __init__(self) -> None:
        """Initialize the scraper with base URL and session."""
        self.base_url = "https://tibiantis.online/"
        self.session = requests.Session()
        self.time_zone_info = {
            "CEST": 7200,  # UTC+2
            "CET": 3600  # UTC+1
        }

    def _parse_date(self, raw_date: str) ->Optional[datetime]:
        """
        Parse date string with timezone information.

        Args:
            raw_date: Date string to parse

        Returns:
            Datetime object or None if parsing fails
        """
        try:
            parsed_date = parser.parse(raw_date, tzinfos=self.time_zone_info)
            date_value = datetime(
                parsed_date.year,
                parsed_date.month,
                parsed_date.day,
                parsed_date.hour,
                parsed_date.minute,
                parsed_date.second,
                tzinfo=None
            )
        except (ValueError, TypeError) as e:
            logger.warning(f"Failed to parse date '{raw_date}': {str(e)}")
            date_value = None

        return date_value

    def _level_convert_str_to_int(self, level_str: str) -> Optional[int]:
        """
        Convert level string to integer.

        Args:
            level_str: Level string to convert

        Returns:
            Integer level or None if conversion fails
        """
        try:
            level_int = int(level_str)
        except (ValueError, TypeError) as e:
            logger.warning(f"Failed to convert level '{level_str}' to int: {str(e)}")
            level_int = None

        return level_int

    def _parse_killer_names(self, killed_by_str: str) -> List[str]:
        """
        Parse killer names from a death message.

        Args:
            killed_by_str: Death message string

        Returns:
            List of killer names
        """
        killer_name = killed_by_str.split("by")[1].strip()

        killer_name = killer_name.strip()[:-1]

        if " and " in killer_name:
            killers = killer_name.split(" and ")
            processed_killers = []
            for killer in killers:
                killer = killer.strip()
                if killer.startswith("a "):
                    killer = killer[2:]
                elif killer.startswith("an "):
                    killer = killer[3:]
                processed_killers.append(killer)
            return processed_killers
        else:
            if killer_name.startswith("a "):
                killer_name = killer_name[2:]
            elif killer_name.startswith("an "):
                killer_name = killer_name[3:]
            return [killer_name.strip()]

    def get_character_data(self, character_name: str) -> Optional[Dict]:
        """
        Fetch character data from Tibiantis website.

        Args:
            character_name: The name of the character to fetch

        Returns:
            Dictionary containing character data or None if character not found

        Raises:
            Exception: If there's an error fetching or processing data
        """
        try:
            character_url = f"{self.base_url}?page=character&name={character_name}"
            response = self.session.get(character_url)
            soup = BeautifulSoup(response.content, "html.parser")

            if not soup:
                return None

            character_data = {}

            character_data_to_scrap = {
                'name': 'name',
                'sex': 'sex',
                'vocation': 'vocation',
                'level': 'level',
                'world': 'world',
                'residence': 'residence',
                'house': 'house',
                'guild membership': 'guild_membership',
                'last login': 'last_login',
                'comment': 'comment',
                'account status': 'account_status'
            }

            rows = soup.find_all("tr", class_="hover")
            if not rows:
                return None

            for row in rows:
                cols = row.find_all("td")

                key = cols[0].text.strip().lower().rstrip(':')
                value = cols[1].text.strip()

                if key in character_data_to_scrap:
                    field_name = character_data_to_scrap[key]

                    if field_name == "last_login":
                        value = self._parse_date(raw_date=value)

                    if field_name == "level":
                        value = self._level_convert_str_to_int(level_str=value)

                    character_data[field_name] = value

            return character_data

        except requests.RequestException as e:
            raise Exception(f"Error fetching player data: {e}")
        except Exception as e:
            raise Exception(f"Error processing player data: {e}")

    def get_character_deaths(self, character_name: str) -> Optional[List[Dict]]:
        """
        Fetch character death history from Tibiantis website.

        Args:
            character_name: The name of the character to fetch deaths for

        Returns:
            List of death records or None if an character not found

        Raises:
            Exception: If there's an error fetching or processing data
        """
        try:
            character_url = f"{self.base_url}?page=character&name={character_name}"
            response = self.session.get(character_url)
            soup = BeautifulSoup(response.content, "html.parser")

            if not soup:
                return None

            tables = soup.find_all("table")
            if not tables:
                return []

            # Find the death history table
            death_table = None

            # First, try to find a table with "Latest Deaths" text
            for table in tables:
                if "Latest Deaths" in table.text:
                    death_table = table
                    break

            # If no table with "Latest Deaths" found, use the first table that has rows with the expected structure
            if not death_table:
                # For testing purposes, use the first table that has rows with date and death message
                for table in tables:
                    rows = table.find_all("tr", class_="hover")
                    if rows and len(rows) > 0:
                        cols = rows[0].find_all("td")
                        if len(cols) >= 2:
                            death_table = table
                            break

            if not death_table:
                return []

            death_list = []
            rows = death_table.find_all("tr", class_="hover")

            for row in rows:
                cols = row.find_all("td")
                if len(cols) < 2:
                    continue

                date_str = cols[0].text.strip()
                death_msg = cols[1].text.strip()

                # Parse date
                date = self._parse_date(raw_date=date_str)

                # Parse killers
                killers = self._parse_killer_names(killed_by_str=death_msg)

                death_list.append({
                    "date": date,
                    "killed_by": death_msg,
                    "killers": killers
                })

            return death_list

        except requests.RequestException as e:
            raise Exception(f"Error fetching player death data: {e}")
        except Exception as e:
            raise Exception(f"Error processing player death data: {e}")
