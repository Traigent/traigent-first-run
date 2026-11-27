# Security Policy

## Scope

- **In scope:** the guide (`GUIDE.md`, `skills/traigent-first-run/`), including the bundled scripts that run on the user's machine; the root `AGENTS.md`, `CLAUDE.md` and `README.md` (assistant-facing and user-facing instructions read during a guided run); the repository configuration in `.github/` (workflows, CODEOWNERS), including any way a pull request can make CI run code from `tests/` or `tools/` with more access than intended; and secrets or personal data exposed in any tracked file, including `reports/`.
- **Out of scope:** other flaws in `tests/` and `tools/`, which are repository maintenance only and play no part in a guided run; `deps/` (a dependency-scanner mirror of the bundled lock file); `.env.example` placeholder values (a real credential found there is in scope); and the licensing files (`LICENSE`, `NOTICE`, `CONTRIBUTOR-LICENSING.md`).
- **Out of scope for this repository, report elsewhere:** the Traigent Python SDK via <https://github.com/Traigent/Traigent/security/advisories/new>; the hosted Traigent service to [security@traigent.ai](mailto:security@traigent.ai).

## Reporting a vulnerability

Please report security issues privately rather than in a public issue or pull request.

1. **Preferred:** GitHub private vulnerability reporting: <https://github.com/Traigent/traigent-first-run/security/advisories/new>.
2. **Alternatively:** email [security@traigent.ai](mailto:security@traigent.ai).

Please include:

- a description of the issue and where it is (a file, or the guide step);
- steps to reproduce;
- the potential impact;
- the commit you tested;
- a suggested fix, if you have one.

Do not include real secrets or customer data in a report.

We will acknowledge receipt within 48 hours and provide a detailed response within 7 days.

## Supported versions

This repository publishes no releases. The guide is used from the `first-run-guide` branch, and fixes land there. Only its current tip is supported.

## Disclosure

We follow coordinated disclosure. We will work with you on a fix and a timeline, publish an advisory when a fix is available, and credit you in the advisory if you want to be credited. Please give us a reasonable chance to fix the issue before you disclose it publicly.
