# Ignition 8.3 Seedability Matrix

This matrix records which Ignition 8.3 connection types you can provision from the filesystem and environment, versus which still require manual entry in the gateway UI. Every downstream phase of `ignition-stack` reads this contract to decide what its wizard can promise and what it has to defer to `POST-SETUP.md`.

The matrix has two verdict columns because the *config* and *secret* parts of a connection often split: the config (URL, port, username) is usually file-seedable, but the secret (password, API key) may need a separate mechanism. Recording them separately lets the service catalog seed the config part while the post-setup generator covers the secret part.

> **Status:** provisional. The investigation is in progress on branch `dynamic-ignition-stack-cli-phase-1`. Rows with verdicts in `( )` are awaiting verification on a live 8.3.6 gateway; rows without parentheses are confirmed.

## Investigation target

- Image: `inductiveautomation/ignition:8.3.6`
- Resources tree: `data/config/resources/{core,local,external,<mode>}` (mode picked by `-Dignition.config.mode=<mode>` JVM arg).
- Reference: `inductive-automation/template-ignition-project` (`master` branch). The template runs a bootstrap container that populates `/data` with `commissioning.json`, a deterministic gateway-network UUID, and mounts `services/ignition/config/resources/core` and `services/ignition/config/resources/<mode>` read-only into the gateway data dir.

## Module install verdict (q-module-install)

Three options were considered for installing third-party `.modl` modules into a stock `inductiveautomation/ignition:8.3.6` image:

- (a) runtime volume-mount of `.modl` into `user-lib/modules/`
- (b) thin derived `Dockerfile` that `COPY`s the `.modl` into `/usr/local/bin/ignition/user-lib/modules/`
- (c) bootstrap-container copy of the `.modl` into the gateway data volume before the gateway process starts

**Result:** *pending verification.*

**Evidence:** *pending; will reference `scripts/seeding-poc/screenshots/module-install/`.*

**Env var:** the platform-environment-variables docs list `GATEWAY_MODULES_ENABLED` as a *comma-delimited set of built-in and third party fully-qualified module identifiers*. The venture context expects this to take a fully-qualified in-container *path*. These two descriptions are different and the experiment must settle which form the variable actually accepts (or whether two separate variables are involved).

## Matrix

Verdict legend: `yes` = file-seeding works without UI touch; `partial` = some aspects work, some don't (note the split in the fallback column); `no` = manual UI entry required.

