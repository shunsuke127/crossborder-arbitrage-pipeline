"""Benchmark & evaluation suite for pipeline latency and agent accuracy."""

from __future__ import annotations

from typing import Dict, List

from src.models import BenchmarkReport, PipelineResult

LABELS = ("BUY", "REVIEW", "PASS")


def _compute_macro_f1(y_true: List[str], y_pred: List[str]) -> float:
    f1_scores: List[float] = []
    for label in LABELS:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == label and p == label)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != label and p == label)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == label and p != label)
        if tp == 0 and fp == 0 and fn == 0:
            continue
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (
            (2 * precision * recall / (precision + recall))
            if (precision + recall) > 0
            else 0.0
        )
        f1_scores.append(f1)
    return round(sum(f1_scores) / len(f1_scores), 4) if f1_scores else 0.0


def evaluate_benchmark(
    results: List[PipelineResult],
    total_rows_read: int,
    rejected_records: int,
    duplicates_removed: int,
    total_runtime_ms: float,
) -> BenchmarkReport:
    """Compute latency, throughput, accuracy, macro-F1, and confusion matrix."""
    n = len(results)
    avg_latency = round(sum(r.latency_ms for r in results) / n, 3) if n > 0 else 0.0
    throughput = (
        round(n / (total_runtime_ms / 1000.0), 2) if total_runtime_ms > 0 else 0.0
    )

    labeled = [r for r in results if r.listing.expected_action in LABELS]
    y_true = [str(r.listing.expected_action) for r in labeled]
    y_det = [r.finance.deterministic_action for r in labeled]
    y_agent = [r.final_action for r in labeled]

    det_acc = (
        round(sum(1 for t, p in zip(y_true, y_det) if t == p) / len(labeled), 4)
        if labeled
        else 0.0
    )
    agent_acc = (
        round(sum(1 for t, p in zip(y_true, y_agent) if t == p) / len(labeled), 4)
        if labeled
        else 0.0
    )
    macro_f1 = _compute_macro_f1(y_true, y_agent)

    matrix: Dict[str, Dict[str, int]] = {
        actual: {pred: 0 for pred in LABELS} for actual in LABELS
    }
    for actual, pred in zip(y_true, y_agent):
        matrix[actual][pred] += 1

    return BenchmarkReport(
        total_rows_read=total_rows_read,
        valid_records=n,
        rejected_records=rejected_records,
        duplicates_removed=duplicates_removed,
        total_runtime_ms=round(total_runtime_ms, 3),
        avg_latency_ms=avg_latency,
        throughput_items_per_sec=throughput,
        labeled_count=len(labeled),
        deterministic_accuracy=det_acc,
        multi_agent_accuracy=agent_acc,
        macro_f1_multi_agent=macro_f1,
        confusion_matrix=matrix,
    )


def format_benchmark_markdown(report: BenchmarkReport) -> str:
    """Render a clean Markdown benchmark report suitable for CI or documentation."""
    lines = [
        "# Pipeline Benchmark Report",
        "",
        "## 1. Ingestion & Throughput",
        f"- **Total Rows Read:** {report.total_rows_read}",
        f"- **Valid Records Processed:** {report.valid_records}",
        f"- **Rejected (Invalid Schema/Values):** {report.rejected_records}",
        f"- **Duplicates Removed:** {report.duplicates_removed}",
        f"- **Total Pipeline Runtime:** {report.total_runtime_ms:.3f} ms",
        f"- **Average Latency / Item:** {report.avg_latency_ms:.3f} ms",
        f"- **Throughput:** {report.throughput_items_per_sec:,.2f} items/sec",
        "",
        "## 2. Evaluation Accuracy (Baseline vs. Multi-Agent)",
        f"- **Labeled Test Cases:** {report.labeled_count}",
        f"- **Deterministic Baseline Accuracy:** {report.deterministic_accuracy * 100:.1f}%",
        f"- **Multi-Agent Pipeline Accuracy:** {report.multi_agent_accuracy * 100:.1f}%",
        f"- **Multi-Agent Macro-F1 Score:** {report.macro_f1_multi_agent:.4f}",
        "",
        "## 3. Confusion Matrix (Actual \\ Predicted)",
        "| Actual \\ Predicted | BUY | REVIEW | PASS |",
        "| :--- | :---: | :---: | :---: |",
    ]
    for actual in LABELS:
        row = report.confusion_matrix[actual]
        lines.append(
            f"| **{actual}** | {row['BUY']} | {row['REVIEW']} | {row['PASS']} |"
        )
    lines.append("")
    return "\n".join(lines)
