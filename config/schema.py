import strawberry
from strawberry.tools import merge_types
from apps.accounts.schema import Query as AccountsQuery
from apps.characters.schema import Query as CharactersQuery

Query = merge_types("Query", (AccountsQuery, CharactersQuery))
schema = strawberry.Schema(query=Query)
