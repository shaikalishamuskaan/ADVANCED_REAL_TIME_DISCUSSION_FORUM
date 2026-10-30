import re


TAG_PATTERN = re.compile(r"^[a-z0-9_-]{1,30}$")
MAX_TAGS_PER_THREAD = 5


def normalize_tag(tag: str) -> str:
    """
    Remove surrounding whitespace and convert a tag to lowercase.
    """
    return tag.strip().lower()


def validate_tag(tag: str) -> str:
    """
    Normalize a tag and check whether it follows the LLD rules.
    Returns the normalized tag if valid.
    """
    normalized = normalize_tag(tag)

    if not TAG_PATTERN.fullmatch(normalized):
        raise ValueError(
            "Tags must be 1-30 characters and contain only "
            "lowercase letters, numbers, underscores, or hyphens."
        )

    return normalized


def normalize_and_validate_tags(tags: list[str]) -> list[str]:
    """
    Normalize all tags, remove duplicates, and enforce the five-tag limit.
    """
    normalized_tags = []

    for tag in tags:
        validated_tag = validate_tag(tag)

        if validated_tag not in normalized_tags:
            normalized_tags.append(validated_tag)

    if len(normalized_tags) > MAX_TAGS_PER_THREAD:
        raise ValueError("A thread can have at most 5 tags.")

    return normalized_tags