from __future__ import annotations

from typing import Iterable, Tuple

from ..config import ServiceNowSettings
from ..http import HTTPClient, AuthConfig


def _auth(settings: ServiceNowSettings) -> AuthConfig:
    if settings.username and settings.password:
        return AuthConfig(username=settings.username, password=settings.password)
    if settings.oauth_token:
        return AuthConfig(bearer_token=settings.oauth_token)
    return AuthConfig()


def probe_servicenow_tables(settings: ServiceNowSettings, tables: Iterable[str]) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []
    with HTTPClient(
        base_url=settings.base_url,
        verify=settings.verify_tls,
        timeout_seconds=settings.request_timeout_seconds,
        user_agent=settings.user_agent,
        rate_limit_per_second=settings.rate_limit_per_second,
        auth=_auth(settings),
    ) as client:
        for table in tables:
            try:
                # Prefer HEAD/OPTIONS if supported; many instances accept GET with sysparm_limit=1 safely
                client.get(f"/api/now/table/{table}", params={"sysparm_limit": 1})
                results.append((table, True, "GET ok"))
            except Exception as exc:  # noqa: BLE001
                results.append((table, False, str(exc)))
    return results

