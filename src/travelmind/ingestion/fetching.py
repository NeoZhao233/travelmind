from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from urllib.parse import urlsplit

import httpx

FreshnessClass = Literal["static", "dynamic"]
FetchMode = Literal["network_200", "not_modified", "cache_fresh", "cache_stale"]


class SourcePolicyError(ValueError):
    """The requested source violates the configured network policy."""


class SourceUnavailableError(RuntimeError):
    """A transient source failure has no admissible cached fallback."""


class SourceResponseRejectedError(RuntimeError):
    """The source returned a response that must not enter ingestion."""


@dataclass(frozen=True)
class SourceFetchPolicy:
    allowed_hosts: frozenset[str]
    freshness_class: FreshnessClass
    fresh_ttl_seconds: float = 300
    maximum_stale_seconds: float = 86_400
    timeout_seconds: float = 5
    maximum_attempts: int = 3
    backoff_base_seconds: float = 0.25
    backoff_cap_seconds: float = 2
    maximum_response_bytes: int = 2_000_000
    allowed_content_types: frozenset[str] = frozenset(
        {"application/json", "text/html", "text/plain"}
    )

    def __post_init__(self) -> None:
        if not self.allowed_hosts:
            raise ValueError("source policy requires at least one allowed host")
        if self.fresh_ttl_seconds < 0 or self.maximum_stale_seconds < 0:
            raise ValueError("freshness bounds must be non-negative")
        if self.maximum_stale_seconds < self.fresh_ttl_seconds:
            raise ValueError("maximum stale age cannot be shorter than fresh TTL")
        if self.timeout_seconds <= 0 or self.maximum_attempts < 1:
            raise ValueError("timeout and attempt count must be positive")
        if self.backoff_base_seconds < 0 or self.backoff_cap_seconds < 0:
            raise ValueError("backoff bounds must be non-negative")
        if self.maximum_response_bytes < 1:
            raise ValueError("maximum response size must be positive")


@dataclass(frozen=True)
class FetchRequest:
    url: str
    headers: Mapping[str, str]
    timeout_seconds: float


@dataclass(frozen=True)
class FetchResponse:
    status_code: int
    headers: Mapping[str, str]
    content: bytes


@dataclass(frozen=True)
class CachedSource:
    url: str
    content: bytes
    content_type: str
    captured_at: datetime
    validated_at: datetime
    etag: str | None = None
    last_modified: str | None = None


@dataclass(frozen=True)
class FetchDiagnostics:
    mode: FetchMode
    attempts: int
    fallback_used: bool
    cache_age_seconds: float | None
    error_type: str | None


@dataclass(frozen=True)
class FetchResult:
    source: CachedSource
    diagnostics: FetchDiagnostics


class SourceTransport(Protocol):
    def send(self, request: FetchRequest) -> FetchResponse: ...


class HttpxSourceTransport:
    """Synchronous production adapter; redirects stay disabled for policy safety."""

    def send(self, request: FetchRequest) -> FetchResponse:
        with httpx.Client(follow_redirects=False) as client:
            response = client.get(
                request.url,
                headers=dict(request.headers),
                timeout=request.timeout_seconds,
            )
        return FetchResponse(
            status_code=response.status_code,
            headers={key.lower(): value for key, value in response.headers.items()},
            content=response.content,
        )


