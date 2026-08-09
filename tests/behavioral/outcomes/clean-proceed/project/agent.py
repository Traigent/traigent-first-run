"""Existing project-owned support-intent agent."""


def route_support(message: str) -> str:
    lowered = message.casefold()
    if any(word in lowered for word in ("refund", "charged", "invoice")):
        return "billing"
    if any(word in lowered for word in ("cancel", "close", "terminate")):
        return "cancellation"
    return "technical-support"
