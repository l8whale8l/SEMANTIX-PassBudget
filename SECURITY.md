# Security Policy

## Reporting a vulnerability

Do not publish credentials, private mission data, or exploit details in a public issue. Use GitHub's private vulnerability reporting or contact the repository maintainers through a private channel.

## Repository rules

- Never commit `.env` files, private keys, tokens, passwords, server addresses, database dumps, user uploads, logs, or non-public mission documents.
- Keep `.env.example` limited to fake local-development values.
- Treat imported source documents and scenario exports as untrusted input.
- Store file content outside the database when appropriate; persist only validated metadata, opaque locators, and content hashes.
- Rotate a credential immediately if it appears in Git history. Deleting the latest file is not sufficient.

## Deployment rules

- Run the API and migration processes with separate least-privilege database roles.
- Expose PostgreSQL only to the application network, not directly to the public internet.
- Inject production secrets through the host or secret manager.
- Validate upload type and size, source locators, timestamps, coordinates, numeric ranges, and canonical input schemas.
- Do not log canonical snapshots or request bodies that may contain non-public inputs.

## Supported versions

The project is pre-release. A supported-version policy will be added with the first tagged release.

