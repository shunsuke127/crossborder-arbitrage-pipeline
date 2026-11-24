"""CSV ingestion, schema validation, and deduplication."""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Set, Tuple

from src.models import ListingRecord

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = {
    "listing_id",
    "category",
    "title",
    "sku",
    "condition",
    "is_graded",
    "source_market",
    "source_cost_jpy",
    "coupon_pct",
    "target_ebay_usd",
    "dest_zone",
    "shipping_method",
    "weight_g",
    "is_sold",
}


@dataclass(frozen=True)
class IngestionSummary:
    records: List[ListingRecord]
    total_rows: int
    rejected_rows: List[Tuple[int, str]]
    duplicates_removed: int


def _parse_bool(raw: str) -> bool:
    return raw.strip().lower() in {"true", "1", "yes", "y"}


def load_listings_csv(
    csv_path: Path, deduplicate: bool = True
) -> IngestionSummary:
    """Load, validate, and deduplicate listing records from a sample CSV file."""
    if not csv_path.exists():
        raise FileNotFoundError(f"Input CSV not found: {csv_path}")

    records: List[ListingRecord] = []
    rejected: List[Tuple[int, str]] = []
    seen_keys: Set[Tuple[str, float, float]] = set()
    duplicates_removed = 0
    total_rows = 0

    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSV file has no header row.")

        missing_cols = REQUIRED_COLUMNS - set(reader.fieldnames)
        if missing_cols:
            raise ValueError(f"Missing required CSV columns: {sorted(missing_cols)}")

        for row_num, row in enumerate(reader, start=2):
            total_rows += 1
            try:
                cost = float(row["source_cost_jpy"])
                coupon = float(row["coupon_pct"])
                ebay_usd = float(row["target_ebay_usd"])
                weight = float(row["weight_g"])

                if cost <= 0:
                    raise ValueError(f"source_cost_jpy must be > 0 (got {cost})")
                if not (0.0 <= coupon <= 50.0):
                    raise ValueError(f"coupon_pct out of bounds [0, 50] (got {coupon})")
                if ebay_usd <= 0:
                    raise ValueError(f"target_ebay_usd must be > 0 (got {ebay_usd})")
                if weight <= 0:
                    raise ValueError(f"weight_g must be > 0 (got {weight})")

                sku = row["sku"].strip()
                title = row["title"].strip()
                if not title:
                    raise ValueError("title cannot be empty")

                dedup_key = (sku or title, cost, ebay_usd)
                if deduplicate and dedup_key in seen_keys:
                    duplicates_removed += 1
                    logger.info("Row %d skipped as duplicate: %s", row_num, dedup_key)
                    continue
                seen_keys.add(dedup_key)

                expected = (row.get("expected_action") or "").strip().upper() or None
                record = ListingRecord(
                    listing_id=row["listing_id"].strip(),
                    category=row["category"].strip().lower(),
                    title=title,
                    sku=sku,
                    condition=row["condition"].strip(),
                    is_graded=_parse_bool(row["is_graded"]),
                    source_market=row["source_market"].strip().lower(),
                    source_cost_jpy=cost,
                    coupon_pct=coupon,
                    target_ebay_usd=ebay_usd,
                    dest_zone=row["dest_zone"].strip().lower(),
                    shipping_method=row["shipping_method"].strip().lower(),
                    weight_g=weight,
                    is_sold=_parse_bool(row["is_sold"]),
                    expected_action=expected,
                )
                records.append(record)
            except (ValueError, KeyError) as exc:
                rejected.append((row_num, str(exc)))
                logger.warning("Row %d rejected: %s", row_num, exc)

    return IngestionSummary(
        records=records,
        total_rows=total_rows,
        rejected_rows=rejected,
        duplicates_removed=duplicates_removed,
    )
