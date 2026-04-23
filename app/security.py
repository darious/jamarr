import logging
import os
import re
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

SENSITIVE_KEYS = (
    "authorization",
    "access_token",
    "refresh_token",
    "token",
    "jwt",
    "password",
    "session_key",
    "lastfm_session_key",
    "user_auth_token",
    "client_secret",
    "secret",
    "api_key",
    "qobuz",
    "qobuz_secret",
    "tidal",
    "tidal_secret",
)

_BEARER_RE = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+")
_JWT_RE = re.compile(r"\beyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\b")
_QUERY_SECRET_RE = re.compile(
    r"(?i)([?&](?:"
    + "|".join(re.escape(key) for key in SENSITIVE_KEYS)
    + r")=)[^&\s]+"
)
_ASSIGNMENT_SECRET_RE = re.compile(
    r"(?i)\b("
    + "|".join(re.escape(key) for key in SENSITIVE_KEYS)
    + r")\b\s*[:=]\s*(['\"]?)[^,'\"\s&)}\]]+"
)


def strip_query_string(value: str) -> str:
    """Return a request target without its query string."""
    return value.split("?", 1)[0]


def redact_secrets(value: Any) -> Any:
    """Redact credentials and tokens from values before they enter logs or UI."""
    if not isinstance(value, str):
        return value

    redacted = _BEARER_RE.sub("Bearer [REDACTED]", value)
    redacted = _JWT_RE.sub("[REDACTED_JWT]", redacted)
    redacted = _QUERY_SECRET_RE.sub(r"\1[REDACTED]", redacted)
    redacted = _ASSIGNMENT_SECRET_RE.sub(r"\1=[REDACTED]", redacted)
    return redacted


def sanitize_log_value(value: Any, max_length: int = 200) -> str:
    text = str(redact_secrets(value)).replace("\n", "\\n").replace("\r", "\\r")
    if len(text) > max_length:
        return f"{text[:max_length]}..."
    return text


def safe_request_path(request: Request) -> str:
    return request.url.path


def safe_user_agent(request: Request) -> str:
    return sanitize_log_value(request.headers.get("user-agent", "-"), max_length=160)


def parse_csv_env(name: str) -> list[str]:
    value = os.getenv(name, "")
    return [item.strip() for item in value.split(",") if item.strip()]


def is_production() -> bool:
    return os.getenv("ENV", "development").lower() == "production"


def fastapi_docs_config() -> dict[str, str | None]:
    if is_production():
        return {
            "docs_url": None,
            "redoc_url": None,
            "openapi_url": None,
        }
    return {
        "docs_url": "/docs",
        "redoc_url": "/redoc",
        "openapi_url": "/openapi.json",
    }


def configure_security_middleware(app: FastAPI) -> None:
    trusted_proxy_ips = parse_csv_env("TRUSTED_PROXY_IPS")
    if trusted_proxy_ips:
        app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=trusted_proxy_ips)

    allowed_hosts = parse_csv_env("ALLOWED_HOSTS")
    if allowed_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    allowed_origins = parse_csv_env("ALLOWED_ORIGINS")
    if allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )


def get_client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def log_security_event(
    event: str,
    request: Request | None = None,
    *,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """Write a structured security event without logging secrets."""
    parts = [f"event={sanitize_log_value(event, 80)}"]
    if request is not None:
        parts.extend(
            [
                f"ip={sanitize_log_value(get_client_ip(request), 80)}",
                f"method={request.method}",
                f"path={safe_request_path(request)}",
                f"user_agent={safe_user_agent(request)}",
            ]
        )
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(f"{sanitize_log_value(key, 80)}={sanitize_log_value(value)}")

    logging.getLogger("app.security.audit").log(level, " ".join(parts))
