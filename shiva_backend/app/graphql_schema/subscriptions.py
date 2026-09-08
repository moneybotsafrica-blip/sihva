import asyncio
import strawberry
from typing import AsyncGenerator
from datetime import datetime

from app.graphql_schema.types import Ticket
from app.graphql_schema.queries import ticket_to_graphql


# Simple in-memory subscription manager
# In production, this would use Redis or a proper pub/sub system
class SubscriptionManager:
    def __init__(self):
        self.subscribers: dict[str, list[asyncio.Queue]] = {}

    async def subscribe(self, ticket_id: str) -> asyncio.Queue:
        """Subscribe to updates for a specific ticket."""
        if ticket_id not in self.subscribers:
            self.subscribers[ticket_id] = []
        
        queue = asyncio.Queue()
        self.subscribers[ticket_id].append(queue)
        return queue

    async def publish(self, ticket_id: str, ticket: Ticket):
        """Publish an update to all subscribers of a ticket."""
        if ticket_id in self.subscribers:
            for queue in self.subscribers[ticket_id]:
                await queue.put(ticket)

    async def unsubscribe(self, ticket_id: str, queue: asyncio.Queue):
        """Unsubscribe from ticket updates."""
        if ticket_id in self.subscribers:
            self.subscribers[ticket_id].remove(queue)
            if not self.subscribers[ticket_id]:
                del self.subscribers[ticket_id]


# Global subscription manager
subscription_manager = SubscriptionManager()


async def ticket_updated_generator(ticket_id: str) -> AsyncGenerator[Ticket, None]:
    """
    Generator for ticket updates subscription.
    Yields updated tickets whenever they change.
    """
    queue = await subscription_manager.subscribe(ticket_id)
    
    try:
        while True:
            # Wait for updates
            ticket = await queue.get()
            yield ticket
    except asyncio.CancelledError:
        # Clean up on cancellation
        await subscription_manager.unsubscribe(ticket_id, queue)
        raise


@strawberry.type
class Subscription:
    @strawberry.subscription
    async def ticket_updated(self, ticket_id: str) -> AsyncGenerator[Ticket, None]:
        """
        Subscription: Receive real-time updates when a ticket changes.
        Staff frontend can use this to live-update ticket views without polling.
        """
        async for ticket in ticket_updated_generator(ticket_id):
            yield ticket


# Helper function to publish updates (call this when tickets change)
async def publish_ticket_update(ticket_id: str, ticket):
    """Publish a ticket update to all subscribers."""
    graphql_ticket = ticket_to_graphql(ticket)
    await subscription_manager.publish(ticket_id, graphql_ticket)
