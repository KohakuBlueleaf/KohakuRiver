---
title: Contributing
description: How to contribute to KohakuRiver, PR process, and code review guidelines
icon: i-carbon-collaborate
---

# Contributing to KohakuRiver

This guide covers the contribution workflow for KohakuRiver, including how to submit changes, the pull request process, and code review expectations.

## Repository Layout

KohakuRiver is a monorepo containing four distinct components:

```
KohakuRiver/
├── src/kohakuriver/            Python   Backend (host, runner, CLI, DB, models)
├── src/kohakuriver-manager/    JS/Vue   Web dashboard
├── src/kohakuriver-doc/        JS/Vue   Documentation site (this site)
└── src/kohakuriver-tunnel/     Rust     Tunnel client binary
```

Each component has its own build tooling but shares the same repository, branch model, and review process.

## Getting Started

1. Fork and clone the repository.
2. Follow the [Development Setup](./development-setup.md) guide to install dependencies.
3. Create a feature branch from `main`.
4. Make changes, write tests if applicable, and ensure everything works locally.
5. Open a pull request against `main`.

## Branch Naming

Use descriptive branch names with a category prefix:

- `feat/overlay-ipv6` -- new features
- `fix/heartbeat-timeout` -- bug fixes
- `refactor/split-overlay-manager` -- refactoring
- `docs/add-dev-guide` -- documentation

## Commit Messages

Write clear, concise commit messages that describe **what** changed and **why**. The project uses short imperative messages:

```
fix some iommu handling and VM reboot mechanism
better restart handling
split large file
refactoring for avoid long functions
```

Keep messages focused on a single logical change. If a commit touches multiple subsystems, mention which ones.

## Pull Request Process

1. **Self-review** your diff before requesting review.
2. Ensure the PR description explains the motivation, not just the mechanics.
3. Link any related issues.
4. Keep PRs focused -- avoid mixing unrelated changes.

### PR Checklist

- Does the change compile/run without errors on all affected components?
- Are new configuration fields documented in the dataclass docstrings?
- Are new API endpoints reflected in the Pydantic `requests.py` models?
- For frontend changes, does `npm run format` pass cleanly?
- For Python changes, do existing CLI commands still work?

## Code Review Expectations

- All changes should be reviewed before merging.
- Reviewers look for correctness, clarity, and consistency with existing [Conventions](./conventions.md).
- Address review feedback with additional commits (do not force-push during review).

## Testing

KohakuRiver does not have a formal test suite at this time. Before submitting a PR:

- **Backend**: Start a host and runner locally and verify the changed behavior. Check logs with `LOG_LEVEL=debug` for unexpected errors.
- **Frontend**: Run `npm run dev` in `src/kohakuriver-manager/` and test in the browser. Verify Element Plus components render correctly in both light and dark mode.
- **Tunnel**: Run `cargo build --release` in `src/kohakuriver-tunnel/` and verify the binary can connect to a running runner.
- **CLI**: Run `kohakuriver --help` and exercise the changed command.

## What to Change Where

```
Want to change...                Look in...
─────────────────────────────    ───────────────────────────────────────
Task scheduling logic            host/services/task_scheduler.py
Node resource calculation        host/services/node_manager.py
Container lifecycle              runner/services/task_executor.py
                                 runner/services/vps_manager.py
VM lifecycle                     runner/services/vm_vps_manager.py
                                 qemu/client.py
API request/response shapes      models/requests.py
Task/Node DB schema              db/task.py, db/node.py
Auth/permissions                 db/auth.py, host/auth/
CLI commands                     cli/commands/*.py
CLI output formatting            cli/formatters/*.py
Overlay networking               host/services/overlay/
                                 runner/services/overlay_manager.py
Tunnel protocol                  tunnel/protocol.py (Python)
                                 kohakuriver-tunnel/src/protocol.rs (Rust)
Dashboard pages                  kohakuriver-manager/src/pages/
Dashboard stores                 kohakuriver-manager/src/stores/
Dashboard API calls              kohakuriver-manager/src/utils/api/
```

## Reporting Issues

Open a GitHub issue with:

- A clear title describing the problem.
- Steps to reproduce.
- Expected vs. actual behavior.
- Relevant log output (use `LOG_LEVEL=debug` for verbose output).

## Code of Conduct

Be respectful. Technical disagreements should focus on the code, not the person.
