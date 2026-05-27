"""Top-level Typer app. Phase 2 fleshes out additional subcommands; Phase 3
wires only the `modules` sub-app so it can ship independently.
"""

from __future__ import annotations

import typer

from ignition_stack.commands.modules import modules_app

app = typer.Typer(
    name="ignition-stack",
    help="Generate ready-to-run Docker Compose stacks for Ignition 8.3.",
    no_args_is_help=True,
)
app.add_typer(modules_app, name="modules")


if __name__ == "__main__":
    app()
