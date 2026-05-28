"""MCP + n8n profile: one Ignition gateway, n8n, and a manual MCP drop-in.

The Ignition MCP module is EA-gated (no public download URL while in Early
Access), so this profile scaffolds a ``modules/dropin/`` directory and adds
a POST-SETUP entry pointing at the survey, per the resolved
[q-mcp-delivery](02-design.md#q-mcp-delivery) decision. The user drops the
``.modl`` file into that directory before ``docker compose up``; the
bootstrap copies anything it finds in ``modules/cache`` AND in the drop-in
dir into the gateway volume.

Structurally this is a single-gateway stack plus the n8n service catalog
entry; the ``mcp_dropin`` flag on ``ProjectConfig`` is what triggers the
writer to lay down the drop-in README + a POST-SETUP stub.
"""

from __future__ import annotations

from dataclasses import dataclass

from ignition_stack.config import DatabaseConfig, GatewayConfig, ProjectConfig
from ignition_stack.profiles.base import Profile, ProfileOptions, register


@dataclass(frozen=True)
class McpN8nProfile:
    slug: str = "mcp-n8n"
    summary: str = "One Ignition gateway + n8n + manual MCP (EA) module drop-in."

    def build(self, name: str, options: ProfileOptions) -> ProjectConfig:
        gateway = GatewayConfig()
        if options.edge_role in {"gateway", "standalone"}:
            gateway = gateway.model_copy(update={"ignition_edition": "edge"})

        services = list(options.services)
        if "n8n" not in services:
            services.insert(0, "n8n")

        return ProjectConfig(
            name=name,
            profile=self.slug,
            gateways=[gateway],
            database=_database(options),
            services=services,
            mcp_dropin=True,
            reverse_proxy=options.reverse_proxy,
        )


def _database(options: ProfileOptions) -> DatabaseConfig | None:
    if options.database_kind is None:
        return None
    return DatabaseConfig(kind=options.database_kind)


profile: Profile = register(McpN8nProfile())
