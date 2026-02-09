---
title: kohakuriver config
description: Configuration and shell completion commands.
icon: i-carbon-settings
---

# kohakuriver config

The `kohakuriver config` command group provides configuration inspection and shell completion setup.

## Commands

### config show

Display the current CLI configuration.

```bash
kohakuriver config show
```

Shows:

- Host address
- Authentication status
- Configuration file paths
- Active settings

### config completion

Generate shell completion scripts.

```bash
kohakuriver config completion <shell>
```

| Shell  | Command                                                                            |
| ------ | ---------------------------------------------------------------------------------- |
| `bash` | `kohakuriver config completion bash >> ~/.bashrc`                                  |
| `zsh`  | `kohakuriver config completion zsh >> ~/.zshrc`                                    |
| `fish` | `kohakuriver config completion fish > ~/.config/fish/completions/kohakuriver.fish` |

After adding the completion script, restart your shell or source the config file:

```bash
source ~/.bashrc   # or ~/.zshrc
```

Tab completion works for:

- All subcommands and flags
- Node hostnames (for `-t` flag)
- Task IDs (for status, kill, logs, etc.)
- Container environment names

### config env

Display environment variables used by KohakuRiver.

```bash
kohakuriver config env
```

Shows all recognized environment variables and their current values:

| Variable             | Description             |
| -------------------- | ----------------------- |
| `KOHAKURIVER_HOST`   | Host server address     |
| `KOHAKURIVER_TOKEN`  | Authentication token    |
| `KOHAKURIVER_CONFIG` | Configuration file path |

## Related Topics

- [Host Configuration](../setup/host-configuration.md) -- Host config reference
- [Runner Configuration](../setup/runner-configuration.md) -- Runner config reference
- [Init](init.md) -- Generate config files
- [Configuration Reference](../reference/configuration.md) -- Full config reference
