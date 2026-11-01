import re

# Username: 3–30 characters, letters, numbers, and underscores.
# The final lookahead prevents matching only a prefix of an invalid username.
MENTION_PATTERN = re.compile(
    r"(?<!\S)@([A-Za-z0-9_]{3,30})(?![A-Za-z0-9_-])"
)


def extract_mentions(body: str) -> list[str]:
    # Ignore fenced code blocks.
    body = re.sub(r"```.*?```", " ", body, flags=re.DOTALL)

    # Ignore inline code.
    body = re.sub(r"`[^`]*`", " ", body)

    usernames = []
    seen = set()

    for match in MENTION_PATTERN.finditer(body):
        username = match.group(1)
        normalized = username.lower()

        if normalized in seen:
            continue

        seen.add(normalized)
        usernames.append(username)

        if len(usernames) == 10:
            break

    return usernames