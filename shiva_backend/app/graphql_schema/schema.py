import strawberry
from app.graphql_schema.queries import Query
from app.graphql_schema.mutations import Mutation
from app.graphql_schema.subscriptions import Subscription


schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    subscription=Subscription,
)
