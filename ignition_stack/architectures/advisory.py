"""Hub-and-spoke RAM advisory.

The hub-and-spoke architecture spins up one hub gateway plus *N* spokes; each
Ignition gateway needs ~1.5 GB to run comfortably. The advisory turns that
math into a proportional friction signal so SEs can see the cost of a
large demo without being silently blocked when they really do want it:

- **green** (≤4 spokes): the common case; proceed without prompting.
- **yellow** (5-8 spokes): show the advisory, ask the user to confirm.
- **red** (≥9 spokes): refuse unless ``--force`` is set, with a message
  explaining the RAM estimate.

The actual *threshold* is the spoke count (per the design's tiered-advisory
decision); the RAM math is folded into the message so the user understands
*why* the tier landed where it did. ``available_bytes`` is injectable so
tests don't depend on the host's free memory.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import psutil

Tier = Literal["green", "yellow", "red"]

# A single Ignition gateway needs ~1.5 GB at idle (anchor heap = 2 GB default
# memory_mb, plus JVM overhead). The advisory estimate stays conservative
# enough that "fits in available RAM" is a real signal, not a worst-case wall.
_BYTES_PER_GATEWAY = 1_500 * 1024 * 1024

# Tier thresholds by spoke count (1 hub + N spokes). Closed intervals; ties go
# to the lower tier (5 spokes is yellow, 9 spokes is red).
_YELLOW_MIN_SPOKES = 5
_RED_MIN_SPOKES = 9


@dataclass(frozen=True)
class Advisory:
    """Outcome of evaluating a hub-and-spoke spoke count.

    ``tier`` drives the CLI flow (green = proceed silently; yellow = confirm;
    red = exit non-zero unless --force). ``message`` is the human-readable
    explanation suitable for stderr or a confirm prompt; it always references
    the totals so the user sees the math.
    """

    tier: Tier
    spoke_count: int
    total_gateways: int
    estimated_gb: float
    available_gb: float
    message: str


def spoke_advisory(spoke_count: int, available_bytes: int | None = None) -> Advisory:
    """Compute the advisory for ``spoke_count`` spoke gateways.

    ``available_bytes`` defaults to ``psutil.virtual_memory().available`` so
    callers don't have to reach for psutil themselves. Tests pass a concrete
    value to make tier+message assertions deterministic.

    Raises ``ValueError`` for negative spoke counts; zero is allowed (a
    hub-only stack, which is just standalone in disguise but the user might
    pick it explicitly during exploration).
    """
    if spoke_count < 0:
        raise ValueError(f"spoke_count must be >= 0, got {spoke_count}")

    if available_bytes is None:
        available_bytes = psutil.virtual_memory().available

    total_gateways = 1 + spoke_count
    estimated_bytes = total_gateways * _BYTES_PER_GATEWAY
    estimated_gb = estimated_bytes / (1024**3)
    available_gb = available_bytes / (1024**3)

    tier = _tier_for(spoke_count)
    message = _message_for(tier, spoke_count, total_gateways, estimated_gb, available_gb)
    return Advisory(
        tier=tier,
        spoke_count=spoke_count,
        total_gateways=total_gateways,
        estimated_gb=estimated_gb,
        available_gb=available_gb,
        message=message,
    )


def _tier_for(spoke_count: int) -> Tier:
    if spoke_count >= _RED_MIN_SPOKES:
        return "red"
    if spoke_count >= _YELLOW_MIN_SPOKES:
        return "yellow"
    return "green"


def _message_for(
    tier: Tier,
    spoke_count: int,
    total_gateways: int,
    estimated_gb: float,
    available_gb: float,
) -> str:
    """Render the advisory message for the given tier.

    Keep these short and concrete: the user sees ``message`` on stderr (red)
    or inside a confirm prompt (yellow); green callers usually skip it
    entirely. Mention spoke count, total gateways, the RAM estimate, and what
    happens next (proceed / confirm / --force).
    """
    estimate = f"{total_gateways} gateways x ~1.5 GB = ~{estimated_gb:.1f} GB needed"
    available = f"{available_gb:.1f} GB available on this host"

    if tier == "green":
        return f"Hub-and-spoke with {spoke_count} spoke(s). {estimate}; {available}. Proceeding."
    if tier == "yellow":
        return (
            f"Hub-and-spoke with {spoke_count} spokes is a heavy demo: "
            f"{estimate}, {available}. "
            f"Each gateway has its own JVM, so memory pressure stacks up fast. "
            f"Confirm to proceed."
        )
    # red
    return (
        f"Hub-and-spoke with {spoke_count} spokes ({total_gateways} gateways total) "
        f"needs ~{estimated_gb:.1f} GB; this host has ~{available_gb:.1f} GB available. "
        f"Stacks this large routinely OOM-kill gateways at startup and are slow to "
        f"demo from. Re-run with --force if you really need this many spokes, or "
        f"drop to <= 8."
    )
