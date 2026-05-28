"""Project tree writer.

The writer composes a generated project at ``<output>/<name>/`` by:

1. Copying the static asset tree (``scripts/``, ``services/<dir>/``)
   from the package's template payload, parametrised per-gateway when
   the project has more than one.
2. Rendering ``docker-compose.yaml`` through
   :func:`ignition_stack.compose.engine.render_compose`, which preserves
   YAML anchors via ruamel.yaml.
3. Rendering ``.env`` from the resolved :class:`ProjectConfig`,
   including per-gateway HTTP port entries when the project is
   multi-gateway.

Every file is written in binary with explicit ``\\n`` newlines so the
output is byte-identical on Linux, macOS, and Windows.
``docker-bootstrap.sh`` in particular must be LF-only or bash inside
the container chokes on CR bytes.
"""

from __future__ import annotations

from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

from ignition_stack.catalog.loader import CatalogLoadError, load_catalog
from ignition_stack.catalog.schema import Catalog
from ignition_stack.compose.engine import render_compose
from ignition_stack.config.schema import ProjectConfig
from ignition_stack.services.loader import load_all_services, service_dir
from ignition_stack.services.resolver import resolve

_STATIC_PACKAGE = "ignition_stack.templates"
_STATIC_PROFILE = "standalone-postgres"


def write_project(config: ProjectConfig, target_dir: Path) -> list[Path]:
    """Generate the project tree at ``target_dir``.

    The config is resolved first (implicit dependencies expanded - see
    :func:`ignition_stack.services.resolver.resolve`) so the compose output and
    the on-disk seeds agree on the same fully-expanded stack.

    Returns the list of files written (absolute paths), in the order they
    were written. Raises :class:`FileExistsError` if ``target_dir`` already
    has files (refuses to clobber).
    """
    target_dir = Path(target_dir).resolve()
    if target_dir.exists() and any(target_dir.iterdir()):
        raise FileExistsError(
            f"target directory '{target_dir}' is not empty; refusing to overwrite"
        )
    target_dir.mkdir(parents=True, exist_ok=True)

    config = resolve(config)

    written: list[Path] = []

    written.extend(_copy_static_tree(config, target_dir))
    written.extend(_copy_service_seeds(config, target_dir))
    written.extend(_overlay_gateway_resources(config, target_dir))
    _ensure_modules_cache_dir(config, target_dir)
    written.append(_write_compose(config, target_dir))
    written.append(_write_env(config, target_dir))

    proxy_file = _write_reverse_proxy_readme(config, target_dir)
    if proxy_file is not None:
        written.append(proxy_file)
    dropin_file = _write_mcp_dropin_readme(config, target_dir)
    if dropin_file is not None:
        written.append(dropin_file)
    post_setup_file = _write_post_setup_stub(config, target_dir)
    if post_setup_file is not None:
        written.append(post_setup_file)

    return written


def _copy_service_seeds(config: ProjectConfig, target_dir: Path) -> list[Path]:
    """Copy each service's ``seed/service/`` tree into ``services/<name>/``.

    These are files mounted into the service's own container (a Postgres
    initdb script, a broker config, a realm export). The destination dir is
    the database name for the DB and the service slug for everyone else - the
    same names the compose fragments mount from.
    """
    written: list[Path] = []
    for src_dir, dest_name in _seed_sources(config):
        seed_service = src_dir / "seed" / "service"
        if not seed_service.is_dir():
            continue
        for rel, content, executable in _walk_template(seed_service):
            written.append(
                _write_static(target_dir, f"services/{dest_name}/{rel}", content, executable)
            )
    return written


