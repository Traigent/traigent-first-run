# Maintainer tests

This directory is CI for the guide itself — the quality gates that keep the guidance honest — not
something a customer runs. See [`behavioral/README.md`](behavioral/README.md) for the containerized
behavioral-contract harness and [`guidance_budget/README.md`](guidance_budget/README.md) for the
guidance byte-budget ledger. The `npx skills add` install ships only
[`skills/traigent-first-run`](../skills/traigent-first-run/), never anything under this directory.
