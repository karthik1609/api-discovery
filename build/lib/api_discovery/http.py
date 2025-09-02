from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential_jitter


@dataclass
class AuthConfig:
    username: Optional[str] = None
    password: Optional[str] = None
    bearer_token: Optional[str] = None


class HTTPClient:
    def __init__(
        self,
        base_url: str,
        *,
        verify: bool = True,
        timeout_seconds: float = 30.0,
        user_agent: str = "api-discovery/0.1",
        rate_limit_per_second: float = 5.0,
        auth: Optional[AuthConfig] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = httpx.Timeout(timeout_seconds)
        self.verify = verify
        self.user_agent = user_agent
        self._min_interval = 1.0 / max(rate_limit_per_second, 0.1)
        self._last_request_at = 0.0

        headers: Dict[str, str] = {"User-Agent": self.user_agent}
        auth_obj: Optional[httpx.Auth] = None

        if auth and auth.username and auth.password:
            auth_obj = httpx.BasicAuth(auth.username, auth.password)
        elif auth and auth.bearer_token:
            headers["Authorization"] = f"Bearer {auth.bearer_token}"

        self._client = httpx.Client(
            base_url=self.base_url, headers=headers, timeout=self.timeout, verify=self.verify, auth=auth_obj
        )

    def _respect_rate_limit(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_request_at
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_at = time.monotonic()

    @retry(wait=wait_exponential_jitter(initial=0.25, max=4.0), stop=stop_after_attempt(5))
    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        self._respect_rate_limit()
        response = self._client.request(method, url, **kwargs)
        response.raise_for_status()
        return response

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def head(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("HEAD", url, **kwargs)

    def options(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("OPTIONS", url, **kwargs)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "HTTPClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        self.close()

