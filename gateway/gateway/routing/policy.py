"""Routing policy and shadow cost (spec Phase 4 tasks 6-7).

Score >= threshold → the large tier, else the small tier. Both tiers are configured in .env; the router
chooses between them per query and never falls back from one to the other (a failure is an error).
Shadow cost uses list prices from .env; with no price configured the cost is unknown (None), never guessed.
"""

from dataclasses import dataclass
from decimal import Decimal

from gateway.config import Settings, Tier


@dataclass(frozen=True)
class Router:
    threshold: float

    def route(self, score: float) -> Tier:
        return "large" if score >= self.threshold else "small"


@dataclass(frozen=True)
class Price:
    """USD per 1M tokens."""

    input_per_m: Decimal
    output_per_m: Decimal


def price_for(settings: Settings, tier: Tier) -> Price | None:
    """The tier's list price from .env, or None when either half is unset."""
    pin = getattr(settings, f"llm_{tier}_price_input_per_m")
    pout = getattr(settings, f"llm_{tier}_price_output_per_m")
    return Price(pin, pout) if pin is not None and pout is not None else None


def shadow_cost(
    price: Price | None, prompt_tokens: int | None, completion_tokens: int | None
) -> Decimal | None:
    if price is None or prompt_tokens is None or completion_tokens is None:
        return None
    usd = (price.input_per_m * prompt_tokens + price.output_per_m * completion_tokens) / Decimal(1_000_000)
    return usd.quantize(Decimal("0.000001"))
