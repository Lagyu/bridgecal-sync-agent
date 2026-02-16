from __future__ import annotations

import typer

from .commands.doctor import doctor
from .commands.sync import sync

app = typer.Typer(no_args_is_help=True, add_completion=False)

app.command()(doctor)
app.command()(sync)
