import strawberry
from strawberry.tools import merge_types
from apps.accounts.schema import Query as AccountsQuery
from apps.characters.schema import Query as CharactersQuery
from apps.deaths.schema import Query as DeathsQuery

Query = merge_types("Query", (AccountsQuery, CharactersQuery, DeathsQuery))
schema = strawberry.Schema(query=Query)
