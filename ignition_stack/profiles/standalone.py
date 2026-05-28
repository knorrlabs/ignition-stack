"""Standalone profile: one full Ignition gateway + optional SQL DB.

This is the Phase-2 walking skeleton's shape, surfaced as a named profile
so the wizard can offer it alongside the multi-gateway profiles. The only
knobs are the database choice (defaults to Postgres) and the optional
reverse-proxy scaffold.
"""

from __future__ import annotations

from dataclasses import dataclass

from ignition_stack.config import DatabaseConfig, GatewayConfig, ProjectConfig
from ignition_stack.profiles.base import Profile, ProfileOptions, register


@dataclass(frozen=True)
class StandaloneProfile:
    slug: str = "standalone"
    summary: str = "One full Ignition 8.3 gateway + Postgres. The default starter stack."

    def build(self, name: str, options: ProfileOptions) -> ProjectConfig:
        gateway = GatewayConfig()
        if options.edge_role in {"gateway", "standalone"}:
            gateway = gateway.model_copy(update={"ignition_edition": "edge"})

        return ProjectConfig(
            name=name,
            profile=self.slug,
            gateways=[gateway],
            database=_database(options),
            services=list(options.services),
            reverse_proxy=options.reverse_proxy,
        )


def _database(options: ProfileOptions) -> DatabaseConfig | None:
    if options.database_kind is None:
        return None
    return DatabaseConfig(kind=options.database_kind)


# Side-effect: registers this profile when the module is imported.
profile: Profile = register(StandaloneProfile())
