import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware


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
