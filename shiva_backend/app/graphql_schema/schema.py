import strawberry
from app.graphql_schema.queries import Query
from app.graphql_schema.mutations import Mutation


schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
)
