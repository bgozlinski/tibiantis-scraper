import strawberry
from apps.accounts.schema import Query

schema = strawberry.Schema(
    query=Query,
)
