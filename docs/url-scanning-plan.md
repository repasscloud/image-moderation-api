# URL image scanning

Approved scope: fetch short-lived signed image URLs, run existing engines, discard the downloaded copy, and commit the changes. Source objects remain untouched.

- Add POST /v1/scan/url with JSON {url, engines?}; engines is an optional nonempty list, defaulting to all enabled engines. Preserve upload routes and clarify their optional engine field.
- ALLOWED_IMAGE_HOSTS is a comma-separated exact hostname allowlist; blank permits any public HTTPS host. Restrict HTTPS to port 443, reject URL credentials/fragments and redirects, ignore proxy environment variables, reject every non-public DNS answer and pin the validated IP at connection time while retaining original TLS hostname validation.
- Add URL_DOWNLOAD_TIMEOUT_SECONDS=30. Share scan admission/concurrency and executor capacity, enforce download byte and decoded-image limits, cap JSON requests at 16 KiB, reject compressed transfer bodies and sanitize errors. Never echo/log the signed URL or derive a filename from it.
- Test wire preservation, host configuration, DNS rebinding protection, IPv4/IPv6 exclusions, redirects, download limits/timeouts, error redaction, auth and defaults. Rebuild Docker and exercise real URL download/inference through a public HTTPS image, then commit only this change.
