"""Shared HTTP plumbing for feed fetchers."""

import httpx

DEFAULT_TIMEOUT_SECONDS = 30.0
USER_AGENT = (
    "Alexander-the-Cracked/0.1 (hackathon discovery agent; "
    "+https://github.com/isayahc/Alexander-the-Cracked)"
)


def http_get_json(url: str) -> object:
    """GET a URL and return the parsed JSON body."""
    response = httpx.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=DEFAULT_TIMEOUT_SECONDS,
        follow_redirects=True,
    )
    response.raise_for_status()
    return response.json()
