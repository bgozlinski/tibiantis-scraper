from scrapy import Item, Field


class CharacterItem(Item):
    name = Field()
    sex = Field()
    vocation = Field()
    level = Field()
    world = Field()
    residence = Field()
    house = Field()
    guild_membership = Field()
    last_login = Field()
    account_status = Field()


class DeathItem(Item):
    character_name = Field()
    level_at_death = Field()
    killed_by = Field()
    died_at = Field()
