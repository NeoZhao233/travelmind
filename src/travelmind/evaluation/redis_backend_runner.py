from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from travelmind.execution import open_redis_checkpointer
from travelmind.runtime.cache import RedisToolCache, tool_cache_key
from travelmind.runtime.models import ToolResponse


class RedisBackendProbeError(RuntimeError):
    """A sanitized error raised when the optional Redis backend is unavailable."""


def run_redis_backend_probe(redis_url: str) -> dict[str, Any]:
    """Exercise real Redis TTL caching and a write/read/delete checkpoint lifecycle."""

    from redis import Redis

    thread_id = f"travelmind-stage13-{uuid4().hex}"
    cache_key = tool_cache_key("candidate_search", {"query": thread_id})
    client = Redis.from_url(
        redis_url,
        socket_connect_timeout=2,
        socket_timeout=2,
        decode_responses=False,
    )
    checks: dict[str, bool] = {}
    diagnostics: dict[str, Any] = {}
    try:
        checks["redis_ping"] = bool(client.ping())
        cache = RedisToolCache(client)
        response = ToolResponse(
            payload={"evidence_count": 1},
            evidence_ids=["redis-probe-evidence"],
        )
        cache.set(cache_key, response, ttl_seconds=30)
        loaded_cache = cache.get(cache_key)
        ttl = client.ttl(cache_key)
        checks["tool_cache_round_trip"] = loaded_cache == response
        checks["tool_cache_ttl_applied"] = 0 < ttl <= 30
        diagnostics["cache_ttl_seconds"] = ttl

        config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
        checkpoint = {
            "v": 1,
            "ts": datetime.now(UTC).isoformat(),
            "id": str(uuid4()),
            "channel_values": {"probe": "stage13"},
            "channel_versions": {"__start__": 1, "probe": 1},
            "versions_seen": {"__input__": {}},
            "pending_sends": [],
        }
        with open_redis_checkpointer(redis_url, ttl_minutes=5) as saver:
            saved_config = saver.put(config, checkpoint, {"source": "stage13-probe"}, {"probe": 1})
            loaded_checkpoint = saver.get(saved_config)
            checks["checkpoint_round_trip"] = bool(
                loaded_checkpoint
                and loaded_checkpoint.get("channel_values", {}).get("probe") == "stage13"
            )
            saver.delete_thread(thread_id)
            checks["checkpoint_cleanup"] = saver.get(config) is None
    except Exception as exc:
        raise RedisBackendProbeError(
            f"Redis backend probe failed with {type(exc).__name__}; endpoint details are redacted"
        ) from None
    finally:
        try:
            client.delete(cache_key)
            client.close()
        except Exception:
            pass

    return {
        "schema_version": 1,
        "experiment": "stage13-live-redis-backend-probe",
        "configuration": {
            "checkpoint_ttl_minutes": 5,
            "tool_cache_ttl_seconds": 30,
            "endpoint_redacted": True,
        },
        "checks": checks,
        "metrics": {"check_pass_rate": sum(checks.values()) / len(checks)},
        "diagnostics": diagnostics,
        "limitations": [
            "The probe uses one local Redis instance and does not measure cluster failover.",
            "Sequential round trips do not establish concurrent throughput or tail latency.",
            "Redis cache failure remains best-effort while checkpoint failure is fail-closed.",
        ],
    }
