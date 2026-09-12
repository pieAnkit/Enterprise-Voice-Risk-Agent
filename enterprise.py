"""UpGuard cybersecurity API client.

OAuth 2.0 client-credentials flow with tokens cached in Redis
(no stampeding when the voice agent fans out tool calls),
plus graceful mock mode when credentials aren't configured yet.
"""
import time
import uuid

import httpx

from app.config import settings
from app.redis_client import cache_get_json, cache_set_json

TOKEN_CACHE_KEY = "upguard:oauth_token"
RISK_CACHE_KEY = "upguard:risk_profile"


class UpGuardClient:
    def __init__(self):
        self._http = httpx.AsyncClient(base_url=settings.upguard_api_base, timeout=10)

    # ---------- OAuth 2.0 ---------------------------------------------------

    async def _get_token(self) -> str:
        cached = await cache_get_json(TOKEN_CACHE_KEY)
        if cached and cached["expires_at"] > time.time() + 60:
            return cached["access_token"]

        resp = await httpx.AsyncClient().post(
            settings.upguard_token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": settings.upguard_client_id,
                "client_secret": settings.upguard_client_secret,
            },
        )
        resp.raise_for_status()
        body = resp.json()
        await cache_set_json(
            TOKEN_CACHE_KEY,
            {"access_token": body["access_token"],
             "expires_at": time.time() + body.get("expires_in", 3600)},
            ttl=body.get("expires_in", 3600) - 60,
        )
        return body["access_token"]

    async def _headers(self) -> dict:
        if not settings.upguard_client_id:
            return {}  # mock mode
        return {"Authorization": f"Bearer {await self._get_token()}"}

    # ---------- Public surface (what the voice tools call) ------------------

    async def get_risk_profile(self) -> dict:
        """Overall security posture — cached 5 min so repeated voice queries
        don't hammer the vendor API."""
        cached = await cache_get_json(RISK_CACHE_KEY)
        if cached:
            return cached
        profile = await self._get("/risk_profile") if settings.upguard_client_id \
            else self._mock_risk_profile()
        await cache_set_json(RISK_CACHE_KEY, profile, settings.risk_cache_ttl_seconds)
        return profile

    async def get_vulnerabilities(self, min_severity: str = "medium") -> list[dict]:
        """Open vulnerabilities above a severity floor, newest first."""
        if not settings.upguard_client_id:
            return self._mock_vulns()
        data = await self._get("/vulnerabilities", params={"status": "open"})
        rank = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        floor = rank.get(min_severity.lower(), 1)
        vulns = [v for v in data.get("results", []) if rank.get(v["severity"].lower(), 0) >= floor]
        return sorted(vulns, key=lambda v: -rank.get(v["severity"].lower(), 0))[:10]

    # ---------- internals ----------------------------------------------------

    async def _get(self, path: str, params: dict | None = None) -> dict:
        resp = await self._http.get(path, params=params,
                                    headers=await self._headers())
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _mock_risk_profile() -> dict:
        return {"score": 78, "grade": "B",
                "message": "Some third-party vendors need attention, nothing critical.",
                "top_risks": ["vendor_acme: leaked credentials",
                              "vendor_apex: stale TLS configuration"]}

    @staticmethod
    def _mock_vulns() -> list[dict]:
        return [
            {"id": "VUL-1001", "severity": "critical",
             "title": "Leaked credential on vendor_acme GitHub",
             "vendor": "vendor_acme"},
            {"id": "VUL-1002", "severity": "high",
             "title": "TLS 1.0 enabled on vendor_apex portal",
             "vendor": "vendor_apex"},
        ]