| connection-type | file-seedable-config | file-seedable-secret | path-template / manual fallback |
| --- | --- | --- | --- |
| `db-connection` | yes | (partial) | Config: `resources/<mode>/ignition/database-connection/<name>/{config.json,resource.json}`. Secret: referenced from config via `{"providerName":"internal-secret-provider","secretName":"..."}`; the secret value itself lives in `resources/<mode>/ignition/secret-provider/internal-secret-provider/config.json` as a JWE-encrypted blob. Plaintext acceptance on first boot is pending verification (experiment B). |
| `jdbc-driver` | yes | n/a | Driver metadata: `resources/<mode>/ignition/database-driver/<Name>/config.json` (classname, URL format, default translator). The `.jar` itself must be placed in `user-lib/jdbc/` either by derived Dockerfile or bootstrap-container copy. |
| `database-translator` | yes | n/a | `resources/<mode>/ignition/database-translator/<TYPE>/config.json`. Built-ins (POSTGRES, MYSQL, MSSQL, ORACLE, SQLITE, GENERIC) are shipped; custom translators are file-seedable the same way. |
| `opc-ua-connection` | (pending) | (pending) | Outbound OPC-UA connections (gateway connects to an external OPC-UA server). The template does not include one; the path is presumed to be `resources/<mode>/com.inductiveautomation.opcua/connection/<name>/{config.json,resource.json}` but this needs verification. Separate from `opc-ua server-config` (the gateway's own UA server) which IS in the template. |
| `opc-ua server-config` | yes | n/a | `resources/<mode>/com.inductiveautomation.opcua/server-config/config.json`. Anonymous-access, bind ports, security policies are file-seedable. |
| `idp-oidc` | (pending) | (pending) | The template ships an `identity-provider/default/config.json` of `type=internal`. An OIDC provider entry would presumably be `resources/<mode>/ignition/identity-provider/<name>/config.json` with `profile.type=oidc` plus a client-secret. The client-secret is the part most likely to need the secret-provider indirection. Needs verification (experiment). |
| `idp-saml` | (pending) | (pending) | Same parent path as `idp-oidc` with `profile.type=saml`. SAML signing certs are typically referenced as secrets. Needs verification. |
| `mqtt-engine-connection` | (pending) | (pending) | Settings used by Cirrus Link MQTT Engine to connect outbound to a broker. Path is presumed under `com.cirruslink.mqttengine/connection/` once the module is loaded. Requires the MQTT Engine `.modl` to be installed first (depends on module-install verdict). |
| `tag-provider` | yes | n/a | The template's `resources/core/ignition/tag-provider/` directory exists. Per-provider files under `<name>/{config.json,resource.json}`. Realtime providers (memory/expression) are file-seedable; database-backed historical providers are file-seedable in config but require the DB connection to be working. |
| `alarm-pipeline` | (pending) | n/a | Likely under `resources/<mode>/ignition/alarm-pipeline/<name>/` or in a per-project resource directory. Needs verification of whether gateway-level pipelines are seedable from the resources tree or only from a project's `com.inductiveautomation.alarm/` resources. |
| `project-resource` | (pending) | n/a | Projects mount to `/usr/local/bin/ignition/data/projects/<project>/`. The template mounts `services/ignition/projects` there directly. Resource format is `<project>/com.inductiveautomation.<module>/<resource-type>/<name>/{resource.json,data.bin,...}`. File-seedable in principle; needs verification that resources placed this way are loaded without a UI import step. |
| `gateway-network-link` | (partial) | n/a | The gateway's own UUID is file-seedable at `data/config/local/ignition/gateway-network/uuid.txt` (the template's bootstrap script writes a deterministic MD5-based UUID there). Outbound peer connections live in `resources/<mode>/ignition/gateway-network-settings/` and `resources/<mode>/ignition/gateway-network-proxy-rules/` (template shows both). Per-link approval state is the part most likely to need UI confirmation; needs verification. |
| `theme-asset` | yes | n/a | `resources/<mode>/com.inductiveautomation.perspective/themes/<name>/{config.json,resource.json}`. The template ships `dark-cool`, `dark-warm`, `light-cool`, `light-warm`. New themes are added with the same pattern. |
| `jvm-arg` | yes | n/a | JVM args go on the gateway container `command:` line after `--`. Example from the template: `-Dignition.config.mode=${DEPLOYMENT_MODE:-dev}`. No env-var wrapper is needed; the compose `command:` is the seam. |
| `env-var` | yes | n/a | Standard container env. Documented commissioning vars include `ACCEPT_IGNITION_EULA`, `GATEWAY_ADMIN_USERNAME`, `GATEWAY_ADMIN_PASSWORD`, `IGNITION_EDITION`, `IGNITION_LICENSE_KEY`, `IGNITION_ACTIVATION_TOKEN`, `IGNITION_ROOT_KEY_PASSWORD_FILE`, `GATEWAY_MODULES_ENABLED`. |
| `secret-reference` | yes | (partial) | A `config.json` referencing a secret looks like `{"<field>": {"data": {"providerName": "<provider>", "secretName": "<name>"}, "type": "Referenced"}}`. The provider and secret name are file-seedable; the secret value itself lives in `resources/<mode>/ignition/secret-provider/<provider>/config.json` as a JWE blob. Plaintext-on-first-boot acceptance is pending (experiment B). |
| `module-install` | (pending) | n/a | See the **Module install verdict** section above. |

## Methodology

This investigation runs on `inductiveautomation/ignition:8.3.6` and walks three kinds of evidence:

1. **Inspection of the reference template.** The `inductive-automation/template-ignition-project` repo is a validated, working file-seeded Ignition project. Every resource present in its `services/ignition/config/resources/core` and `services/ignition/config/resources/dev` trees is by definition file-seedable in 8.3, because the template boots cleanly with them. Rows whose verdict is `yes` and whose template-presence is obvious are answered this way.
2. **Three load-bearing experiments** that affect many rows at once:
   - **A** (`lastModificationSignature` validation): take a template resource verbatim, mutate `config.json` without updating `resource.json.attributes.lastModificationSignature`, boot, and observe whether the gateway rejects, accepts, or reverts the change. If signatures are validated strictly, the matrix has to acknowledge that file-seeding requires computing the signature; if not, simple plain-`config.json` writes are enough.
   - **B** (plaintext secret acceptance): write a `secret-provider/internal-secret-provider/config.json` with a plaintext value (not a JWE blob), boot, and observe whether the gateway rejects, auto-encrypts, or accepts as-is. This determines whether `file-seedable-secret` is `yes`, `partial`, or `no` for every connection type that uses the internal secret provider.
   - **C** (`GATEWAY_MODULES_ENABLED` semantics): place an `MQTT-Engine.modl` via each of options (a) runtime volume-mount, (b) derived Dockerfile, (c) bootstrap-container copy, with `GATEWAY_MODULES_ENABLED` set to (i) the module identifier (e.g. `com.cirruslink.mqtt.engine`), (ii) the fully-qualified in-container path. Determine which combinations cause the gateway to show MQTT Engine on the Modules page.
3. **Per-row verification** for rows the template does not cover (outbound OPC-UA, OIDC IDP, SAML IDP, mqtt-engine-connection, alarm-pipeline, project-resource).

Every confirmed verdict in the table above is backed by either a template-tree path or a screenshot captured at `scripts/seeding-poc/screenshots/`. The Playwright assertion script at `scripts/seeding-poc/boot.py` automates the `db-connection` row end-to-end (boot → log in → navigate → assert → screenshot → tear down) and exits non-zero if the seed does not appear in the UI; this serves as the regression gate for Phase 1's headline claim.
