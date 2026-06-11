"""System architectures: pre-canned shapes that turn intent into config.

The slugs mirror Ignition's documented system architectures (Basic / Scale Out
/ Hub and Spoke). Importing this package registers every built-in architecture
by side-effect so ``get_architecture("scale-out")`` works without explicit
module imports.
"""

from ignition_stack.architectures import basic, hub_and_spoke, scale_out  # noqa: F401
from ignition_stack.architectures.advisory import Advisory, spoke_advisory
from ignition_stack.architectures.base import (
    Architecture,
    ArchOptions,
    apply_iiot,
    build_architecture,
    can_host_redundant_role,
    get_architecture,
    list_architectures,
    mark_redundant,
)
from ignition_stack.architectures.hub_and_spoke import ArchitectureError

__all__ = [
    "Advisory",
    "ArchOptions",
    "Architecture",
    "ArchitectureError",
    "apply_iiot",
    "build_architecture",
    "can_host_redundant_role",
    "get_architecture",
    "list_architectures",
    "mark_redundant",
    "spoke_advisory",
]
