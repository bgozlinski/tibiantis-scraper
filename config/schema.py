import strawberry
from strawberry.tools import merge_types
from apps.accounts.schema import Query as AccountsQuery
from apps.characters.schema import Query as CharactersQuery
from apps.deaths.schema import Query as DeathsQuery
from apps.bedmages.schema import Mutation as BedmagesMutation, Query as BedmagesQuery


Query = merge_types(
    "Query", (AccountsQuery, CharactersQuery, DeathsQuery, BedmagesQuery)
)
Mutation = merge_types("Mutation", (BedmagesMutation,))
schema = strawberry.Schema(query=Query, mutation=Mutation)
