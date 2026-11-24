"""CLI entrypoint for the Cross-Border Arbitrage Multi-Agent Pipeline."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from src.benchmark import format_benchmark_markdown
from src.pipeline import run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Cross-border e-commerce multi-agent data pipeline "
            "(zero personal API keys required)."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/sample_listings.csv"),
        help="Path to input CSV file (default: data/sample_listings.csv)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs"),
        help="Directory for output artifacts (default: outputs/)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Skip live public FX API call and use fallback FX rate.",
    )
    parser.add_argument(
        "--fallback-fx",
        type=float,
        default=150.0,
        help="Fallback USD/JPY rate when offline or API unavailable (default: 150.0).",
    )
    parser.add_argument(
        "--use-ollama",
        action="store_true",
        help="Enable optional local Ollama critique agent (no cloud API key needed).",
    )
    parser.add_argument(
        "--ollama-model",
        type=str,
        default="qwen2.5:14b",
        help="Local Ollama model name (default: qwen2.5:14b).",
    )
    return parser


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
    )
    args = build_parser().parse_args()

    fx_quote, results, report = run_pipeline(
        input_csv=args.input,
        output_dir=args.output,
        offline=args.offline,
        fallback_fx=args.fallback_fx,
        use_local_ollama=args.use_ollama,
        ollama_model=args.ollama_model,
    )

    print(
        f"\nFX Rate: {fx_quote.pair} = {fx_quote.rate:.2f} "
        f"(source: {fx_quote.source})\n"
    )
    print(f"{'ID':<6} {'Action':<7} {'Base':<7} {'Profit(JPY)':>12} {'Margin':>8}  Reason")
    print("-" * 88)
    for r in results:
        print(
            f"{r.listing.listing_id:<6} {r.final_action:<7} "
            f"{r.finance.deterministic_action:<7} {r.finance.profit_jpy:>12,.0f} "
            f"{r.finance.profit_margin_pct:>7.1f}%  {r.summary_reason}"
        )

    print("\n" + format_benchmark_markdown(report))
    print(f"Artifacts written to: {args.output.resolve()}")


if __name__ == "__main__":
    main()
