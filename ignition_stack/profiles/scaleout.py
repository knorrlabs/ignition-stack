"""Scaleout profile: frontend + backend Ignition gateways networked together.

Two roles: ``frontend`` (user-facing UI / OPC-UA aggregation) defaults to
the Edge edition because that's the canonical scaleout shape in the field;
``backend`` runs the standard edition with the database connection. Both
gateways join the frontend AND backend networks so the frontend can reach
the DB the backend owns. The network split is on by default - that's the
whole point of the scaleout demo.

The plan's validation calls for "two networked gateways (frontend + backend)
+ a DB; the gateway-network link config is present per the Phase-1 matrix";
the gateway-network link itself is a follow-up resource set the seeding
matrix marks ``file-seedable-config: yes``, so it travels with the
``gateway-resources/`` overlay once that catalog grows. Today the
``services`` list is empty by default; users add brokers/IDPs on top.
"""

from __future__ import annotations

from dataclasses import dataclass

from ignition_stack.config import DatabaseConfig, GatewayConfig, ProjectConfig
from ignition_stack.profiles.base import Profile, ProfileOptions, register


@dataclass(frozen=True)
class ScaleoutProfile:
    slug: str = "scaleout"
    summary: str = "Frontend + backend Ignition gateways via gateway network + Postgres."

    def build(self, name: str, options: ProfileOptions) -> ProjectConfig:
        edge_role = options.edge_role if options.edge_role is not None else "frontend"
        gateways = [
            GatewayConfig(
                name="frontend",
                role="frontend",
                ignition_edition="edge" if edge_role == "frontend" else "standard",
                http_port=9088,
            ),
            GatewayConfig(
                name="backend",
                role="backend",
                ignition_edition="edge" if edge_role == "backend" else "standard",
                http_port=9089,
            ),
        ]

        return ProjectConfig(
            name=name,
            profile=self.slug,
            network_split=True,
            gateways=gateways,
            database=_database(options),
            services=list(options.services),
            reverse_proxy=options.reverse_proxy,
        )


def _database(options: ProfileOptions) -> DatabaseConfig | None:
    if options.database_kind is None:
        return None
    return DatabaseConfig(kind=options.database_kind)


profile: Profile = register(ScaleoutProfile())