def _overlay_gateway_resources(config: ProjectConfig, target_dir: Path) -> list[Path]:
    """Overlay every seeding service's ``seed/gateway-resources/`` onto gateways.

    Per the Phase-1 matrix, file-seedable connections (db-connection, the
    internal-secret-provider that holds its password, ...) are dropped into
    each gateway's ``config/resources/`` tree, which the bootstrap copies into
    the gateway data volume on first boot. The same resource set lands on every
    gateway so each can reach the shared service.
    """
    written: list[Path] = []
    gw_dirs = [gw.name for gw in config.gateways] if config.is_multi_gateway else ["ignition"]
    for src_dir, _ in _seed_sources(config):
        resources_tree = src_dir / "seed" / "gateway-resources"
        if not resources_tree.is_dir():
            continue
        for rel, content, executable in _walk_template(resources_tree):
            for gw_dir in gw_dirs:
                written.append(
                    _write_static(target_dir, f"services/{gw_dir}/{rel}", content, executable)
                )
    return written


def _seed_sources(config: ProjectConfig) -> list[tuple[object, str]]:
    """(service-catalog dir, on-disk destination name) for the DB + each service.

    Only services whose manifest sets ``seeds_gateway_resources`` contribute
    gateway resources, but ``seed/service/`` is copied for any service that
    ships one regardless.
    """
    sources: list[tuple[object, str]] = []
    if config.database is not None:
        sources.append((service_dir(config.database.kind), config.database.name))
    for svc in config.services:
        sources.append((service_dir(svc), svc))
    return sources


def _ensure_modules_cache_dir(config: ProjectConfig, target_dir: Path) -> None:
    """Create an empty modules/cache/ when any gateway lists modules.

    The compose engine emits a bind mount of this directory into every
    gateway's bootstrap container; absent the directory, `docker compose
    up` fails before the bootstrap runs. The directory stays empty here
    - `ignition-stack modules download` (Phase 3) populates it.
    """
    if not any(gw.modules for gw in config.gateways):
        return
    (target_dir / "modules" / "cache").mkdir(parents=True, exist_ok=True)


def _copy_static_tree(config: ProjectConfig, target_dir: Path) -> list[Path]:
    """Copy the static portion of the project tree.

    For a single-gateway project the scripts + services/ignition layout
    is copied verbatim (Phase 2 walking skeleton). For multi-gateway
    projects the services subtree is duplicated once per gateway under
    ``services/<gateway-name>/`` so each bootstrap container can mount
    its own template-source.
    """
    written: list[Path] = []
    static_root = _static_root()

    for src_rel, content, executable in _walk_template(static_root):
        if src_rel == "docker-compose.yaml":
            # The compose file is rendered separately by the engine; the
            # bundled copy is only there to seed the byte-identical Phase
            # 2 golden during development.
            continue
        if src_rel.startswith("services/"):
            if config.is_multi_gateway:
                for gw in config.gateways:
                    fan_rel = src_rel.replace("services/ignition/", f"services/{gw.name}/", 1)
                    written.append(_write_static(target_dir, fan_rel, content, executable))
            else:
                written.append(_write_static(target_dir, src_rel, content, executable))
        else:
            written.append(_write_static(target_dir, src_rel, content, executable))

    return written


def _write_static(target_dir: Path, rel: str, content: bytes, executable: bool) -> Path:
    dst = target_dir / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(content)
    if executable:
        dst.chmod(0o755)
    return dst


def _write_compose(config: ProjectConfig, target_dir: Path) -> Path:
    catalog = _maybe_load_catalog(config)
    rendered = render_compose(config, catalog=catalog)
    dst = target_dir / "docker-compose.yaml"
    dst.write_bytes(rendered.encode("utf-8"))
    return dst


def _maybe_load_catalog(config: ProjectConfig) -> Catalog | None:
    """Load the bundled catalog only when a gateway actually needs it.

    Saves a parse + I/O for the common module-free single-gateway case
    and keeps test fixtures from needing modules.yaml to be reachable.
    """
    if not any(gw.modules for gw in config.gateways):
        return None
    try:
        return load_catalog()
    except CatalogLoadError as exc:
        raise RuntimeError(
            "modules referenced in project config but modules.yaml could not be loaded"
        ) from exc


def _write_env(config: ProjectConfig, target_dir: Path) -> Path:
    env_path = target_dir / ".env"
    env_path.write_bytes(_render_env(config).encode("utf-8"))
    return env_path


