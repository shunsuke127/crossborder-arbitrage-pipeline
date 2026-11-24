"""Unit and integration tests for the multi-agent data pipeline."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.agents import DecisionOrchestrator
from src.calculator import analyze_profit, lookup_shipping_jpy
from src.ingestion import load_listings_csv
from src.models import CostConfig, ListingRecord
from src.pipeline import run_pipeline


class TestCrossBorderPipeline(unittest.TestCase):
    def setUp(self) -> None:
        self.config = CostConfig()
        self.sample_csv = Path("data/sample_listings.csv")

    def test_shipping_lookup(self) -> None:
        self.assertEqual(lookup_shipping_jpy("spk", "us", 50), 1200.0)
        self.assertEqual(lookup_shipping_jpy("spk", "us", 150), 1500.0)
        self.assertEqual(lookup_shipping_jpy("spk", "us", 5000), 6500.0)

    def test_ingestion_validates_and_deduplicates(self) -> None:
        summary = load_listings_csv(self.sample_csv, deduplicate=True)
        # 12 rows in sample CSV: 1 invalid negative price, 1 duplicate -> 10 valid
        self.assertEqual(summary.total_rows, 12)
        self.assertEqual(len(summary.rejected_rows), 1)
        self.assertEqual(summary.duplicates_removed, 1)
        self.assertEqual(len(summary.records), 10)

    def test_raw_near_mint_escalated_to_review(self) -> None:
        record = ListingRecord(
            listing_id="T1",
            category="poke",
            title="Test Card SAR",
            sku="201/165",
            condition="Near Mint",
            is_graded=False,
            source_market="flea_market",
            source_cost_jpy=2000.0,
            coupon_pct=0.0,
            target_ebay_usd=70.0,
            dest_zone="us",
            shipping_method="spk",
            weight_g=50.0,
            is_sold=False,
        )
        finance = analyze_profit(record, fx_rate=150.0, config=self.config)
        self.assertEqual(finance.deterministic_action, "BUY")

        orchestrator = DecisionOrchestrator()
        _, final_action, _, reason = orchestrator.decide(record, finance, self.config)
        self.assertEqual(final_action, "REVIEW")
        self.assertIn("RAW_NEAR_MINT_DISPUTE_RISK", reason)

    def test_over_100_usd_wall_detection(self) -> None:
        record = ListingRecord(
            listing_id="T2",
            category="poke",
            title="High Value Card",
            sku="095/069",
            condition="Excellent",
            is_graded=False,
            source_market="auction",
            source_cost_jpy=7000.0,
            coupon_pct=0.0,
            target_ebay_usd=145.0,
            dest_zone="us",
            shipping_method="spk",
            weight_g=60.0,
            is_sold=False,
        )
        finance = analyze_profit(record, fx_rate=150.0, config=self.config)
        self.assertEqual(finance.wall_status, "OVER_LIMIT")

    def test_end_to_end_offline_pipeline_and_benchmark(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            fx, results, report = run_pipeline(
                input_csv=self.sample_csv,
                output_dir=out_dir,
                offline=True,
                fallback_fx=150.0,
            )
            self.assertTrue(fx.is_fallback)
            self.assertEqual(len(results), 10)
            self.assertGreater(report.multi_agent_accuracy, report.deterministic_accuracy)
            self.assertEqual(report.multi_agent_accuracy, 1.0)
            self.assertTrue((out_dir / "pipeline_results.csv").exists())
            self.assertTrue((out_dir / "benchmark_report.json").exists())
            self.assertTrue((out_dir / "benchmark_report.md").exists())


if __name__ == "__main__":
    unittest.main()
