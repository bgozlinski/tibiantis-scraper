from datetime import datetime
from xmlrpc.client import DateTime

import requests
from bs4 import BeautifulSoup
from typing import Dict, Optional, List
from dateutil import parser


class TibiantisScraper():
    def __init__(self):
        self.base_url = "https://tibiantis.online/"
        self.session = requests.Session()
        self.time_zone_info = {
            "CEST": 7200,  # UTC+2
            "CET": 3600  # UTC+1
        }

    def _parse_date(self, raw_date: str) ->Optional[DateTime]:
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
            date_value = None

        return date_value

    def _level_convert_str_to_int(self, level_str: str) -> Optional[int]:
        try:
            level_int = int(level_str)
        except (ValueError, TypeError) as e:
            level_int = None

        return level_int

    def _parse_killer_names(self, killed_by_str: str) -> List[str]:

        killer_name = killed_by_str.split("by")[1].strip()

        killer_name = killer_name.strip()[:-1]

        if killer_name.startswith("a "):
            killer_name = killer_name[2:]
        elif killer_name.startswith("an "):
            killer_name = killer_name[3:]

        if " and " in killer_name:
            killers = killer_name.split(" and ")
            return [killer.strip() for killer in killers]
        else:
            return [killer_name.strip()]

    def get_character_data(self, character_name: str) -> Optional[Dict]:
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
        character_url = f"{self.base_url}?page=character&name={character_name}"
        response = self.session.get(character_url)
        soup = BeautifulSoup(response.content, "html.parser")

        if not soup:
            return None

        try:
            tables = soup.find_all("table", class_="tabi")
            if "Latest Deaths" not in tables[1].text:
                return []

            death_list = []
            rows = tables[1].find_all("tr")[1:]

            for row in rows:
                cols = row.find_all("td")
                time_str = cols[0].text.strip()
                killed_by = cols[1].text.strip()

                try:
                    time = self._parse_date(raw_date=time_str)
                except (ValueError, TypeError):
                    time = None

                killer_name = self._parse_killer_names(killed_by_str=killed_by)

                death_list.append({
                    "time": time,
                    "killed_by": killer_name,
                })

            return death_list

        except requests.RequestException as e:
            raise Exception(f"Error fetching player data: {e}")
