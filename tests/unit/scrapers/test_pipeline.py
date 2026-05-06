"""Unit tests for DjangoPipeline — services mocked, no DB required."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from scrapers.tibiantis_scrapers.items import CharacterItem, DeathItem
from scrapers.tibiantis_scrapers.pipelines import DjangoPipeline


def _make_item(**kwargs: object) -> CharacterItem:
    item = CharacterItem()
    for key, value in kwargs.items():
        item[key] = value
    return item


def _make_death_item(**kwargs: object) -> DeathItem:
    item = DeathItem()
    for key, value in kwargs.items():
        item[key] = value
    return item


@pytest.fixture()
def pipeline() -> DjangoPipeline:
    return DjangoPipeline()


@pytest.fixture()
def spider() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def full_item() -> CharacterItem:
    return _make_item(
        name="Yhral",
        sex="male",
        vocation="Elder Druid",
        level=118,
        world="Tibiantis",
        residence="Edron",
        house="",
        guild_membership="",
        last_login=None,
        account_status="Free Account",
    )


@pytest.fixture()
def full_death_item() -> DeathItem:
    return _make_death_item(
        character_name="Hakin Ace",
        level_at_death=10,
        killed_by="a slime",
        died_at=datetime(2026, 4, 30, 5, 25, 12, tzinfo=ZoneInfo("Europe/Berlin")),
    )


class TestDjangoPipelineProcessItem:
    @pytest.mark.asyncio
    async def test_returns_original_item(
        self, pipeline: DjangoPipeline, spider: MagicMock, full_item: CharacterItem
    ) -> None:
        with patch("apps.characters.services.upsert_character"):
            result = await pipeline.process_item(full_item, spider)

        assert result is full_item

    @pytest.mark.asyncio
    async def test_calls_upsert_with_dict_of_item(
        self, pipeline: DjangoPipeline, spider: MagicMock, full_item: CharacterItem
    ) -> None:
        with patch("apps.characters.services.upsert_character") as mock_upsert:
            await pipeline.process_item(full_item, spider)

        mock_upsert.assert_called_once_with(dict(full_item))

    @pytest.mark.asyncio
    async def test_passes_all_fields_to_upsert(
        self, pipeline: DjangoPipeline, spider: MagicMock, full_item: CharacterItem
    ) -> None:
        with patch("apps.characters.services.upsert_character") as mock_upsert:
            await pipeline.process_item(full_item, spider)

        payload = mock_upsert.call_args[0][0]
        assert payload["name"] == "Yhral"
        assert payload["level"] == 118
        assert payload["vocation"] == "Elder Druid"

    @pytest.mark.asyncio
    async def test_propagates_value_error_when_name_missing(
        self, pipeline: DjangoPipeline, spider: MagicMock
    ) -> None:
        item = _make_item(sex="male", vocation="Knight", level=10)

        with patch("apps.characters.services.upsert_character") as mock_upsert:
            mock_upsert.side_effect = ValueError(
                "CharacterPayload requires non-empty 'name'"
            )
            with pytest.raises(ValueError, match="non-empty 'name'"):
                await pipeline.process_item(item, spider)

    @pytest.mark.asyncio
    async def test_does_not_swallow_upsert_exception(
        self, pipeline: DjangoPipeline, spider: MagicMock, full_item: CharacterItem
    ) -> None:
        with patch("apps.characters.services.upsert_character") as mock_upsert:
            mock_upsert.side_effect = RuntimeError("db unavailable")
            with pytest.raises(RuntimeError, match="db unavailable"):
                await pipeline.process_item(full_item, spider)

    @pytest.mark.asyncio
    async def test_death_item_dispatched_to_save_death_event(
        self,
        pipeline: DjangoPipeline,
        spider: MagicMock,
        full_death_item: DeathItem,
    ) -> None:
        with patch("apps.deaths.services.save_death_event") as mock_save:
            await pipeline.process_item(full_death_item, spider)

        mock_save.assert_called_once_with(dict(full_death_item))

    @pytest.mark.asyncio
    async def test_death_item_does_not_route_through_character_path(
        self,
        pipeline: DjangoPipeline,
        spider: MagicMock,
        full_death_item: DeathItem,
    ) -> None:
        """Regression guard — DeathItem must NOT trigger upsert_character.

        Asserts isinstance dispatch routing: a DeathItem reaches save_death_event
        but never reaches the M1 character path. Catches accidental ``if`` /
        ``elif`` reordering or fall-through bugs.
        """
        with (
            patch("apps.deaths.services.save_death_event"),
            patch("apps.characters.services.upsert_character") as mock_upsert,
        ):
            await pipeline.process_item(full_death_item, spider)

        mock_upsert.assert_not_called()
