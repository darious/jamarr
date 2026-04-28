# Security Policy

## Reporting a Vulnerability

Please do not report security vulnerabilities in public issues.

Report security issues privately to the project maintainer. If the repository has GitHub private vulnerability reporting enabled, use that. Otherwise contact the maintainer by email using the address listed on the GitHub repository owner profile.

Include:

- A description of the issue and impact.
- Steps to reproduce, proof-of-concept details, or affected endpoints.
- Whether credentials, tokens, private data, or signing material may be exposed.
- Any suggested fix, if you already have one.

## Secrets

Never commit `.env` files, passwords, API tokens, private keys, keystores, database dumps, or production logs.

If a secret is committed or exposed:

1. Revoke or rotate it immediately.
2. Remove it from the current tree.
3. Purge it from Git history if the repository has not already been permanently mirrored elsewhere.
4. Treat public Git hosting, CI logs, forks, release artifacts, and local clones as possible copies.

## Supported Versions

Security fixes are handled on the current `main` branch unless a maintainer explicitly says otherwise.

