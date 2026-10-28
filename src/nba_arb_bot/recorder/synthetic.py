"""Shared offline synthetic-capture primitives; no transport or credentials."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import re

from .planner import stamp, utc


class PayloadError(ValueError):
    """Safe error codes only: never include source response bodies or credentials."""


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", value):
        raise PayloadError("invalid_identifier")
    return value


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError("missing_timestamp")
    return utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def _seconds(delta):
    return (Decimal(delta.days * 86400 + delta.seconds)
            + Decimal(delta.microseconds) / Decimal(1_000_000))


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PayloadError("duplicate_json_key")
        result[key] = value
    return result


def _check_keys(value):
    """Reject credential-bearing fields before any raw response persistence."""
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(r"[^a-z]", "", key.casefold())
            if any(word in normalized for word in (
                "password", "authorization", "apikey", "token", "cookie", "secret",
                "credential", "endpoint", "url", "headers",
            )):
                raise PayloadError("credential_or_transport_field_not_allowed")
            _check_keys(child)
    elif isinstance(value, list):
        for child in value:
            _check_keys(child)


@dataclass(frozen=True)
class Capture:
    capture_id: str
    request_started_at: datetime
    request_finished_at: datetime
    received_at: datetime

    def times(self):
        _identifier(self.capture_id)
        times = tuple(stamp(t) for t in (
            self.request_started_at, self.request_finished_at, self.received_at))
        if not times[0] <= times[1] <= times[2]:
            raise ValueError("Invalid request/receipt chronology")
        return times
