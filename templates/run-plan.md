# Traigent Run Plan — record (one per optimization run)

Capture format for a run. The **recommended values come from the Traigent service**
(`traigent plan` / `traigent recommend`), not from this file — see the
`traigent-run-plan` skill. The defaults below are only starting points so
you are not staring at blank fields; confirm or adjust each with the user.

**Run name** (suggested convention): `<agent>__<dataset-subset>__<objectives>__<YYYY-MM-DD-HHMM>`

## Context sent to Traigent
- Task / what the agent does:
- Agent entrypoint (file:function):
- Dataset size / holdout split:
- Objectives the user cares about:
- Budget / max spend:
- Prior run id or portal context:

## Plan (service-returned + your confirmations)
| Option | Default starting point | Service value | User decision |
|---|---|---|---|
| Objectives | `["accuracy"]` (add `"cost"`/`"latency"` only to trade accuracy away) |  |  |
| Models | 1 premium + 2 mid + 2 low-cost across vendors |  |  |
| Knobs | from `traigent recommend` / `recommend_configuration_space()` |  |  |
| Algorithm | `auto` (cloud smart; converges without a full grid) |  |  |
| max_trials | bounded so `max_trials × dataset_size` fits budget & quota |  |  |
| Cost cap (USD) | `5.00` (`TRAIGENT_RUN_COST_LIMIT`) |  |  |
| offline | `false` for the portal run; `true` only for a local baseline |  |  |

## Dry-run (mock, free, offline) — always first
- Command / entrypoint:
- Trials ran / failed:
- Evaluator sanity gate (known-good ≥0.9, known-bad ≤0.1):
- Estimated real-run cost (`max_trials × dataset_size` LLM calls × $/call):

## Real run (only on explicit user go)
- User approved cost: [ ]
- Cost cap confirmed: [ ]
- Run id:
- Portal link:

## Carry forward
After the run, paste the next-step recommendation from the `traigent-next-run` skill.
