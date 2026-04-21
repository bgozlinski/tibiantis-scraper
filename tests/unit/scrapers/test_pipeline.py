"""Unit tests for DjangoPipeline — upsert_character is mocked, no DB required."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from scrapers.tibiantis_scrapers.items import CharacterItem
from scrapers.tibiantis_scrapers.pipelines import DjangoPipeline


def _make_item(**kwargs: object) -> CharacterItem:
    item = CharacterItem()
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
