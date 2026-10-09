from typing import Optional
from agents import SessionABC
from agents.items import TResponseInputItem


class InMemorySession(SessionABC):
    """In-memory conversation history session for OpenAI Agents SDK."""

    def __init__(self, session_id: str = "interview_session"):
        self.session_id = session_id
        self._items: list[TResponseInputItem] = []

    async def get_items(self, limit: Optional[int] = None) -> list[TResponseInputItem]:
        """Retrieve conversation items up to the specified limit."""
        if limit is None:
            return list(self._items)
        return list(self._items[-limit:])

    async def add_items(self, items: list[TResponseInputItem]) -> None:
        """Add new conversation items to history."""
        self._items.extend(items)

    async def pop_item(self) -> Optional[TResponseInputItem]:
        """Remove and return the most recent item."""
        return self._items.pop() if self._items else None

    async def clear_session(self) -> None:
        """Reset the conversation session."""
        self._items.clear()