class ConditionalSourceFetcher:
    def __init__(
        self,
        transport: SourceTransport,
        policy: SourceFetchPolicy,
        *,
        now: Callable[[], datetime],
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._transport = transport
        self._policy = policy
        self._now = now
        self._sleeper = sleeper

    def fetch(self, url: str, cached: CachedSource | None = None) -> FetchResult:
        self._validate_url(url)
        if cached is not None and cached.url != url:
            raise SourcePolicyError("cached source URL does not match request URL")
        headers = {"accept": ", ".join(sorted(self._policy.allowed_content_types))}
        if cached is not None and cached.etag:
            headers["if-none-match"] = cached.etag
        if cached is not None and cached.last_modified:
            headers["if-modified-since"] = cached.last_modified

        last_error_type: str | None = None
        for attempt in range(1, self._policy.maximum_attempts + 1):
            try:
                response = self._transport.send(
                    FetchRequest(
                        url=url,
                        headers=headers,
                        timeout_seconds=self._policy.timeout_seconds,
                    )
                )
            except (TimeoutError, ConnectionError, httpx.TransportError) as exc:
                last_error_type = type(exc).__name__
                if attempt < self._policy.maximum_attempts:
                    self._sleeper(self._backoff(attempt, None))
                    continue
                return self._fallback_or_raise(cached, attempt, last_error_type)

            normalized_headers = {key.lower(): value for key, value in response.headers.items()}
            if response.status_code == 200:
                return self._accept_200(url, response, normalized_headers, attempt)
            if response.status_code == 304:
                if cached is None:
                    raise SourceResponseRejectedError(
                        "source returned 304 without a cached representation"
                    )
                validated = CachedSource(
                    url=cached.url,
                    content=cached.content,
                    content_type=cached.content_type,
                    captured_at=cached.captured_at,
                    validated_at=self._now(),
                    etag=normalized_headers.get("etag", cached.etag),
                    last_modified=normalized_headers.get("last-modified", cached.last_modified),
                )
                return FetchResult(
                    source=validated,
                    diagnostics=FetchDiagnostics(
                        mode="not_modified",
                        attempts=attempt,
                        fallback_used=False,
                        cache_age_seconds=0,
                        error_type=None,
                    ),
                )
            if response.status_code == 429 or 500 <= response.status_code <= 599:
                last_error_type = f"HTTP_{response.status_code}"
                if attempt < self._policy.maximum_attempts:
                    self._sleeper(self._backoff(attempt, normalized_headers.get("retry-after")))
                    continue
                return self._fallback_or_raise(cached, attempt, last_error_type)
            raise SourceResponseRejectedError(
                f"source response rejected with status {response.status_code}"
            )
        raise AssertionError("bounded fetch loop exited unexpectedly")

    def _accept_200(
        self,
        url: str,
        response: FetchResponse,
        headers: Mapping[str, str],
        attempt: int,
    ) -> FetchResult:
        if len(response.content) > self._policy.maximum_response_bytes:
            raise SourceResponseRejectedError("source response exceeded size limit")
        content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type not in self._policy.allowed_content_types:
            raise SourceResponseRejectedError("source content type is not allowed")
        observed_at = self._now()
        source = CachedSource(
            url=url,
            content=response.content,
            content_type=content_type,
            captured_at=observed_at,
            validated_at=observed_at,
            etag=headers.get("etag"),
            last_modified=headers.get("last-modified"),
        )
        return FetchResult(
            source=source,
            diagnostics=FetchDiagnostics(
                mode="network_200",
                attempts=attempt,
                fallback_used=False,
                cache_age_seconds=None,
                error_type=None,
            ),
        )

    def _fallback_or_raise(
        self,
        cached: CachedSource | None,
        attempts: int,
        error_type: str,
    ) -> FetchResult:
        if cached is not None:
            age = max(0.0, (self._now() - cached.validated_at).total_seconds())
            fresh = age <= self._policy.fresh_ttl_seconds
            stale_static = (
                self._policy.freshness_class == "static"
                and age <= self._policy.maximum_stale_seconds
            )
            if fresh or stale_static:
                return FetchResult(
                    source=cached,
                    diagnostics=FetchDiagnostics(
                        mode="cache_fresh" if fresh else "cache_stale",
                        attempts=attempts,
                        fallback_used=True,
                        cache_age_seconds=age,
                        error_type=error_type,
                    ),
                )
        raise SourceUnavailableError(
            "source unavailable after bounded attempts; no admissible cache"
        )

    def _backoff(self, attempt: int, retry_after: str | None) -> float:
        exponential = self._policy.backoff_base_seconds * (2 ** (attempt - 1))
        delay = min(exponential, self._policy.backoff_cap_seconds)
        if retry_after is not None:
            try:
                delay = min(float(retry_after), self._policy.backoff_cap_seconds)
            except ValueError:
                pass
        return max(0.0, delay)

    def _validate_url(self, url: str) -> None:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        allowed = {item.lower() for item in self._policy.allowed_hosts}
        try:
            port = parsed.port
        except ValueError as exc:
            raise SourcePolicyError("source URL has an invalid port") from exc
        if (
            parsed.scheme != "https"
            or not host
            or host not in allowed
            or parsed.username is not None
            or parsed.password is not None
            or port not in (None, 443)
        ):
            raise SourcePolicyError("source URL violates HTTPS/host policy")
