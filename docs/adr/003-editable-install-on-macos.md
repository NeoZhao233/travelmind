# ADR 003: Use non-editable installs in the current macOS environment

## Status

Accepted for the current development environment; revisit when the filesystem behavior changes.

## Problem

The project was present in the virtual environment as an editable install, but Python could not
import `travelmind`. Python's verbose startup log showed that it skipped the editable `.pth` file
because macOS had applied the `hidden` filesystem flag. Running `uv sync` reproduced the flag and
the import failure.

## Alternatives

- Use `uv sync --no-editable` everywhere.
- Set `PYTHONPATH=src` in every development command.
- Remove the `src` project layout.
- Clear the macOS file flag after synchronization.

An initial attempt kept the editable installation and cleared the flag with `chflags nohidden`.
The import passed in the bootstrap process, but the filesystem flag was reapplied before the next
process and the cold-start verification failed. A one-process success was therefore insufficient.

## Decision

Use `uv sync --no-editable --reinstall-package travelmind` through `scripts/bootstrap.sh`. This
installs the built package without depending on a `.pth` link, forces the same-version local wheel
to be rebuilt after source changes, and immediately runs an import smoke test. Contributors rerun
bootstrap after source changes and before verification.

## Why

`PYTHONPATH` would make correctness depend on shell-specific state, while removing the `src` layout
would weaken protection against importing an uninstalled local package by accident. A regular wheel
install exercises a deployment-like import path and remains stable when `.pth` processing fails.

## Costs and risks

- Source changes are not reflected until bootstrap reinstalls the local wheel.
- Running raw `uv sync` can switch the project back to editable mode and reproduce the failure.
- The workflow is slower than a normal editable development install.
- A future uv, Python, or filesystem update may allow editable mode again.

## Verification evidence

- `scripts/bootstrap.sh` installs non-editably and ends with a package import smoke test.
- `scripts/verify.sh` checks package import, CLI cold start, unit tests, and Ruff.
- `tests/test_cli.py` protects the demo command contract.

## Interview questions

- Why did an installed distribution still fail to import?
- What is an editable install and how does a `.pth` file work?
- Why not solve the issue with `PYTHONPATH`?
- What development convenience is lost with a non-editable install?
- Why did the first `chflags` repair appear to work but fail on cold start?
- How would CI detect this environment-specific regression?
- Why can dependencies be synchronized while the installed local source is stale?