def _render_env(config: ProjectConfig) -> str:
    """Render the project .env. Always LF-terminated, no Windows surprises.

    Data-driven: the fixed gateway keys come first, then the database block,
    then each catalog service contributes its image key and preset credentials
    from its manifest ``env`` map, so adding a service needs no writer change.
    """
    lines = [
        "# Generated by ignition-stack. Edit values, do not delete keys.",
        f"COMPOSE_PROJECT_NAME={config.name}",
    ]
    if not config.is_multi_gateway:
        # Phase 2 walking-skeleton compatibility: a single shared
        # GATEWAY_NAME / GATEWAY_HTTP_PORT pair the bootstrap + gateway
        # services both reference.
        gw = config.gateways[0]
        lines += [
            f"GATEWAY_NAME={config.name}",
            f"GATEWAY_HTTP_PORT={gw.http_port}",
        ]
    else:
        for gw in config.gateways:
            lines.append(f"{gw.env_prefix}_HTTP_PORT={gw.http_port}")

    lines.append(f"IGNITION_IMAGE={config.ignition_image}")
    if config.database is not None:
        lines.append(f"{config.database.image_env}={config.database.image}")
    lines += [
        f"ADMIN_USERNAME={config.admin_username}",
        f"ADMIN_PASSWORD={config.admin_password}",
    ]
    if config.database is not None:
        db = config.database
        lines += [
            f"DB_USER={db.user}",
            f"DB_PASSWORD={db.password}",
            f"DB_HOST={db.name}",
        ]
        if db.extra_databases and db.kind in {"postgres", "mysql", "mariadb"}:
            lines.append(f"EXTRA_DATABASES={','.join(db.extra_databases)}")

    catalog = load_all_services()
    for svc in sorted(config.services):
        manifest = catalog[svc]
        lines.append(f"{manifest.image_env}={manifest.image}")
        for key, value in manifest.env.items():
            lines.append(f"{key}={value}")

    lines.append(f"TZ={config.timezone}")
    return "\n".join(lines) + "\n"


def _static_root() -> Traversable:
    return resources.files(_STATIC_PACKAGE) / _STATIC_PROFILE


_TRAEFIK_README = """\
# Reverse proxy: ia-eknorr/traefik-reverse-proxy

This project's wizard offered to install the preferred Traefik reverse
proxy here. The repo lives at https://github.com/ia-eknorr/traefik-reverse-proxy
and is **not** cloned automatically (the CLI never bundles a proxy
silently). Install it manually:

```sh
cd {path}
git clone https://github.com/ia-eknorr/traefik-reverse-proxy.git .
```

Then read that repo's README for routing and TLS setup. The gateway is
already exposed on a host port via `docker-compose.yaml`; the proxy can
either replace that mapping or sit in front of it.
"""

_MCP_DROPIN_README = """\
# MCP module drop-in

The Ignition MCP module is Early-Access and gated behind a survey, so
this CLI cannot bundle it. To enable the MCP service in this stack:

1. Request the module from
   https://inductiveautomation.com/early-access (Ignition MCP).
2. Drop the resulting `.modl` file into this directory:
   `modules/dropin/<filename>.modl`.
3. Re-run `docker compose up -d`. The bootstrap will copy any `.modl`
   present here into the gateway's `user-lib/modules/` on startup.

n8n is already configured in this stack; the MCP module is what
exposes the Ignition side of the conversation to n8n's workflows.
"""

_POST_SETUP_HEADER = """\
# Post-setup steps

Phase 7 generates this file from the seedability matrix + the resolved
config; the entries below are what the Phase-6 profiles flag for manual
follow-up. Anything not listed here is pre-seeded by the CLI.
"""


def _write_reverse_proxy_readme(config: ProjectConfig, target_dir: Path) -> Path | None:
    if config.reverse_proxy is None:
        return None
    proxy_dir = target_dir / config.reverse_proxy.path
    proxy_dir.mkdir(parents=True, exist_ok=True)
    dst = proxy_dir / "README.md"
    dst.write_bytes(_TRAEFIK_README.format(path=config.reverse_proxy.path).encode("utf-8"))
    return dst


