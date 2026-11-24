"""Domain data models with strict typing for the data pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Literal, Optional


ActionLabel = Literal["BUY", "REVIEW", "PASS"]
WallStatus = Literal["OK", "NEAR_LIMIT", "OVER_LIMIT"]


@dataclass(frozen=True)
class ListingRecord:
    """Validated input record loaded from CSV."""

    listing_id: str
    category: str
    title: str
    sku: str
    condition: str
    is_graded: bool
    source_market: str
    source_cost_jpy: float
    coupon_pct: float
    target_ebay_usd: float
    dest_zone: str
    shipping_method: str
    weight_g: float
    is_sold: bool
    expected_action: Optional[str] = None


@dataclass(frozen=True)
class FxQuote:
    """USD/JPY exchange rate snapshot."""

    pair: str
    rate: float
    source: str
    fetched_at_utc: str
    is_fallback: bool = False


@dataclass(frozen=True)
class CostConfig:
    """Deterministic fee, tax, shipping, and target threshold settings."""

    fx_safety_margin_pct: float = 3.0
    fvf_pct: float = 12.35
    fvf_fixed_usd: float = 0.30
    intl_fee_pct: float = 1.35
    fee_consumption_tax_pct: float = 10.0
    fx_spread_pct: float = 2.0
    payout_fee_jpy: float = 0.0
    packaging_cost_jpy: float = 50.0
    tariff_enabled: bool = True
    us_tariff_pct: float = 15.0
    other_tariff_pct: float = 0.0
    ddp_handling_fee_jpy: float = 0.0
    wall_warning_usd: float = 95.0
    wall_hard_limit_usd: float = 100.0
    target_profit_margin_pct: float = 25.0
    target_profit_jpy: float = 2500.0


@dataclass(frozen=True)
class ProfitAnalysis:
    """Deterministic financial calculation output."""

    listing_id: str
    effective_fx: float
    gross_usd: float
    gross_jpy: float
    ebay_fee_usd: float
    fx_spread_usd: float
    net_payout_jpy: float
    net_cost_jpy: float
    shipping_jpy: float
    packaging_jpy: float
    tariff_jpy: float
    total_cost_jpy: float
    profit_jpy: float
    profit_margin_pct: float
    roi_pct: float
    breakeven_cost_jpy: float
    wall_status: WallStatus
    deterministic_action: ActionLabel


@dataclass(frozen=True)
class AgentFeedback:
    """Evaluation output from an individual specialist agent."""

    agent_name: str
    score: float  # 0.0 to 1.0
    flags: List[str] = field(default_factory=list)
    rationale: str = ""


@dataclass(frozen=True)
class PipelineResult:
    """Combined deterministic calculation + multi-agent evaluation result."""

    listing: ListingRecord
    finance: ProfitAnalysis
    agent_feedbacks: List[AgentFeedback]
    final_action: ActionLabel
    confidence: float
    summary_reason: str
    latency_ms: float

    def to_flat_dict(self) -> Dict[str, Any]:
        return {
            "listing_id": self.listing.listing_id,
            "title": self.listing.title,
            "sku": self.listing.sku,
            "source_cost_jpy": round(self.finance.net_cost_jpy, 1),
            "target_ebay_usd": self.finance.gross_usd,
            "profit_jpy": round(self.finance.profit_jpy, 1),
            "profit_margin_pct": round(self.finance.profit_margin_pct, 2),
            "roi_pct": round(self.finance.roi_pct, 2),
            "wall_status": self.finance.wall_status,
            "deterministic_action": self.finance.deterministic_action,
            "final_action": self.final_action,
            "expected_action": self.listing.expected_action or "",
            "confidence": round(self.confidence, 3),
            "flags": "; ".join(
                flag for fb in self.agent_feedbacks for flag in fb.flags
            ),
            "summary_reason": self.summary_reason,
            "latency_ms": round(self.latency_ms, 3),
        }


@dataclass(frozen=True)
class BenchmarkReport:
    """Pipeline performance and accuracy benchmark summary."""

    total_rows_read: int
    valid_records: int
    rejected_records: int
    duplicates_removed: int
    total_runtime_ms: float
    avg_latency_ms: float
    throughput_items_per_sec: float
    labeled_count: int
    deterministic_accuracy: float
    multi_agent_accuracy: float
    macro_f1_multi_agent: float
    confusion_matrix: Dict[str, Dict[str, int]]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
