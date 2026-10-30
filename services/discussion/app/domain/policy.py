from typing import Protocol
from uuid import UUID


class Actor(Protocol):
    user_id: UUID
    role: str
    status: str


class ModifiableResource(Protocol):
    author_id: UUID
    deleted_at: object | None


def can_modify(actor: Actor, resource: ModifiableResource) -> bool:
    """
    Decide whether an actor can edit or delete a thread or comment.
    """

    if actor.status != "active":
        return False

    if resource.deleted_at is not None:
        return False

    if actor.user_id == resource.author_id:
        return True

    return actor.role in ("moderator", "admin")