from dataclasses import dataclass
from uuid import UUID


MAX_COMMENT_DEPTH = 3


@dataclass(frozen=True)
class CommentStructure:
    parent_id: UUID | None
    depth: int
    is_continuation: bool


def build_comment_structure(
    parent,
    thread_id: UUID,
) -> CommentStructure:
    """
    Calculate the parent, depth, and continuation status
    for a new comment.

    parent=None means this is a top-level comment.
    """

    # Top-level comment
    if parent is None:
        return CommentStructure(
            parent_id=None,
            depth=1,
            is_continuation=False,
        )

    # A reply must belong to the same thread.
    if parent.thread_id != thread_id:
        raise ValueError("Parent comment belongs to another thread.")

    # Reject invalid existing parent depths.
    if parent.depth < 1 or parent.depth > MAX_COMMENT_DEPTH:
        raise ValueError("Parent comment has an invalid depth.")

    # Normal reply: depth 1 -> 2, or depth 2 -> 3.
    if parent.depth < MAX_COMMENT_DEPTH:
        return CommentStructure(
            parent_id=parent.id,
            depth=parent.depth + 1,
            is_continuation=False,
        )

    # Replying to a depth-3 comment:
    # attach the new comment to the depth-2 parent.
    if parent.parent_id is None:
        raise ValueError(
            "A depth-3 comment must have a depth-2 parent."
        )

    return CommentStructure(
        parent_id=parent.parent_id,
        depth=MAX_COMMENT_DEPTH,
        is_continuation=True,
    )