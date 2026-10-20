"""A small GitHub GraphQL client: sends one query, retries on hiccups, respects the rate limit."""

import os
import subprocess
import time
from datetime import datetime, timezone

import httpx

GRAPHQL_URL = "https://api.github.com/graphql"


def get_token() -> str:
    """Use $GITHUB_TOKEN if set, otherwise borrow the token the `gh` CLI is logged in with."""
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True)
    return result.stdout.strip()


class GitHubClient:
    def __init__(self, token: str, max_retries: int = 5):
        self.http = httpx.Client(
            headers={"Authorization": f"Bearer {token}"},
            timeout=60.0,
        )
        self.max_retries = max_retries

    def query(self, query: str, variables: dict) -> dict:
        """Run one GraphQL query and return its `data` part.

        GitHub sometimes answers big queries with a 502 or a timeout. Those are
        temporary, so we wait and try again, doubling the wait each time
        (2s, 4s, 8s, ...). Real errors, such as a typo in the query, fail at once.
        """
        for attempt in range(self.max_retries):
            try:
                response = self.http.post(GRAPHQL_URL, json={"query": query, "variables": variables})
            except httpx.TransportError:
                self._wait_before_retry(attempt)
                continue

            if response.status_code in (502, 503, 504):
                self._wait_before_retry(attempt)
                continue
            response.raise_for_status()

            body = response.json()
            if "errors" in body:
                raise RuntimeError(f"GraphQL error: {body['errors']}")

            self._pause_if_rate_limited(body["data"])
            return body["data"]

        raise RuntimeError(f"GitHub did not answer after {self.max_retries} attempts")

    def _wait_before_retry(self, attempt: int) -> None:
        seconds = 2 ** (attempt + 1)
        print(f"  GitHub hiccup, retrying in {seconds}s")
        time.sleep(seconds)

    def _pause_if_rate_limited(self, data: dict) -> None:
        """Every query asks for `rateLimit`. If the hourly budget is nearly spent, sleep until it resets."""
        limit = data.get("rateLimit")
        if limit and limit["remaining"] < 50:
            reset_at = datetime.fromisoformat(limit["resetAt"])
            seconds = max(0, (reset_at - datetime.now(timezone.utc)).total_seconds()) + 5
            print(f"  Rate limit almost used up, sleeping {seconds:.0f}s")
            time.sleep(seconds)
