from marshmallow import Schema, fields


class CharacterSchema(Schema):
    """Schema for Character model serialization/validation."""

    id = fields.Int(dump_only=True)
    name = fields.Str(required=True)
    sex = fields.Str()
    vocation = fields.Str()
    level = fields.Int()
    world = fields.Str()
    residence = fields.Str()
    house = fields.Str()
    guild_membership = fields.Str()
    last_login = fields.DateTime()
    comment = fields.Str()
    account_status = fields.Str()
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)


character_schema = CharacterSchema()
characters_schema = CharacterSchema(many=True)