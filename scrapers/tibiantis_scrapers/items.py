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
