"""Validated provider URL composition; configuration is user-owned."""
from urllib.parse import urlsplit, urlunsplit
import ipaddress
from ai.errors import ProviderError


def validate_url(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or any(ord(c) < 33 for c in value)):
            raise ValueError()
    except ValueError:
        raise ProviderError("Base URL must be HTTP(S), without credentials, query, or fragment.") from None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def is_loopback(value: str) -> bool:
    host = urlsplit(value).hostname or ""
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def endpoint(base: str, route: str) -> str:
    base = validate_url(base)
    parsed = urlsplit(base)
    parts = [p for p in parsed.path.split("/") if p]
    suffix = [p for p in route.split("/") if p]
    overlap = 0
    for count in range(1, min(len(parts), len(suffix)) + 1):
        if parts[-count:] == suffix[:count]:
            overlap = count
    path = "/" + "/".join(parts + suffix[overlap:])
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
