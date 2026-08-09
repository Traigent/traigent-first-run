# Project Artifact Permission

**Draft pending review by counsel.** It states the intent this repository already
operates under; it is published so a reviewer does not have to infer it.

## What this covers

A **Project Artifact** is a file this guide creates in the project you point it at,
or a change it makes to a file already there. In practice that is everything under
`traigent-runs/` - the filled `run-plan.md`, `config-space.json`, tuning and holdout
splits, calibration files, generated agent and evaluator wrappers, readiness reports
and logs - plus the `/traigent-runs/` line it adds to your `.gitignore` and the
provider key line it adds to your `.env`.

A Project Artifact is **not** the Traigent First Run skill, scripts, references, or
assets as distributed here; it is not the Traigent SDK; and it is not any
third-party software.

## The permission

To the extent a Project Artifact contains copyrightable material owned by Traigent
Ltd - most plainly, text carried over from `assets/run-plan.md` or from a reference
implementation in `references/` - Traigent Ltd grants you a perpetual, worldwide,
non-exclusive, irrevocable, royalty-free, sublicensable license to use, reproduce,
modify, distribute, and license that material under any terms you choose.

No obligation attaches: not to disclose source, not to keep a Traigent notice, not
to license your project under Apache-2.0 or anything else.

Traigent Ltd claims no ownership of your inputs, your project's material, your
datasets, or model output produced during a run.

This permission grants no rights in Traigent trademarks, and it changes no
third-party license - including the license of the separately obtained Traigent SDK,
which remains AGPL-3.0-only or commercial on its own terms.

THE TRAIGENT-OWNED MATERIAL COVERED BY THIS PERMISSION IS PROVIDED "AS IS", WITHOUT
WARRANTIES OR CONDITIONS OF ANY KIND, TO THE MAXIMUM EXTENT PERMITTED BY APPLICABLE
LAW.

## Why it is written down

The guide's whole job is to put files in a repository that is not ours. Apache-2.0
already leaves your project alone, and this permission does not narrow it - it
removes the question so a licence review does not have to reach it.
