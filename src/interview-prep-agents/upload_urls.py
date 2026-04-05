import os
from urllib.parse import urlparse, urlunparse


_LOCAL_UPLOAD_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _get_internal_upload_base_url() -> str:
    configured = os.getenv("UPLOAD_INTERNAL_BASE_URL", "").strip()
    if configured:
        return configured.rstrip("/")

    port = os.getenv("PORT", "8000").strip() or "8000"
    return f"http://host.docker.internal:{port}"


def normalize_attachment_url_for_agent(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return url

    path = parsed.path
    if path.startswith("/api/uploads/"):
        path = path[len("/api"):]

    if not path.startswith("/uploads/"):
        return url

    if parsed.hostname not in _LOCAL_UPLOAD_HOSTS:
        return url

    internal_base = urlparse(_get_internal_upload_base_url())
    return urlunparse(
        (
            internal_base.scheme or "http",
            internal_base.netloc,
            path,
            "",
            parsed.query,
            "",
        )
    )


def rewrite_attachment_urls_for_agent(message: str) -> str:
    rewritten_lines: list[str] = []

    for line in message.splitlines():
        stripped = line.strip()
        if not stripped.lower().startswith("attachment url:"):
            rewritten_lines.append(line)
            continue

        _, _, raw_url = line.partition(":")
        normalized_url = normalize_attachment_url_for_agent(raw_url.strip())
        rewritten_lines.append(f"Attachment URL: {normalized_url}" if normalized_url else line)

    return "\n".join(rewritten_lines)
