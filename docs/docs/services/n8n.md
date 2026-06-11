---
title: n8n
description: n8n workflow automation engine, pairs with the Ignition MCP module.
---

# n8n

n8n is a workflow automation engine. It is the catalog's user-facing service, so when the network split is on it lands on the `frontend` network rather than the `backend`. It pairs with the Ignition MCP module: add the n8n service and set `mcp_dropin` in a declarative config to scaffold the MCP module drop-in alongside it.

| | |
| --- | --- |
| Image | `n8nio/n8n:2.23.0` (override with `N8N_IMAGE` in `.env`) |
| Catalog kind | `automation` |
| Provides | `automation` |
| Requires | nothing |
| Network when split is on | `frontend` |

## How it reaches a stack

n8n is added as a service in a declarative config or through the composer. Pair it with `mcp_dropin: true` to scaffold the Early-Access Ignition MCP module drop-in, bridging n8n and the gateway. (A guided wizard path for adding n8n + MCP returns in a later release.)

## Preset ports

- `N8N_PORT=5678`: host port for the n8n editor UI.

## Post-setup

None for n8n itself. Setting `mcp_dropin` adds a post-setup step for the Early-Access MCP module drop-in.
