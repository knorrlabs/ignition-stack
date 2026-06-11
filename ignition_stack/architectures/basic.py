"""Basic architecture: one full Ignition gateway + optional SQL DB.

This mirrors Ignition's documented Basic architecture - a single gateway
that does everything - surfaced as a named architecture so the wizard can
offer it alongside the multi-gateway architectures. The only knobs are the
database choice (defaults to Postgres) and the optional reverse-proxy
scaffold.
"""

from __future__ import annotations

from dataclasses import dataclass

from ignition_stack.architectures.base import Architecture, ArchOptions, register
from ignition_stack.config import DatabaseConfig, GatewayConfig, ProjectConfig


@dataclass(frozen=True)
class BasicArchitecture:
    slug: str = "basic"
    summary: str = "One full Ignition 8.3 gateway + Postgres. The default starter stack."

    def build(self, name: str, options: ArchOptions) -> ProjectConfig:
        gateway = GatewayConfig()
        if options.edge_role in {"gateway", "basic"}:
            gateway = gateway.model_copy(update={"ignition_edition": "edge"})

        return ProjectConfig(
            name=name,
            architecture=self.slug,
            gateways=[gateway],
            database=_database(options),
            services=list(options.services),
            reverse_proxy=options.reverse_proxy,
        )


def _database(options: ArchOptions) -> DatabaseConfig | None:
    if options.database_kind is None:
        return None
    return DatabaseConfig(kind=options.database_kind)


# Side-effect: registers this architecture when the module is imported.
architecture: Architecture = register(BasicArchitecture())
