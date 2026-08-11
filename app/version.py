"""Application version.

The version lives in the git tag, not in a file. Release builds bake it in:
the Docker image sets ``JAMARR_VERSION`` from the tag that triggered the build
(see ``publish_docker.yml``), and the docs workflow exports it before
generating the OpenAPI schema.

Anything else — a dev container, a local ``uv run`` — is not a release and
honestly reports itself as such rather than claiming a version it isn't.
"""

import os

DEV_VERSION = "dev"


def get_version() -> str:
    """The running build's version, or ``dev`` outside a release build."""
    return os.getenv("JAMARR_VERSION", "").strip() or DEV_VERSION


__version__ = get_version()
