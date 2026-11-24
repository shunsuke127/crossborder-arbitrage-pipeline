"""Deterministic cross-border profit & landed-cost calculation engine.

Design principle:
    Financial math (fees, FX spread, tariffs, shipping, breakeven) is kept
    100% deterministic in pure Python — never delegated to an LLM.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from src.models import ActionLabel, CostConfig, ListingRecord, ProfitAnalysis, WallStatus

# Weight brackets: (max_weight_g, fee_jpy)
SHIPPING_TABLES: Dict[str, Dict[str, List[Tuple[int, int]]]] = {
    "spk": {
        "us": [(100, 1200), (200, 1500), (300, 1800), (500, 2400), (1000, 3800), (2000, 6500)],
        "asia": [(100, 900), (200, 1150), (300, 1400), (500, 1900), (1000, 3000), (2000, 5200)],
        "eu": [(100, 1350), (200, 1700), (300, 2050), (500, 2750), (1000, 4300), (2000, 7400)],
    },
    "epl": {
        "us": [(100, 640), (200, 830), (300, 1020), (500, 1400), (1000, 2350), (2000, 4250)],
        "asia": [(100, 470), (200, 600), (300, 730), (500, 990), (1000, 1640), (2000, 2940)],
        "eu": [(100, 670), (200, 870), (300, 1070), (500, 1470), (1000, 2470), (2000, 4470)],
    },
    "ems": {
        "us": [(500, 3900), (600, 4180), (700, 4460), (1000, 5300), (2000, 8100)],
        "asia": [(500, 1450), (600, 1650), (700, 1850), (1000, 2400), (2000, 3900)],
        "eu": [(500, 4200), (600, 4520), (700, 4840), (1000, 5800), (2000, 9000)],
    },
}


def lookup_shipping_jpy(method: str, zone: str, weight_g: float) -> float:
    """Return international shipping cost in JPY based on method, zone, and weight."""
    method_table = SHIPPING_TABLES.get(method, SHIPPING_TABLES["spk"])
    brackets = method_table.get(zone, method_table["us"])
    for max_w, fee in brackets:
        if weight_g <= max_w:
            return float(fee)
    return float(brackets[-1][1])


def analyze_profit(
    record: ListingRecord,
    fx_rate: float,
    config: CostConfig,
) -> ProfitAnalysis:
    """Compute exact unit economics for a single cross-border listing."""
    effective_fx = fx_rate * (1.0 - config.fx_safety_margin_pct / 100.0)
    gross_usd = record.target_ebay_usd
    gross_jpy = gross_usd * effective_fx

    # Marketplace fees + Japan consumption tax on fees
    fvf_usd = gross_usd * (config.fvf_pct / 100.0) + config.fvf_fixed_usd
    intl_usd = gross_usd * (config.intl_fee_pct / 100.0)
    fee_subtotal = fvf_usd + intl_usd
    ebay_fee_usd = fee_subtotal * (1.0 + config.fee_consumption_tax_pct / 100.0)

    # Payout after FX conversion spread
    net_usd_before_spread = gross_usd - ebay_fee_usd
    fx_spread_usd = net_usd_before_spread * (config.fx_spread_pct / 100.0)
    net_payout_jpy = (net_usd_before_spread - fx_spread_usd) * effective_fx - config.payout_fee_jpy

    # Landed costs
    net_cost_jpy = record.source_cost_jpy * (1.0 - record.coupon_pct / 100.0)
    shipping_jpy = lookup_shipping_jpy(
        record.shipping_method, record.dest_zone, record.weight_g
    )
    packaging_jpy = config.packaging_cost_jpy

    tariff_rate = (
        config.us_tariff_pct if record.dest_zone == "us" else config.other_tariff_pct
    )
    tariff_jpy = gross_jpy * (tariff_rate / 100.0) if config.tariff_enabled else 0.0
    ddp_jpy = (
        config.ddp_handling_fee_jpy
        if (config.tariff_enabled and record.dest_zone == "us")
        else 0.0
    )

    total_cost_jpy = net_cost_jpy + shipping_jpy + packaging_jpy + tariff_jpy + ddp_jpy
    profit_jpy = net_payout_jpy - total_cost_jpy
    profit_margin_pct = (profit_jpy / gross_jpy * 100.0) if gross_jpy > 0 else 0.0
    roi_pct = (profit_jpy / net_cost_jpy * 100.0) if net_cost_jpy > 0 else 0.0
    breakeven_cost_jpy = net_payout_jpy - (
        shipping_jpy + packaging_jpy + tariff_jpy + ddp_jpy
    )

    # $100 customs/handling threshold check
    if gross_usd > config.wall_hard_limit_usd:
        wall_status: WallStatus = "OVER_LIMIT"
    elif gross_usd > config.wall_warning_usd:
        wall_status = "NEAR_LIMIT"
    else:
        wall_status = "OK"

    # Purely quantitative baseline verdict
    ok_margin = profit_margin_pct >= config.target_profit_margin_pct
    ok_profit = profit_jpy >= config.target_profit_jpy
    if record.is_sold or profit_jpy <= 0:
        det_action: ActionLabel = "PASS"
    elif ok_margin and ok_profit:
        det_action = "BUY"
    elif ok_margin or ok_profit:
        det_action = "REVIEW"
    else:
        det_action = "PASS"

    return ProfitAnalysis(
        listing_id=record.listing_id,
        effective_fx=round(effective_fx, 4),
        gross_usd=round(gross_usd, 2),
        gross_jpy=round(gross_jpy, 2),
        ebay_fee_usd=round(ebay_fee_usd, 4),
        fx_spread_usd=round(fx_spread_usd, 4),
        net_payout_jpy=round(net_payout_jpy, 2),
        net_cost_jpy=round(net_cost_jpy, 2),
        shipping_jpy=round(shipping_jpy, 2),
        packaging_jpy=round(packaging_jpy, 2),
        tariff_jpy=round(tariff_jpy, 2),
        total_cost_jpy=round(total_cost_jpy, 2),
        profit_jpy=round(profit_jpy, 2),
        profit_margin_pct=round(profit_margin_pct, 2),
        roi_pct=round(roi_pct, 2),
        breakeven_cost_jpy=round(breakeven_cost_jpy, 2),
        wall_status=wall_status,
        deterministic_action=det_action,
    )
