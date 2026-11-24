"""End-to-end data pipeline orchestrator."""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import List, Tuple

from src.agents import (
    BaseEvaluationAgent,
    DecisionOrchestrator,
    OptionalOllamaCritiqueAgent,
    ProfitabilityAgent,
    RiskComplianceAgent,
)
from src.benchmark import evaluate_benchmark, format_benchmark_markdown
from src.calculator import analyze_profit
from src.fx_client import fetch_usd_jpy_rate
from src.ingestion import load_listings_csv
from src.models import BenchmarkReport, CostConfig, FxQuote, PipelineResult


def run_pipeline(
    input_csv: Path,
    output_dir: Path,
    offline: bool = False,
    fallback_fx: float = 150.0,
    use_local_ollama: bool = False,
    ollama_model: str = "qwen2.5:14b",
    config: CostConfig | None = None,
) -> Tuple[FxQuote, List[PipelineResult], BenchmarkReport]:
    """Execute the full workflow: Ingest -> FX -> Calculate -> Multi-Agent -> Benchmark."""
    cfg = config or CostConfig()
    output_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()

    # Step 1: Ingest & validate CSV
    ingestion = load_listings_csv(input_csv, deduplicate=True)

    # Step 2: Fetch USD/JPY rate (key-free public API with offline fallback)
    fx_quote = fetch_usd_jpy_rate(offline=offline, fallback_rate=fallback_fx)

    # Step 3: Build specialist agent team
    agents: List[BaseEvaluationAgent] = [
        ProfitabilityAgent(),
        RiskComplianceAgent(),
    ]
    if use_local_ollama:
        agents.append(OptionalOllamaCritiqueAgent(model=ollama_model))
    orchestrator = DecisionOrchestrator(agents=agents)

    # Step 4: Deterministic calculation + Multi-agent evaluation
    results: List[PipelineResult] = []
    for record in ingestion.records:
        item_start = time.perf_counter()
        finance = analyze_profit(record, fx_quote.rate, cfg)
        feedbacks, final_action, confidence, summary_reason = orchestrator.decide(
            record, finance, cfg
        )
        latency_ms = (time.perf_counter() - item_start) * 1000.0
        results.append(
            PipelineResult(
                listing=record,
                finance=finance,
                agent_feedbacks=feedbacks,
                final_action=final_action,
                confidence=confidence,
                summary_reason=summary_reason,
                latency_ms=latency_ms,
            )
        )

    total_runtime_ms = (time.perf_counter() - t0) * 1000.0

    # Step 5: Benchmark evaluation
    report = evaluate_benchmark(
        results=results,
        total_rows_read=ingestion.total_rows,
        rejected_records=len(ingestion.rejected_rows),
        duplicates_removed=ingestion.duplicates_removed,
        total_runtime_ms=total_runtime_ms,
    )

    # Step 6: Export artifacts
    _export_results_csv(results, output_dir / "pipeline_results.csv")
    (output_dir / "benchmark_report.json").write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "benchmark_report.md").write_text(
        format_benchmark_markdown(report),
        encoding="utf-8",
    )

    return fx_quote, results, report


def _export_results_csv(results: List[PipelineResult], dest: Path) -> None:
    if not results:
        return
    rows = [r.to_flat_dict() for r in results]
    with dest.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
