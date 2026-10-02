"""Exceptions shared across stages."""


class NeedsReview(Exception):
    """The bot must stop and hand over to a person instead of guessing."""

    def __init__(self, reason: str, details: dict[str, str] | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.details = dict(details or {})

    def __str__(self) -> str:
        if not self.details:
            return self.reason
        listed = ", ".join(f"{key}={value}" for key, value in self.details.items())
        return f"{self.reason}: {listed}"
