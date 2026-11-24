"""Multi-agent evaluation layer with zero-API-key default & optional local LLM adapter.

Architecture:
    1. ProfitabilityAgent   -> Evaluates margin, absolute profit, and ROI efficiency.
    2. RiskComplianceAgent  -> Evaluates customs ($100 wall), condition dispute risk,
                               counterfeit anomaly signals, and availability (SOLD).
    3. DecisionOrchestrator -> Synthesizes specialist feedback into final BUY/REVIEW/PASS.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

from src.models import (
    ActionLabel,
    AgentFeedback,
    CostConfig,
    ListingRecord,
    ProfitAnalysis,
)

logger = logging.getLogger(__name__)


class BaseEvaluationAgent(ABC):
    """Abstract interface for pluggable specialist agents."""

    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def evaluate(
        self,
        record: ListingRecord,
        finance: ProfitAnalysis,
        config: CostConfig,
    ) -> AgentFeedback:
        raise NotImplementedError


class ProfitabilityAgent(BaseEvaluationAgent):
    """Scores financial attractiveness and capital efficiency."""

    @property
    def name(self) -> str:
        return "ProfitabilityAgent"

    def evaluate(
        self,
        record: ListingRecord,
        finance: ProfitAnalysis,
        config: CostConfig,
    ) -> AgentFeedback:
        flags: List[str] = []

        if finance.profit_jpy <= 0:
            flags.append("NEGATIVE_PROFIT")
            return AgentFeedback(
                agent_name=self.name,
                score=0.0,
                flags=flags,
                rationale=f"Projected loss of JPY {finance.profit_jpy:,.0f}.",
            )

        margin_ratio = min(
            finance.profit_margin_pct / max(config.target_profit_margin_pct, 1.0), 1.5
        )
        profit_ratio = min(
            finance.profit_jpy / max(config.target_profit_jpy, 1.0), 1.5
        )
        score = round(min((margin_ratio * 0.5 + profit_ratio * 0.5) / 1.25, 1.0), 3)

        if finance.profit_margin_pct < config.target_profit_margin_pct:
            flags.append("BELOW_TARGET_MARGIN")
        if finance.profit_jpy < config.target_profit_jpy:
            flags.append("BELOW_TARGET_PROFIT")
        if finance.roi_pct >= 80.0:
            flags.append("HIGH_ROI")

        rationale = (
            f"Profit JPY {finance.profit_jpy:,.0f} "
            f"({finance.profit_margin_pct:.1f}% margin, {finance.roi_pct:.1f}% ROI)."
        )
        return AgentFeedback(
            agent_name=self.name, score=score, flags=flags, rationale=rationale
        )


class RiskComplianceAgent(BaseEvaluationAgent):
    """Detects operational, compliance, condition, and counterfeit anomaly risks."""

    @property
    def name(self) -> str:
        return "RiskComplianceAgent"

    def evaluate(
        self,
        record: ListingRecord,
        finance: ProfitAnalysis,
        config: CostConfig,
    ) -> AgentFeedback:
        flags: List[str] = []
        penalty = 0.0

        if record.is_sold:
            flags.append("ALREADY_SOLD")
            return AgentFeedback(
                agent_name=self.name,
                score=0.0,
                flags=flags,
                rationale="Listing is already marked as SOLD.",
            )

        # Operational friction above $100 customs threshold
        if finance.wall_status == "OVER_LIMIT":
            flags.append("OVER_100_USD_WALL")
            penalty += 0.35
        elif finance.wall_status == "NEAR_LIMIT":
            flags.append("NEAR_100_USD_WALL")
            penalty += 0.10

        # Raw (ungraded) Near Mint cards carry elevated return/dispute risk on eBay
        if (not record.is_graded) and record.condition.lower() == "near mint":
            flags.append("RAW_NEAR_MINT_DISPUTE_RISK")
            penalty += 0.25

        # US-bound listings without SpeedPAK lose eBay shipping protection
        if record.dest_zone == "us" and record.shipping_method != "spk":
            flags.append("NON_SPEEDPAK_US_RISK")
            penalty += 0.25

        # Counterfeit / damaged-item anomaly: source price < 15% of target gross JPY
        if finance.gross_jpy > 0 and (finance.net_cost_jpy / finance.gross_jpy) < 0.15:
            flags.append("SUSPICIOUS_LOW_PRICE_ANOMALY")
            penalty += 0.45

        score = round(max(1.0 - penalty, 0.0), 3)
        rationale = (
            "No major compliance or quality risks detected."
            if not flags
            else f"Detected risk flags: {', '.join(flags)}."
        )
        return AgentFeedback(
            agent_name=self.name, score=score, flags=flags, rationale=rationale
        )


class OptionalOllamaCritiqueAgent(BaseEvaluationAgent):
    """Optional local LLM agent (Ollama) — requires no external API keys.

    If local Ollama is unreachable, gracefully degrades without crashing the pipeline.
    """

    def __init__(
        self,
        endpoint: str = "http://localhost:11434/api/generate",
        model: str = "qwen2.5:14b",
        timeout_sec: float = 10.0,
    ) -> None:
        self.endpoint = endpoint
        self.model = model
        self.timeout_sec = timeout_sec

    @property
    def name(self) -> str:
        return f"LocalLLMAgent({self.model})"

    def evaluate(
        self,
        record: ListingRecord,
        finance: ProfitAnalysis,
        config: CostConfig,
    ) -> AgentFeedback:
        prompt = (
            "You are a cross-border trading card risk reviewer. "
            'Respond ONLY with JSON: {"score": 0.0-1.0, "rationale": "short text"}.\n'
            f"Title: {record.title}, Condition: {record.condition}, Graded: {record.is_graded}, "
            f"Cost JPY: {finance.net_cost_jpy}, eBay USD: {finance.gross_usd}, "
            f"Profit JPY: {finance.profit_jpy}, Wall: {finance.wall_status}."
        )
        payload = json.dumps(
            {"model": self.model, "prompt": prompt, "stream": False}
        ).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                parsed = json.loads(body.get("response", "{}"))
                score = float(parsed.get("score", 0.5))
                rationale = str(parsed.get("rationale", "Local LLM review completed."))
                return AgentFeedback(
                    agent_name=self.name,
                    score=max(0.0, min(1.0, score)),
                    flags=["LOCAL_LLM_VERIFIED"],
                    rationale=rationale,
                )
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
            logger.warning("Local Ollama unreachable (%s); returning neutral score.", exc)
            return AgentFeedback(
                agent_name=self.name,
                score=0.5,
                flags=["LOCAL_LLM_FALLBACK"],
                rationale="Local Ollama server unavailable; fell back to deterministic agents.",
            )


class DecisionOrchestrator:
    """Aggregates specialist agent feedback into a final action with confidence."""

    def __init__(self, agents: Optional[List[BaseEvaluationAgent]] = None) -> None:
        self.agents: List[BaseEvaluationAgent] = agents or [
            ProfitabilityAgent(),
            RiskComplianceAgent(),
        ]

    def decide(
        self,
        record: ListingRecord,
        finance: ProfitAnalysis,
        config: CostConfig,
    ) -> Tuple[List[AgentFeedback], ActionLabel, float, str]:
        feedbacks = [a.evaluate(record, finance, config) for a in self.agents]
        all_flags = {flag for fb in feedbacks for flag in fb.flags}

        # Hard blockers -> immediate PASS
        if "ALREADY_SOLD" in all_flags or "NEGATIVE_PROFIT" in all_flags:
            return (
                feedbacks,
                "PASS",
                0.98,
                "Blocked due to sold status or negative profit.",
            )

        # Risk escalation -> downgrade BUY to REVIEW for human inspection
        review_triggers = {
            "OVER_100_USD_WALL",
            "RAW_NEAR_MINT_DISPUTE_RISK",
            "SUSPICIOUS_LOW_PRICE_ANOMALY",
            "NON_SPEEDPAK_US_RISK",
        }
        triggered_risks = sorted(all_flags.intersection(review_triggers))

        avg_score = sum(fb.score for fb in feedbacks) / max(len(feedbacks), 1)

        if finance.deterministic_action == "PASS":
            return (
                feedbacks,
                "PASS",
                round(max(1.0 - avg_score, 0.70), 3),
                "Profitability below target thresholds.",
            )

        if triggered_risks:
            return (
                feedbacks,
                "REVIEW",
                round(avg_score, 3),
                f"Profitable, but escalated to REVIEW due to: {', '.join(triggered_risks)}.",
            )

        if finance.deterministic_action == "BUY" and avg_score >= 0.75:
            return (
                feedbacks,
                "BUY",
                round(avg_score, 3),
                "Passed quantitative targets and risk compliance checks.",
            )

        return (
            feedbacks,
            "REVIEW",
            round(avg_score, 3),
            "Borderline metrics; manual verification recommended.",
        )
