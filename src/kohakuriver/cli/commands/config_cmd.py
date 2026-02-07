"""Config management commands."""

import os
import subprocess
import sys
from typing import Annotated

import typer

from kohakuriver.cli import config as cli_config
from kohakuriver.cli.output import console, print_error, print_success

app = typer.Typer(help="Configuration commands")


@app.command("show")
def show_config():
    """Show current configuration."""
    from rich.table import Table

    table = Table(title="Current Configuration", show_header=True)
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")
    table.add_column("Source")

    # Network settings
    table.add_row(
        "HOST_ADDRESS",
        cli_config.HOST_ADDRESS,
        "env" if os.environ.get("HAKURIVER_HOST") else "default",
    )
    table.add_row(
        "HOST_PORT",
        str(cli_config.HOST_PORT),
        "env" if os.environ.get("HAKURIVER_PORT") else "default",
    )
    table.add_row(
        "HOST_SSH_PROXY_PORT",
        str(cli_config.HOST_SSH_PROXY_PORT),
        "env" if os.environ.get("HAKURIVER_SSH_PROXY_PORT") else "default",
    )

    # Path settings
    table.add_row(
        "SHARED_DIR",
        cli_config.SHARED_DIR,
        "env" if os.environ.get("HAKURIVER_SHARED_DIR") else "default",
    )

    # Output settings
    table.add_row("OUTPUT_FORMAT", cli_config.OUTPUT_FORMAT, "default")

    console.print(table)


@app.command("completion")
def generate_completion(
    shell: Annotated[
        str,
        typer.Argument(help="Shell type (bash, zsh, fish)"),
    ] = "bash",
    output: Annotated[
        str | None,
        typer.Option("--output", "-o", help="Output file"),
    ] = None,
):
    """Generate shell completion script."""
    try:
        # Get the path to the kohakuriver entry point
        result = subprocess.run(
            [sys.executable, "-m", "kohakuriver.cli.main", "--show-completion", shell],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            # Try alternative method
            if shell == "bash":
                completion_script = """
# KohakuRiver completion for bash
_kohakuriver_completion() {
    local IFS=$'\\n'
    COMPREPLY=( $(env COMP_WORDS="${COMP_WORDS[*]}" \\
                  COMP_CWORD=$COMP_CWORD \\
                  _KOHAKURIVER_COMPLETE=complete_bash \\
                  kohakuriver) )
    return 0
}
complete -F _kohakuriver_completion kohakuriver
"""
            elif shell == "zsh":
                completion_script = """
# KohakuRiver completion for zsh
#compdef kohakuriver

_kohakuriver() {
    eval $(env _KOHAKURIVER_COMPLETE=complete_zsh kohakuriver)
}
compdef _kohakuriver kohakuriver
"""
            elif shell == "fish":
                completion_script = """
# KohakuRiver completion for fish
complete -c kohakuriver -f -a "(env _KOHAKURIVER_COMPLETE=complete_fish kohakuriver)"
"""
            else:
                print_error(f"Unknown shell: {shell}")
                raise typer.Exit(1)
        else:
            completion_script = result.stdout

        if output:
            output_path = os.path.expanduser(output)
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            with open(output_path, "w") as f:
                f.write(completion_script)
            print_success(f"Completion script written to: {output_path}")

            # Print installation instructions
            console.print("\n[bold]Installation:[/bold]")
            if shell == "bash":
                console.print(f"  Add to ~/.bashrc: source {output_path}")
            elif shell == "zsh":
                console.print(f"  Add to ~/.zshrc: source {output_path}")
            elif shell == "fish":
                console.print(f"  Copy to: ~/.config/fish/completions/kohakuriver.fish")
        else:
            console.print(completion_script)

    except Exception as e:
        print_error(f"Failed to generate completion: {e}")
        raise typer.Exit(1)


@app.command("env")
def show_env():
    """Show environment variables for configuration."""
    from rich.table import Table

    table = Table(title="Environment Variables", show_header=True)
    table.add_column("Variable", style="cyan")
    table.add_column("Description")
    table.add_column("Current Value", style="green")

    env_vars = [
        ("HAKURIVER_HOST", "Host address", os.environ.get("HAKURIVER_HOST", "-")),
        ("HAKURIVER_PORT", "Host port", os.environ.get("HAKURIVER_PORT", "-")),
        (
            "HAKURIVER_SSH_PROXY_PORT",
            "SSH proxy port",
            os.environ.get("HAKURIVER_SSH_PROXY_PORT", "-"),
        ),
        (
            "HAKURIVER_SHARED_DIR",
            "Shared directory",
            os.environ.get("HAKURIVER_SHARED_DIR", "-"),
        ),
    ]

    for var, desc, value in env_vars:
        table.add_row(var, desc, value)

    console.print(table)
