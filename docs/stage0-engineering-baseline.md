# Stage 0 report: reproducible engineering baseline

Date: 2026-09-07

## Acceptance criteria

- Locked dependency synchronization succeeds.
- The installed `travelmind` package imports in a fresh process.
- The CLI starts and completes its deterministic demo.
- Unit and smoke tests pass.
- Static analysis passes.
- The same checks pass in a newly created clean virtual environment.

## Failure discovered

The existing `.venv` contained `travelmind-0.1.0.dist-info`, so the distribution appeared to be
installed, but `import travelmind` and CLI startup failed. Python verbose startup logs showed that
the editable-install `.pth` file was skipped because it carried the macOS `hidden` filesystem flag.

This distinction matters: dependency synchronization metadata alone is not proof that an
application can cold-start.

## Failed first repair

The first repair cleared the flag with `chflags nohidden`. Import succeeded immediately inside the
bootstrap command but failed from the next process because the flag was reapplied. The immediate
check produced a false sense of recovery; a separate-process verification exposed it.

## Final decision

`scripts/bootstrap.sh` now uses a locked, non-editable install and explicitly reinstalls the local
`travelmind` package. This avoids `.pth` processing, refreshes same-version source changes, and
exercises an import path closer to deployment. The trade-off is that bootstrap must be rerun after
source changes. ADR 003 records why `PYTHONPATH`, removing the `src` layout, and the initial flag
repair were rejected.

## Verification evidence

Project environment:

```text
TravelMind 0.1.0 imported from .venv/lib/python3.11/site-packages/travelmind/__init__.py
6 tests passed
Ruff: all checks passed
CLI demo: completed
uv sync --check: no changes required
```

Clean-room environment:

```text
Created a second virtual environment under /private/tmp
Installed 61 locked packages
TravelMind 0.1.0 imported from that environment's site-packages
6 tests passed in a separate process
Ruff: all checks passed
CLI demo: completed
```

The temporary clean-room environment contained no persistent project data and was used only for
installation verification.

## Interview-ready discussion

- An installed distribution can still be non-importable when its editable source link is ignored.
- A healthy environment check should exercise import and application startup, not only package-list
  metadata.
- Separate-process or cold-start tests catch failures hidden by state in the setup process.
- Editable installs optimize development speed; regular wheel installs improve deployment parity.
- Environment-specific workarounds must be documented with a removal condition instead of becoming
  unexplained permanent infrastructure.

## Next stage

Stage 1 will define the travel-domain corpus, source policy, chunk schema, structured place facts,
and a manually labeled retrieval evaluation set before implementing advanced retrieval methods.
