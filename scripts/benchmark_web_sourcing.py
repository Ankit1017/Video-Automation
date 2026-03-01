from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import argparse
import json
import sys
from typing import Any

from main_app.models import WebSourcingSettings
from main_app.platform.web_sourcing.orchestrator import WebSourcingOrchestrator


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run global web sourcing benchmark checks.")
    parser.add_argument(
        "--fixture",
        default="tests/fixtures/web_queries.json",
        help="JSON file containing benchmark query objects.",
    )
    parser.add_argument(
        "--output",
        default=".cache/web_sourcing_benchmark_latest.json",
        help="Where to store benchmark report JSON.",
    )
    parser.add_argument(
        "--min-pass-rate",
        type=float,
        default=0.70,
        help="Minimum pass rate threshold for enforce mode.",
    )
    parser.add_argument(
        "--enforce",
        action="store_true",
        help="Exit non-zero when pass rate is below threshold.",
    )
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help="Never fail process; report only.",
    )
    parser.add_argument(
        "--max-queries",
        type=int,
        default=3,
        help="Maximum number of fixture queries to run per benchmark invocation.",
    )
    return parser.parse_args()


def _load_fixture(path: str) -> list[dict[str, Any]]:
    fixture_path = Path(path)
    if not fixture_path.exists():
        raise FileNotFoundError(f"Fixture file not found: {fixture_path}")
    raw = json.loads(fixture_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Fixture must be a JSON array of query objects.")
    output: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        topic = " ".join(str(item.get("topic", "")).split()).strip()
        if not topic:
            continue
        output.append(item)
    if not output:
        raise ValueError("Fixture has no valid query entries.")
    return output


def _build_settings(entry: dict[str, Any]) -> WebSourcingSettings:
    defaults = asdict(
        WebSourcingSettings(
            enabled=True,
            force_refresh=True,
            max_search_results=4,
            max_fetch_pages=2,
            timeout_ms=3000,
            query_variant_count=1,
            retry_count=1,
            allow_provider_failover=True,
        )
    )
    overrides_raw = entry.get("web_settings", {})
    overrides = overrides_raw if isinstance(overrides_raw, dict) else {}
    valid_keys = set(WebSourcingSettings.__dataclass_fields__.keys())
    payload = {
        key: value
        for key, value in {**defaults, **overrides}.items()
        if key in valid_keys
    }
    payload["enabled"] = True
    return WebSourcingSettings(**payload)


def _is_hard_provider_exhausted(provider_attempts: list[dict[str, Any]], accepted_count: int) -> bool:
    if accepted_count > 0:
        return False
    if not provider_attempts:
        return False
    exhausting_statuses = {"provider_unavailable", "search_error", "circuit_open"}
    statuses = {
        " ".join(str(item.get("status", "")).split()).strip().lower()
        for item in provider_attempts
        if isinstance(item, dict)
    }
    return bool(statuses) and statuses.issubset(exhausting_statuses)


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    passed = sum(1 for row in rows if bool(row.get("pass", False)))
    pass_rate = (passed / total) if total else 0.0
    avg_accepted = (sum(float(row.get("accepted_count", 0) or 0) for row in rows) / total) if total else 0.0
    avg_quality = (sum(float(row.get("quality_avg", 0.0) or 0.0) for row in rows) / total) if total else 0.0
    fallback_rate = (
        sum(1 for row in rows if bool(row.get("fallback_quality_mode_used", False))) / total
        if total
        else 0.0
    )
    failover_rate = (
        sum(1 for row in rows if bool(row.get("failover_used", False))) / total
        if total
        else 0.0
    )
    zero_result_rate = (
        sum(1 for row in rows if int(row.get("accepted_count", 0) or 0) == 0) / total
        if total
        else 0.0
    )
    return {
        "total_queries": total,
        "passed_queries": passed,
        "pass_rate": round(pass_rate, 4),
        "avg_accepted_count": round(avg_accepted, 4),
        "avg_quality_score": round(avg_quality, 4),
        "fallback_usage_rate": round(fallback_rate, 4),
        "failover_usage_rate": round(failover_rate, 4),
        "zero_result_rate": round(zero_result_rate, 4),
    }


def run_benchmark(*, fixture_path: str, max_queries: int) -> dict[str, Any]:
    entries = _load_fixture(fixture_path)
    limited_entries = entries[: max(1, int(max_queries))]
    orchestrator = WebSourcingOrchestrator()
    rows: list[dict[str, Any]] = []

    for index, entry in enumerate(limited_entries, start=1):
        topic = " ".join(str(entry.get("topic", "")).split()).strip()
        constraints = " ".join(str(entry.get("constraints", "")).split()).strip()
        label = " ".join(str(entry.get("id", f"Q{index}")).split()).strip() or f"Q{index}"
        settings = _build_settings(entry)

        try:
            result = orchestrator.run(topic=topic, constraints=constraints, settings=settings)
            run_diagnostics = result.diagnostics if isinstance(result.diagnostics, dict) else {}
            provider_attempts = run_diagnostics.get("provider_attempts", [])
            provider_attempts_list = provider_attempts if isinstance(provider_attempts, list) else []
            accepted_count = int(run_diagnostics.get("accepted_count", len(result.fetched_pages)) or 0)
            quality_stats = run_diagnostics.get("quality_stats", {})
            quality_avg = float(quality_stats.get("avg", 0.0) or 0.0) if isinstance(quality_stats, dict) else 0.0
            hard_exhausted = _is_hard_provider_exhausted(provider_attempts_list, accepted_count)
            query_pass = accepted_count >= 1 and not hard_exhausted
            row = {
                "id": label,
                "topic": topic,
                "provider_used": result.provider,
                "search_count": int(run_diagnostics.get("search_count", 0) or 0),
                "accepted_count": accepted_count,
                "quality_avg": quality_avg,
                "fallback_quality_mode_used": bool(run_diagnostics.get("fallback_quality_mode_used", False)),
                "failover_used": bool(run_diagnostics.get("failover_used", False)),
                "retry_events": int(run_diagnostics.get("retry_events", 0) or 0),
                "rate_limited_urls": int(run_diagnostics.get("rate_limited_urls", 0) or 0),
                "hard_provider_exhausted": hard_exhausted,
                "warnings_count": len(result.warnings),
                "pass": query_pass,
                "error": "",
            }
        except BaseException as exc:  # pragma: no cover - safeguard for runtime-only issues
            row = {
                "id": label,
                "topic": topic,
                "provider_used": "",
                "search_count": 0,
                "accepted_count": 0,
                "quality_avg": 0.0,
                "fallback_quality_mode_used": False,
                "failover_used": False,
                "retry_events": 0,
                "rate_limited_urls": 0,
                "hard_provider_exhausted": True,
                "warnings_count": 0,
                "pass": False,
                "error": str(exc),
            }
        rows.append(row)

    summary = _summarize(rows)
    return {"summary": summary, "queries": rows}


def main() -> int:
    args = _parse_args()
    report = run_benchmark(fixture_path=args.fixture, max_queries=args.max_queries)
    summary = report.get("summary", {}) if isinstance(report, dict) else {}
    pass_rate = float(summary.get("pass_rate", 0.0) or 0.0)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False))

    if args.warn_only:
        return 0
    if args.enforce and pass_rate < float(args.min_pass_rate):
        print(
            (
                f"Benchmark gate failed: pass_rate={pass_rate:.4f} "
                f"< min_pass_rate={float(args.min_pass_rate):.4f}"
            ),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
