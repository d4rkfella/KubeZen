from __future__ import annotations
from typing import (
    Awaitable,
    Callable,
    Dict,
    List,
    Type,
    TypeVar,
    Optional,
    Any,
)
import asyncio
import logging
from collections import defaultdict


# Basic Event Structure
class Event:
    """Base class for all events."""

    def __init__(self, **kwargs: object) -> None:
        self.data: Dict[str, Any] = {}
        for key, value in kwargs.items():
            setattr(self, key, value)
            if key == "data" and isinstance(value, dict):
                self.data = value

    def to_dict(self) -> dict[str, object]:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


E = TypeVar("E", bound=Event)
# Type for an event handler: an async function that takes an event and returns nothing
EventHandler = Callable[[E], Awaitable[None]]


class EventBus:
    """
    An asynchronous event bus for dispatching events to registered handlers.
    """

    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initializes the EventBus.
        :param logger: An optional logger instance.
        """
        self._handlers: Dict[Type[Event], List[EventHandler]] = defaultdict(list)
        self.logger = logger or logging.getLogger(__name__)

    def subscribe(self, event_type: Type[E], handler: EventHandler[E]) -> None:
        """
        Subscribes a handler to a specific event type.
        :param event_type: The class of the event to subscribe to.
        :param handler: The asynchronous function to be called when the event is published.
        """
        self.logger.debug(f"Subscribing handler {handler.__name__} to event {event_type.__name__}")
        self._handlers[event_type].append(handler)

    async def publish(self, event: E) -> None:
        """
        Publishes an event, calling all subscribed handlers for that event type.
        Handlers are called concurrently.
        :param event: The event instance to publish.
        """
        event_type = type(event)

        # Get handlers for the specific event type
        handlers = self._handlers.get(event_type, [])
        if not handlers:
            self.logger.error(
                f"[EVENT_BUS] No handlers registered for event type {event_type.__name__}"
            )
            return

        # Concurrently run all handlers for this event
        tasks = [handler(event) for handler in handlers]
        await asyncio.gather(*tasks)
        self.logger.info(
            f"[EVENT_BUS] Finished processing all handlers for event {event_type.__name__}"
        )
