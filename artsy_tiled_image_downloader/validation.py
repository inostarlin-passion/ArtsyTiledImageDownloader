from __future__ import annotations

from collections.abc import Collection
from urllib.parse import SplitResult, urlsplit


def parse_http_url(value: str, *, field: str) -> SplitResult:
    """Parse and validate an absolute HTTP(S) URL without credentials/fragments."""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")

    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field} must not be empty")

    try:
        parsed = urlsplit(cleaned)
        # Accessing port performs validation that urlsplit itself defers.
        _ = parsed.port
    except ValueError as exc:
        raise ValueError(f"{field} is not a valid URL") from exc

    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{field} must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{field} must not contain credentials")
    if parsed.fragment:
        raise ValueError(f"{field} must not contain a URL fragment")
    return parsed


def validate_http_url(
    value: str,
    *,
    field: str,
    allowed_hosts: Collection[str] | None = None,
    allow_subdomains: bool = False,
) -> str:
    parsed = parse_http_url(value, field=field)
    hostname = parsed.hostname.lower() if parsed.hostname else ""

    if allowed_hosts:
        normalized_hosts = {host.lower().rstrip(".") for host in allowed_hosts}
        hostname = hostname.rstrip(".")
        exact_match = hostname in normalized_hosts
        subdomain_match = allow_subdomains and any(
            hostname.endswith(f".{host}") for host in normalized_hosts
        )
        if not exact_match and not subdomain_match:
            expected = ", ".join(sorted(normalized_hosts))
            suffix = " or a subdomain" if allow_subdomains else ""
            raise ValueError(f"{field} host must be {expected}{suffix}")

    return value.strip()


def is_http_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        validate_http_url(value, field="URL")
    except ValueError:
        return False
    return True
