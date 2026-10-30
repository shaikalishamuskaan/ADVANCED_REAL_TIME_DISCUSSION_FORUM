def validate_thread_input(title: str, description: str) -> None:
    if not title or not title.strip():
        raise ValueError("Thread title cannot be empty.")

    if len(title) > 200:
        raise ValueError("Thread title must be at most 200 characters.")

    if len(description) > 10000:
        raise ValueError("Thread description must be at most 10000 characters.")


def validate_comment_input(body: str) -> None:
    if not body or not body.strip():
        raise ValueError("Comment body cannot be empty.")

    if len(body) > 5000:
        raise ValueError("Comment body must be at most 5000 characters.")