def _write_mcp_dropin_readme(config: ProjectConfig, target_dir: Path) -> Path | None:
    if not config.mcp_dropin:
        return None
    dropin_dir = target_dir / "modules" / "dropin"
    dropin_dir.mkdir(parents=True, exist_ok=True)
    dst = dropin_dir / "README.md"
    dst.write_bytes(_MCP_DROPIN_README.encode("utf-8"))
    return dst


_SCALEOUT_GATEWAY_NETWORK_STEP = """\
## Approve the scaleout gateway-network link

Scaleout demos depend on a gateway-network link between `frontend` and
`backend`. The Phase-1 seedability matrix (see
`docs/ignition-seeding-matrix.md`, row `gateway-network-link`) marks this
row **partial**: each gateway's UUID is file-seeded by the bootstrap, and
the outbound peer-link path is known, but the per-link approval step
happens in the gateway UI and the exact peer-link JSON schema was not
pinned in Phase 1.

To finish the link manually after `docker compose up -d`:

1. Open the `frontend` gateway (`http://localhost:9088`), navigate to
   Config -> Networking -> Gateway Network, and add an outgoing connection
   to `${COMPOSE_PROJECT_NAME}-backend` on port 8060.
2. Open the `backend` gateway (`http://localhost:9089`) and approve the
   incoming connection request.
3. Repeat in reverse if you need bidirectional aggregation.
"""


def _write_post_setup_stub(config: ProjectConfig, target_dir: Path) -> Path | None:
    """Emit a minimal POST-SETUP.md when the project has any manual follow-ups.

    Phase 7 owns the real generator; this stub captures only what Phase-6
    profiles introduce: the MCP drop-in, the Traefik install, and the
    scaleout gateway-network approval (the matrix's ``gateway-network-link``
    row is partial - UUID + outbound path are file-seedable, per-link
    approval is UI-only). Phase 7 replaces the body with matrix-driven
    entries.
    """
    sections: list[str] = []
    if config.profile == "scaleout":
        sections.append(_SCALEOUT_GATEWAY_NETWORK_STEP.rstrip())
    if config.mcp_dropin:
        sections.append(
            "## Drop in the Ignition MCP module\n\n"
            "The MCP module is EA-gated; download it from the early-access "
            "survey and place the `.modl` in `modules/dropin/`. See "
            "`modules/dropin/README.md`."
        )
    if config.reverse_proxy is not None:
        sections.append(
            f"## Install the reverse proxy\n\n"
            f"The wizard scaffolded `{config.reverse_proxy.path}/` with a README "
            f"that walks you through cloning ia-eknorr/traefik-reverse-proxy and "
            f"routing this stack through it."
        )
    if not sections:
        return None
    body = _POST_SETUP_HEADER + "\n" + "\n\n".join(sections) + "\n"
    dst = target_dir / "POST-SETUP.md"
    dst.write_bytes(body.encode("utf-8"))
    return dst


def _walk_template(root: Traversable, prefix: str = "") -> list[tuple[str, bytes, bool]]:
    """Yield (relative-path, bytes, executable) for every file under ``root``.

    Skips Python package markers (``__init__.py``) and any pyc artifacts so
    the generated project doesn't contain Python plumbing.
    """
    out: list[tuple[str, bytes, bool]] = []
    for entry in sorted(root.iterdir(), key=lambda e: e.name):
        name = entry.name
        rel = f"{prefix}{name}"
        if entry.is_dir():
            out.extend(_walk_template(entry, prefix=f"{rel}/"))
            continue
        if name == "__init__.py" or name.endswith(".pyc"):
            continue
        # Shell scripts (the bootstrap, Postgres initdb hooks, ...) must be
        # executable so the container can run them directly.
        out.append((rel, entry.read_bytes(), rel.endswith(".sh")))
    return out
