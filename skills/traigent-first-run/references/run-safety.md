# Run Safety and Result Honesty

Use this reference for setup, dry-run, paid execution, portal verification, recovery, and claims.

## Contents

0. The standing rule
1. Environment and privacy
2. Static and mock validation
3. Approval and budgets
4. Connected-run readiness
5. Baseline and optimization
6. Post-run verification
7. Recovery

## The standing rule

**A first run does not stop a legitimate customer from onboarding. Ever.**

Where a customer's own data or code makes a check genuinely unsafe for **us** to perform, they get
full knowledge of what was not checked and what proceeding means - and then they proceed.
Disclosure, not a gate.

**Corollary: deduct for what the customer controls; never deduct for what we do not own.** A check
this guide declined to make is our boundary, not their defect, and it is never printed as their
failure. A ceiling that bounds what this card may *claim* is honest, because it describes evidence
we do not have. A block that bounds what the customer may *do* is ours to justify, and a boundary we
chose does not justify it.

**What this does not touch**, because "ever" is doing real work above and the file defines hard stops
below that are not in question. **The test is OWNERSHIP - whose is the thing in the way? - and the
list under it is examples rather than the set.** This rule is about a check WE declined to make,
where the obstacle is ours and nothing the customer does reaches it. It does not lift a stop that
waits on something only they can give.

Those are theirs, and among them: secret entry, a key this run has not been handed, a tracked
credential file, a modified ignore file, an environment they have not approved, a replay that changes their world,
spending their money without approval, or a readiness cap that blocks because a component is absent
rather than because a check was declined. Read the test, not the list - a stop this list happens not
to name is measured by the same question.

**Ownership requires a distinct remedy for each kind of stop.** The categories below distinguish
customer decisions, actions we decline, measurement failures, third-party limits, and our own
service failures. A declined check does not explain all of them.

1. **Theirs** - the list above. It waits on something only they can give, and their giving it clears
   the stop.
2. **An action WE refuse to take on their machine.** Not a check we declined to make, which costs
   them a measurement; a thing we will not do TO their project, which would cost them their machine.
   Executing arbitrary setup code during a dependency build is the live case. The corollary does not
   reach it - nothing is being deducted and no claim is being bounded - and the disclosure it owes
   is a ROUTE rather than a score: say what we will not run, and what they can do instead.
3. **A broken instrument.** An untrustworthy measurement cannot justify optimizing on that
   measurement. Stop the affected work, name what failed and which claims it prevents, and retain
   independent evidence that remains valid. A privacy or delivery failure can require stopping
   further calls without invalidating every quality observation already collected.
4. **Neither party's.** A provider can return an answer without reporting cost or token usage.
   That silence does not make a completed call fake or its quality unmeasurable. Continue the
   bounded primary-criterion run on the disclosed approval under "Missing cost or usage telemetry"
   below; repair is optional. Unknown charges remain unknown, and a conservative budget deduction
   is not a measurement of them. Approval still belongs to the customer; missing telemetry does
   not create approval or require them to repair the provider before onboarding.
5. **Ours, and not a check we declined.** Our own service or its tracking failing - a portal rung
   that will not come up, a connected run degrading to local-only mid-flight. The run can still
   measure quality; what it cannot do is record, and this file stops paid work at once for it. No
   disclosure makes it the customer's to weigh, and no route of theirs clears it, so it is neither
   an ask nor a route: say what failed, that it is ours, and what was or was not spent.

**A source build is category 2 and not category 4**, however much a platform with no published
wheels looks ownerless. What stops the run there is not the platform - it is this guide refusing to
execute setup code on their machine, which is a decision of ours and has a route out.

**Not "can they clear it", which is a different question and gets this wrong.** A customer whose
evaluator executes candidate code could clear that stop by rewriting the evaluator - and the whole
finding is that they should not have to, because the unmade check is ours. Difficulty is not the
test; whose the obstacle is, is.

Stated here, ahead of every gate below, because it is the rule each of them is measured against.

## Environment and privacy

### Why the install sits where it does

The opening gate establishes every scoreable fact available without installation, SKILL section 4 finishes
deferred local validation, and SKILL section 5 installs the SDK into the environment the customer
approved - an existing project environment or a new persistent `.venv`, because a first run should
end with Traigent installed where they will keep using it. After that point, the remaining capability and mock checks
need the installed SDK, so no useful independent work overlaps the install. Keep this one foreground command with its complete
resolver diagnostic; explain the wait and do not delegate it.

### Setup sequence

Only after the standard-library-only component checks:

1. Resolve the route from the selected agent, never from key names. Inventory presence—not values—in
   the process, handoff, and exact credentials a project-declared env loader, launcher, or secret
   manager exposes without external calls. Never enumerate stores or copy values; mark declared-only
   sources unverified. Reuse a matching credential in place when inheritable; on mismatch, do not call the
   file unsaved. Say: `Agent route: <vendor/model>. Provider credentials: <vendors and sources>.
   Traigent key: <present/absent> (not a provider credential).` Ask nothing here: a route whose
   credential is absent is decided at step 6 of this sequence, on its one stop. A route change requires
   recipient disclosure and approval; never rewrite a route merely to match a key. With no route,
   use the sole available vendor, or carry that choice to the same stop. Generated baselines need
   their model ladder; a user-owned baseline requires only its existing route and credential.
2. Choose the environment under Choosing the environment below, naming its absolute path before
   touching it: detect the candidates inside the project root, then propose the one, ask which of
   several, or offer to create the project's persistent `.venv` when none is usable. Preserve every
   existing environment until its owner says yes to the install; `.venv-traigent` is a fallback,
   not the no-environment default. The rules
   below own detection, the version guard, creation, recovery, and activation mechanics; never fall
   back to a shared or dependent environment the customer did not name. If resume validation
   verified this run's completed setup, skip selection and installation and continue with the
   remaining free checks or credential handoff.
3. Install the declared dependencies under SKILL.md's narrow authorization.
   Into an existing project environment: only what the version guard allows, after their yes to
   the resolved approval card. A new persistent `.venv` uses the combined creation/install approval
   below. Into the throwaway environment: the exact pins in
   `assets/requirements-first-run.txt`, never the project's own declarations, which the run never
   edits. Never use an unversioned `pip install traigent`. On the throwaway route,
   say first: `Installing traigent==0.27.0, litellm==1.93.0 and python-dotenv==1.2.2 into
   <absolute path>/.venv-traigent - a package fetch only: no provider or Traigent calls, and none
   of your project's code runs.` Then proceed: the notice is not a question, and the
   install-approval policy clause in the authorization table still governs. Keep this unattended
   step foregrounded, explain the wait, and do not delegate it; Why the install sits where it does above explains the wait. Then re-run `scripts/preflight.py` through the chosen interpreter without
   `--defer-missing-sdk`; `sdk-version: PASS` is required before continuing. On `sdk-version: FAIL`,
   preserve that environment, report its path and the concrete failure, and stop. Handle other
   failed records at their own gates; a credential-file mode finding is not an installation failure.
   Recovery below owns the next action; a persistent project environment is never recreated as
   walkthrough recovery. Nothing else catches a silent or partial install.
4. Verify capabilities and public signatures from the installed SDK. Use its public dataset
   loader/validator, decorator, and evaluation models; use a public no-execution contract validator
   when available, otherwise finish with safe mock plumbing and do not claim exhaustive static
   compatibility. Never recreate SDK binding fallbacks. Use resolved dataset paths for the pinned
   SDK's tracked nested-relative defect.
5. Run calibration deferred solely for a local installed dependency. Then run a fresh-process
   Traigent mock plumbing check only when every model call and external side effect is intercepted;
   exit it and never reuse that process for a real run.
6. After all applicable free checks, create or minimally update `.env` through
   the ordered credential handoff below, which selects the file: add only a
   genuinely missing selected-provider key, and stop once for only that secret locally; any other
   line is the `.env` rule's under Rules, which names the copied-actor route's one. Where the
   route's credential is absent and another vendor's is present, that stop closes its message with
   the lettered ask - `A.` preserve this route by adding <key>, marked recommended unless the user
   already chose the other vendor; `B.` change to <available vendor> - and nothing follows it: one
   reply pastes the key or changes the route. Do not request or route the Traigent key before the
   section-7 baseline checkpoint.
7. Where the copied-actor route in Static and mock validation was taken and the customer chose a
   route that calibrates - the file copy this run makes, or a target they paste - run that
   calibration once the target is in the file step 6 selected under the name the question stated
   - the copied file's absolute path this run wrote, or the value they pasted - the copy reads it
   there and nowhere else. A skip reply runs nothing. It is the one
   calibration this sequence runs after the credential handoff, because its target lives in the
   same owner-only file.

### Finding a supported interpreter

Use only locally installed Python 3.11-3.13 whose host installation is trusted. On POSIX, locate
`python3`, then `python3.13`, `python3.12`, and `python3.11` with `command -v`; inspect the returned
absolute paths before launching anything. Skip project-contained executables and unknown wrappers;
a command name is not provenance. Probe the first known host installation, continuing through that
list if its version is unsupported. This probe prints its absolute path and version:

```sh
"<trusted-host-python>" -I -S -B -c 'import sys; ok = (3, 11) <= sys.version_info[:2] < (3, 14); print(sys.executable, sys.version.split()[0]) if ok else None; sys.exit(0 if ok else 1)'
```

On Windows, list already installed paths with `py -0p`, then probe those executables directly in
3.13, 3.12, 3.11 order with the same `-I -S -B -c` check. Never use a launcher mode that auto-installs.
If the PATH/launcher search fails and `uv` is already present, use
`uv python find --offline --no-python-downloads '>=3.11,<3.14'` and inspect then probe its returned
host path too. The same known-host requirement applies to launcher and manager results.
Do not install a manager or download a runtime during this lookup. If none works, report readiness
as not yet measured and give one remedy: install Python 3.13 locally, then provide its executable
path to resume. An unsupported project environment remains untouched and is named as such.
Use the chosen executable's literal absolute path for later commands; do not depend on a shell
variable surviving the next tool call. This chooses a runtime for creating a new project or
throwaway environment, never an existing environment to install into.

### Choosing the environment

A first run ends with Traigent installed where the customer will keep using it.
In the commands below, `.../` is the absolute skill directory resolved under GUIDE.md. In this order:

1. **Detect.** Use the trusted host interpreter found above, by absolute path, to run
   `"<trusted-python>" -I -S -B ".../scripts/find_environments.py" --project-root
   "<project root>" --requirements ".../assets/requirements-first-run.txt"`.
   Keep the customer-project working directory under GUIDE.md's location rule. The detector reads
   candidate files and installed distribution metadata without executing candidate interpreters,
   importing project modules, or writing files. It recognizes directly contained names with `env`
   in any case, `pyvenv.cfg` plus `bin/python` or `Scripts/python.exe`, and `$VIRTUAL_ENV` or
   `$UV_PROJECT_ENVIRONMENT` when contained in the project. A config-bearing environment with a
   missing or broken interpreter, or a directory symlink, stays visible as unverified and preserved.
   Anything outside the project, or deeper
   than the root, is reachable only by a path the customer types. A matching executable and runtime
   version establish a candidate against the trusted host runtime; an unfamiliar executable is
   **unverified**, not absent or supported. Report that path and the detector's remedy, including
   rerunning with a matching trusted installed runtime where appropriate. Never run the unfamiliar
   candidate merely to find out what it is. Installed-package inventory also stays unverified when
   startup customization cannot be matched to trusted bootstrap code or a path entry exposes
   additional distributions outside the inventoried sites. Never execute those hooks to settle
   the uncertainty or remove them; use a verified environment under the choices below.
2. **Choose an existing environment or create the project's own.** Apply the path-preservation
   rules below before counting usable candidates. Exactly one candidate on
   Python 3.11-3.13: propose installing into it, by absolute path (`existing-project`). Several:
   ask which one - lettered, each with its absolute path and Python version - plus `other path`
   and, only when the name is free, `create .venv for this project`.
   None: say `No virtual environment found directly under the project root.` An unsupported
   version is not an absent environment: say
   `No supported virtual environment found directly under the project root`, followed by each
   reported `skipped` clause, such as `<path> was skipped (declared Python <version>, not
   3.11-3.13; runtime identity unverified)`.
   A `pyvenv.cfg` declaration outside that range also rules out the candidate: report its declared
   version as unsupported and its runtime identity as unverified, preserving it; do not seek an
   unsupported host Python to verify it.
   For other unverified candidates, say `An environment exists at <path>, but this run could not verify
   its runtime or installed-package inventory`, followed by its remedy. Keep these distinct even when other candidates work.
   A moved environment may be unverified because its cached startup code records its old path.

   In either case, when `<project root>/.venv` is absent, resolve the supported Python under
   Finding a supported interpreter and preview its absolute path and version, the absolute `.venv`
   path, the exact top-level pins in `assets/requirements-first-run.txt` and their package-declared
   dependencies. Explain that this creates the customer's persistent project environment and
   installs that SDK stack for continued use. Offer `A. Create .venv and install the SDK for this
   project (recommended). B. Use an existing environment - reply with its absolute path.` An
   explicit reply such as `A`, `create it`, or `I have no environment` to this preview authorizes
   both creation and that install (`new-project`); silence or elapsed time never selects it.
   After that yes, create the empty environment under Rules below. Use the isolated plan/apply
   procedure in step 3 to resolve the agreed pins and show the resolved additions before
   installation, as information rather than a second approval. Install only the previewed pins and
   their package-declared dependencies. A scope change, unexpected installed-version change,
   source-build requirement, or inconsistent plan stops
   this sequence; report it and obtain approval for any revised scope rather than extending that yes.
   The source-build refusal under Rules still applies.

   Check the name independently of the detector before offering creation: any existing `.venv`
   entry, including a file, an unsupported or broken environment, or a symlink (even dangling),
   occupies it. Never overwrite it or follow a `.venv` symlink into automatic selection. A usable
   ordinary `.venv` remains an existing candidate. When a new environment is needed but that name
   is occupied, name the preserved path and offer
   `A. Use a throwaway .venv-traigent (recommended). B. Use an existing environment - reply with
   its absolute path.` Wait for their explicit choice. An unsupported environment elsewhere does
   not occupy a free `.venv`; the normal new-project route still applies there.
3. **One SDK install approval.** Use the route's approval: the combined preview above for
   `new-project`, or the dependency-installation rule below for `throwaway`.
   An existing environment uses the resolved card here, because it already holds packages the
   resolver may change. Use the trusted runtime that verified
   this environment; for a new environment, that is the host runtime that created it. Prepare the version guard's proposed
   set below, then run `"<trusted-python>" -I -S -B ".../scripts/environment_install.py"
   plan --candidate "<absolute environment path>" --requirements
   ".../assets/requirements-first-run.txt" --plan "<local plan.json>"`, adding `--change <package>==<pinned>` only for each proposed replacement.
   Planning ignores pip configuration and `PIP_*` index settings; for private-index or offline
   setup, use `plan --no-index --find-links "<absolute local wheel directory>"` with a
   customer-supplied directory containing all required wheels.
   This fetches wheels and metadata into a temporary local plan directory; it changes no installed
   package and runs no customer startup hook or source build. It uses trusted bootstrap pip code,
   reads installed metadata as data, and constrains every other installed distribution to its
   current version. A conflict stops planning; use the failed-plan route under Version guard below.
   For `existing-project`, show the resulting card, including every transitive addition and every replacement:
   `Installing into <absolute path> (Python <version>) would add: <new packages with versions>.
   This will change <package> <installed> to <new> [one line per change, or changes: none].
   Only package artifacts were fetched; no installed packages changed. Proceed, or use a throwaway
   .venv-traigent instead?` Install only on an explicit yes; a no takes the throwaway route.
   Silence or elapsed time is never installation approval. That single yes covers each exact
   change line; no generic approval substitutes for a missing line.

   Apply that same plan with `"<trusted-python>" -I -S -B ".../scripts/environment_install.py"
   apply --plan "<local plan.json>" --approved-plan-sha256 <the displayed plan_sha256>`. The helper checks
   the environment's runtime, configuration and installed metadata and the plan's wheel hashes,
   then installs only those wheels without resolving again. A change to those inputs stops application;
   regenerate the card and obtain a new yes for changed scope. Keep the plan and hash in this run's
   local setup evidence. Never substitute the candidate's `-m pip`, a console `pip`, or a fresh
   unbound resolver call: startup hooks and a second resolution are outside this approval.
4. **Version guard.** The pins in `assets/requirements-first-run.txt` are the tested versions and
   the recommendation, not a requirement for their environment. `traigent` at or above `0.27.0`
   and `litellm` at or above its pin are kept as they are and only what is missing is installed;
   the setup evidence then carries the one-line note `not the tested versions`, naming them.
   Compare complete package versions, including prerelease, development, post-release, local and
   epoch segments, and canonical package names; malformed or ambiguous metadata stops the plan.
   A below-pin version is only a proposed replacement until the card's explicit
   `this will change <package> <installed> to <pinned>` receives a yes. The same exact-change rule
   covers every installed package, including `python-dotenv` and transitive dependencies. A
   dependency conflict needs a revised disclosed plan; never silently
   upgrade, downgrade, or reinstall an installed package. If planning fails, show
   `No install plan was produced; no installed packages changed. <observed resolver reason>.`
   Name any reported version conflict in the customer's terms; do not label a network or missing-wheel
   failure a dependency conflict. Recommend a compatible project environment.
   Offer the throwaway route only with its compatibility
   consequence: for example, `Your agent uses openai 3.x; this SDK stack requires openai below 3.
   A throwaway environment preserves yours, but would run your agent with that older dependency;
   compatibility is unverified.` Never recommend that dependency downgrade as the remedy or enter
   the fallback automatically. After an explicit fallback choice, show its resolved dependency
   versions and apply the existing static/mock checks to the selected agent before proposing a paid run.
   Record the versions actually installed and any difference from the original agent's dependency
   versions as this run's setup evidence.
5. **Throwaway route.** `.venv-traigent` under the project root with Python 3.11-3.13 and the
   exact pins (`throwaway`) - used only when the customer declines the project-environment
   install, refuses the guard's change line, or explicitly chooses it because `.venv` is occupied
   and cannot be used. Having no environment alone selects `new-project`, never this fallback.
   Before offering this route, apply the Version guard's compatibility disclosure, including when
   it is the alternative to an installed-version change.
   On this route only, the
   closing handoff carries the reminder SKILL.md states.

### Rules

- Preserve every existing environment the customer did not approve for the install, including
  every shared or dependent environment. An install lands only in the environment they said yes
  to, or in the throwaway `.venv-traigent`; never replace a project interpreter, and never install
  into a shared, dependent, external, or assistant-owned environment as a fallback. Only a path
  the customer typed reaches an environment outside the project.
- Before creating an environment, when the project is a Git worktree, ensure the project-root
  `.gitignore` excludes `/.venv/` for `new-project` or `/.venv-traigent/` for `throwaway`, preserving
  its existing rules. Add only the rule for the directory this run creates; adopting an existing
  environment adds neither rule. Do not initialize Git just for this. Both remain available after
  the walkthrough; `.venv` is the customer's persistent project environment, never cleanup material.
- Name the chosen environment by absolute path before creating or touching it. If the throwaway
  path already exists without the verified same-run setup below, inspect it without changing it,
  stop with its path and evidence, and recommend inspection. Remove and recreate the existing
  throwaway environment only on the user's explicit request. Never adopt a throwaway environment
  from a different or unverified run; it is not an automatic `existing-project` candidate.
  A persistent `.venv` this run created is never removed or
  recreated by walkthrough cleanup or recovery; preserve an incomplete one and offer inspection
  or the explicitly chosen fallback.
- **Continue this run's completed setup.** After successful selection or creation, installation, and `sdk-version: PASS` from installed
  preflight, record the setup evidence in `traigent-runs/run-plan.md` before any credential wait:
  the route taken (`existing-project`, `new-project`, or `throwaway`) and the environment's absolute path,
  its interpreter and Python version, `sys.prefix`, installed top-level versions, the requirements
  file's SHA-256, and the creation/install/preflight results. On a matching unfinished run, including
  a stage-5 wait for a missing credential, treat that evidence as a hint and independently verify
  it before continuing. The resolved environment must still be the one the record names, on the
  recorded route, and its named interpreter must report that environment as `sys.prefix` and the
  recorded supported Python version. Read installed versions through that interpreter's
  `importlib.metadata`; they must match the recorded versions, and on the throwaway route the
  unchanged `assets/requirements-first-run.txt` too.
  Re-run installed preflight without `--defer-missing-sdk` and require `sdk-version: PASS`; other
  failed records retain their own remedies. Only a verified completed setup continues
  at the remaining free checks or credential handoff: do not recreate the environment or repeat
  installation. A finished or historical record, missing creation/completion evidence, path or pin
  drift, or a failed setup or environment verification keeps the preserve-and-stop rule above. This exception grants no
  provider, data-transfer, or paid authority; the resume approval rules still apply.
- Installation uses the trusted plan/apply helper above, which binds its destination to the
  verified environment without importing that environment's startup files. Every later command - installed preflight,
  calibration, the mock check, baseline, enhanced run, and held-out scoring - runs through that
  same interpreter.
- For either creation route, resolve its supported interpreter using Finding a supported interpreter
  above. Recheck that the chosen directory is wholly absent, including any dangling symlink, before
  running `"<resolved-python>" -I -S -B -m venv "<project root>/.venv"` for `new-project` or
  `"<resolved-python>" -I -S -B -m venv "<project root>/.venv-traigent"` for `throwaway`.
  Both target paths are absolute. Creation uses only the standard-library
  venv/ensurepip bootstrap; fetch no SDK packages or project dependencies during it. If the name
  became occupied, preserve it and return to the path choice instead of running venv over it.
  Isolation also applies to creation, so a project module named `venv` or a startup hook cannot shadow the
  standard-library bootstrap. Omit `-I -S` from the chosen environment's post-install SDK check so
  that check measures its installed packages.
- Keep dependency installation as its own action class. For `existing-project`, the resolved card's
  yes authorizes what the version guard allows; for `new-project`, the combined preview's yes
  authorizes the stated pins and their declared dependencies. On the explicitly selected throwaway
  route, the announced install proceeds without another approval, from the exact packages
  and versions recorded for the top-level requirements plus their package-declared dependencies.
  Either way it is a package-artifact-only fetch/install with no provider or Traigent calls,
  private-data transfer, or user/project code execution. Prefer wheels; stop if fulfilling it
  requires source builds, additional undeclared top-level packages, or code execution. **That stop is category 2 of the standing rule: an action this guide will not
  take on their machine.** A source build runs the package's own setup code on their computer,
  which is not a check we declined but a thing we refuse to do to them - so it owes them a route
  rather than a number. Name the package and preserve the named incomplete environment. To
  continue this guided run, recommend a supported interpreter and platform with published wheels;
  recreating the incomplete throwaway environment still requires the user's explicit request under
  the preserve-and-stop rule above. Installing the package themselves is an alternative for a
  separate, user-managed workflow outside this guide; installing elsewhere does not repair this
  run's environment or supply its missing setup evidence. Nothing is deducted for it and no claim
  is bounded by it. A user or environment install-approval policy still takes precedence.
- Leave the project's own dependency declarations unchanged. Choosing the environment's version
  guard owns what is installed; dependency installation does not authorize importing or executing
  user/project modules.
- After every applicable free component, capability, and safe mock check, select the credential
  handoff file: a local file the user explicitly identified for this run, or otherwise the
  target-project `.env`. Verify its owner-only mode, check only key presence, and do not copy or
  move its values into another file or ask the user to enter an already available key again.
  Preserve existing values, comments, unrelated keys, blank alternate-provider entries, and any
  Traigent key already present; add only the genuinely missing selected-provider entry and, where
  The copied-actor route's route A was taken, that route's target name with the copied file's
  absolute path. Before
  opening it, require mode `0600` on POSIX. Resolve the selected handoff file relative to its Git
  worktree as `<credential-file-relative-path>`. Root `.env` uses
  `git -C "<credential-file-worktree>" ls-files --error-unmatch -- .env`: exit 0 means tracked
  and must stop; continue only on exit 1 with no match, and stop on any other status. Preserve an
  effective `/.env` rule and require `check-ignore -q -- .env`; stop before secret entry if the
  effective-ignore check fails. Otherwise run
  `git -C "<credential-file-worktree>" ls-files --error-unmatch -- "<credential-file-relative-path>"`.
  Exit 0 means tracked and must stop; continue only on exit 1 with no match, and stop on any other
  status. Preserve that worktree's `.gitignore` while ensuring it has an effective ignore rule for
  that exact relative path, then require
  `git -C "<credential-file-worktree>" check-ignore -q -- "<credential-file-relative-path>"` to succeed.
  Stop before secret entry if the effective-ignore check fails, and repair the ignore rules. Outside Git, do not create
  `.gitignore`. After these checks, announce and set the selected owner-controlled file to mode
  `0600` on POSIX before opening it or adding a key. If ownership or filesystem permissions prevent
  that, preserve it and explain the required owner action. A blank-file permission warning can
  wait for this handoff; a populated-file permission failure must be resolved before secret use.
  Stop once only when a key is truly missing. Add or request the Traigent key only
  after the local baseline checkpoint.
- Check presence only; never inspect, paste, or print secret values.
- Hand the file off unambiguously. In a graphical session, launch the opener detached and
  non-blocking: pass the absolute `.env` path as one safely quoted argument, redirect stdin,
  stdout, and stderr away from the assistant's pipes, and start it in the background. On POSIX,
  the `xdg-open` or `open` launch must end with `</dev/null >/dev/null 2>&1 &`; on Windows
  PowerShell, use `Start-Process`. Do not wait for the editor process or interpret its continued
  lifetime as failure; print the absolute path immediately and stop for the user. In a headless
  session, or when no graphical handler is available, skip the opener and print the absolute path
  as the fallback. Name the target line by the variable it sets - whichever of the chosen route's
  names the customer holds, and no line at all for a route that signs through its own cloud
  credential chain; at the later portal gate, name `TRAIGENT_API_KEY=` separately. That gate runs
  this same handoff a second time, on the same file, by these same two rungs - so a headless
  session prints the path there too and opens nothing.
- When a readiness command is asked to write a report file, verify that the file exists after the
  command returns. Some tooling still prints the score to stdout even when `--report` is supplied,
  so stdout is evidence of the score, not proof that the requested file was written.
- The documented SDK/service contract says connected runs send configuration keys and values,
  numeric measures, run state, and content-free metadata to the Traigent backend. Apart from
  content placed in a tuned configuration or observability content the project explicitly records,
  result metadata excludes prompts/inputs, dataset contents and expected outputs, and model
  responses. The pinned SDK test follows the guide's final trial-result serializer: raw
  `example_results` input, expected output, and model output do not reach its submitted object;
  the configuration label, numeric score, stable example ID, and numeric measure do. Session
  creation sends the configured space, dataset size/name, and function identifier: keep those
  values content-free and disclose them in approval. A connected request uses the Traigent API key
  to authenticate; it is not a telemetry field or guide artifact, but do not say credentials are
  'not transmitted'. This guide neither inspects network packets nor proves every optional SDK
  feature follows that path; stop if observed runtime behavior contradicts the contract. **That
  stop is category 3: a broken instrument.** Further calls would continue the observed contract
  breach, so stop them, say that it is ours, and name the SPECIFIC contract observed to be breached and
  what it actually affects - a payload or privacy contradiction does not by itself make every number
  meaningless, and claiming it does overstates in the other direction. Report spend as the evidence
  has it: preserve and report any charges already observed and any calls marked untracked, and say
  nothing was spent only where the evidence establishes no billable call happened. A contradiction
  seen during or after a paid call does not establish that.
  Describe the documented backend-payload contract, not independently audited network traffic.
- Treat backend transmission and local persistence as separate boundaries. SDK 0.27.0 writes
  per-example `query`, `response`, and `expected` text to local optimization logs by default. In
  the first-run wrapper, set `TRAIGENT_LOG_EXAMPLE_CONTENT=false` in the process before importing
  Traigent; this retains example ids and metrics while writing those content fields as `null`.
  Keep assistant-created logs beneath ignored `traigent-runs/`; honor and name a preserved
  project-defined results folder. Do not re-enable example-content logging unless the user asks
  after being told the local path, retained content, and deletion responsibility.
- A selected direct LLM provider still receives whatever content the agent normally sends in
  model calls.
- With OpenRouter, OpenRouter receives the request as the gateway and the selected upstream
  inference provider may also receive prompts, examples, and outputs. Automatic routing and
  fallbacks can change that upstream recipient.
- Encode prompt variants as short labels mapped to the text inside the agent function; never put raw
  prompt text as configuration-space values. Configuration choices are synced to Traigent's
  optimizer, so labels keep the actual prompts on the machine.

Ask before any private content leaves the machine, even when the provider key already exists.

Before a Traigent key request, link current [pricing](https://portal.traigent.ai/pricing),
[terms](https://portal.traigent.ai/terms), and [privacy](https://portal.traigent.ai/privacy). Do
not copy their prices or claims. State what the documented telemetry contract above says a
connected run sends and what it excludes - the documented contract, not a packet audit; the contract
is what the user is entitled to before deciding. Say that and no more. This guide does not carry
Traigent's training-use policy and makes no claim about it either way. Point the user to the
linked terms and privacy pages instead; they decide with those in front of them before pasting
the key.

At the secret-entry gate, show only the URL needed for the selected service:

- Traigent registration, only once the user already has their access code:
  `https://portal.traigent.ai/register`
- Traigent API keys: `https://portal.traigent.ai/management/api-keys`
- OpenRouter keys: `https://openrouter.ai/keys`
- OpenAI keys: `https://platform.openai.com/api-keys`
- Anthropic keys: `https://console.anthropic.com/settings/keys`

These account/key links are necessary actions, not educational detours. Do not show every provider
link; show only the selected provider and Traigent when each key becomes necessary.

A first-time user reaches that key page one way. They start at `https://traigent.ai` and submit their
email address, and Traigent sends a six-digit confirmation code that proves the mailbox and expires
within minutes. Once they enter it, a second email arrives carrying a single-use access code, valid
for 10 days, that authorizes one portal registration. The registration link in that same email is
deliberately plain and carries no credential, so the code is typed into the page rather than
clicked through. When the user completes portal registration the code is spent, the account's
portal access period starts, and they land in the portal. Their address is already confirmed by
then, so registration does not ask for a second confirmation.

The key is then created, not handed over. Two places create one: the key control in the portal's
top bar, which issues a key in a click or two and is highlighted on a first visit, and
`https://portal.traigent.ai/management/api-keys`, which offers more options. Name the top-bar
control first; it is the shorter path. Either way the key is shown once and cannot be read back, so
say "save it now" while it is on screen rather than afterwards.

Do not assume the user walked the whole path. Getting the second email and registering are separate
acts, and many people read the email and stop. Establish where they actually are before naming a
destination:

- **Already registered, key in hand** - they only need to paste it.
- **Already registered, no key in hand** - registering is not the same as holding a key. The key is
  created in the portal, not issued by registering, and it is shown once, so anyone who skipped that
  step or did not save the value creates a fresh one - the top-bar key control, or
  `https://portal.traigent.ai/management/api-keys`. Say the write-scope rule below at that moment.
- **Not registered, holding an access code still inside its 10 days** - walk the whole remaining
  path rather than naming one destination: open the second Traigent email for the access code,
  register at `https://portal.traigent.ai/register` (given as a clickable link) using that code,
  and then, once in the portal, create a full-access key from the top-bar key control and save it
  as it is shown. Only then return here to paste it.
- **Not registered, with no usable access code** - they never started, they are still waiting on
  one of the two emails, or their code is older than 10 days. All three resolve the same way: send
  them to `https://traigent.ai` as a clickable link. An expired code cannot be revived, and waiting
  will not deliver one that was never requested.

Those four are exclusive on what the user holds, not on how long ago: a run later refused for
account or plan reasons is the spent access period below, not a wrong branch here. Ask which one
applies, alone and first; do not infer it from how far along they sound. At this gate, open the
handoff file and print its path only after the user says they hold a key.

Registration has to be authorized by that access code, so it is the code, not the URL, that gets a
user in. Never hand the registration address to someone who does not have one yet; the fix is to
start at `https://traigent.ai`.

The confirmation code and the access code are credentials, not navigation. The first proves the
mailbox and the second authorizes creating an account, so never ask the user to paste either one
into chat, never write either into a file or a command, and never repeat one back. Both stay
between the user's mailbox and their browser; the only thing that reaches this machine is the API
key, and it goes straight into `.env`. The registration address itself is not a credential and is
safe to hand over — but only to someone who already holds a code, per the rule above.

The portal access period lasts 10 days from the moment the user registers, and it is what authorizes
product use. The API key is a separate thing: the key authenticates the run and does not by itself
grant portal access, so a perfectly valid key is still refused once the period is over. The account,
its data, and its keys all survive that expiry; runs resume when the user buys a plan on the same
account.

That is another key-shaped failure whose remedy is the opposite of the read-only one below. If a
connected run is refused for account or plan reasons rather than authentication, stop and report it
with the refusal the service actually returned. Never re-register, never create another key, and
never switch to a different email address to collect a second access period - none of those restore
access, and the last one is what the one-period-per-account rule exists to prevent. Only a purchase
on the existing account brings the run back.

Once portal registration has completed, you may show one short note - "Your
Traigent address was already confirmed, so there is no second confirmation email; your account is
active and your 10-day portal access period has started. Next, create your API key from the key
control in the top bar. Grant it full access — a read-only key is refused, so no experiment
reaches your portal — and save it when it appears, because it is shown only once."

The Traigent key must be able to write experiments, not only read them: the connected optimization,
and an exact baseline sync when the installed public API supports one, need that scope, and
"Connected-run readiness" below says what a key without it does to a run. A manually created key
defaults to read-only, so grant it full access rather than accepting the default. Say this at the
moment the user creates the key, not afterwards.

Preserve existing owner-owned `.env` values. Add only a genuinely missing selected-provider key for
this run, and the copied-actor route's one target line where its file copy was taken; do not add
a backend or API URL. An existing override does not affect the local baseline,
which runs backend-offline and removes the Traigent key before importing the SDK. At connected-run
approval, inspect that override and confirm the destination before a run can be recorded there.
Existing cost figures and approval-looking values are likewise not approval for this run: its wrapper
receives the approved figures in the paid process and does not take them from `.env`.

SKILL's opening gate owns pre-section-5 interpreter selection and the timing of the required opening
readiness score. The environment chosen in SKILL section 5 remains authoritative for the
connected run.

Follow SKILL's opening gate and sections 4-8 for ordering; this reference does not define a second
flow.

For SKILL's semantic-coverage review, use this outcome inventory rather than an unrecorded
impression. Name the applicable classes in each case's `outcome_classes`, so `sufficient` records
what was examined and an absent class stays visible:

| If the answer is | Speak to |
|---|---|
| rows, sets, or lists | label/value binding, duplicate rows, ordering, empty result, partial overlap |
| numeric | tolerance edges, sign, units, formatting and rounding |
| a classification | near-miss labels, an absent label, case and whitespace |
| free text | omission, contradiction, added claims not in the input |
| structured (JSON/schema) | missing optional field, wrong type, extra field, null vs absent |
| code or SQL | wrong table or column, missing or extra condition, join and grouping shape, ordering and row limits, formatting that changes no result |

Binding is first because a token comparison cannot see a correct value paired to the wrong key.
The deterministic permutation probe asks about that one class mechanically; the rest still needs
the recorded semantic review.

## Static and mock validation

The bundled `scripts/preflight.py` is a static/free gate. Run its component checks before
environment creation or dependency installation. It may read files and public package metadata,
but it must not:

- Import user modules.
- Execute the agent or evaluator.
- Make model/provider calls.
- Contact Traigent or consume optimization quota.

The static gate checks environment, package metadata, dataset structure/quality, model naming, and
safe configuration. It deliberately does not decide how the SDK normalizes rows, injects
configuration, binds agent inputs, or invokes evaluator callbacks. During the first
standard-library-only pass, omit optional model-pricing checks and interpret a missing SDK as a
deferred SDK finding, not as a failure of dataset-quality checks. Dataset heuristics use canonical
`input`/`output` fields unless the assistant explicitly selects other dot paths with
`--input-field` and `--expected-field` from the user's schema. Those choices configure only the
local quality view; they are not aliases, rewrites, or proof of SDK acceptance.

### Execution evaluators are out of scope

This first-run guide supports non-executing comparison evaluators. It does not ship, select, or
validate a sandbox for candidate/model output that is executed as code or SQL. Identify an execution
evaluator from its complete call path: a scorer enters that path when it executes or imports
candidate/model output as code, shells out with it, or submits it to a code or SQL engine. What ends
here is the evaluator that runs the answer, never the task that produced it: an agent whose answer
is code or SQL stays in scope, graded by the comparison `references/evaluation-and-dataset.md`
selects for it. A virtual environment, stripped credentials, an ordinary subprocess, a timeout, or
mock flags do not make that execution safe.

Comparison evaluators are calibrated on the customer's original, through an unchanged callable
adapter when needed. An LLM judge likewise calibrates the original; its provider calls remain
behind the approval gate in Approval and budgets. Neither uses `--calibrated-copy-of`: that route
belongs only to an evaluator that executes candidate code or SQL, under the scope boundary below.

When the resolved evaluator call path is an executing one, preserve the project, run only read-only
static inspection that does not import or execute it, record a `containment` warning, and **do not
calibrate the original evaluator here**. What this guide declines is running the customer's scorer
against the customer's engine on our initiative. It is not their onboarding.

**The run continues, on full disclosure.** Under the standing rule at the top of this file, tell them
in their own words, and do not soften any of it:

- **what was not checked** - their evaluator, against their engine;
- **that the reason is our boundary, not their defect, and - where neither a complete readable
  result nor an observed failure reached the score - that we therefore do not know whether their
  evaluator works**: we declined the check, so nothing
  here established that it is sound and nothing here established that it is broken. Their query may
  be wrong, their column types may not match, their cells may be null; this run has not looked. No
  step on their original target would change that; the copied-actor route below can measure a copy
  where its conditions hold. That is a fact about the guide rather than about them.
  **Never say there is nothing for them to fix** - that says we looked, and we did not. Where the
  project supplied a complete passing result, say instead that the supplied measurement is being
  counted: the scoring command read the result and did not observe its production. Without an observed failure,
  incomplete or unreadable evidence establishes neither success nor failure. An observed failure
  and a timeout follow their own card findings and remedies. Keep the scope tight in the other direction too: an evaluator rewritten later to
  compare rather than execute is a different evaluator, out of this gate altogether, so "no change
  of yours could ever matter" is false as well;
- **what proceeding concretely means** - during the paid run the *model* writes the statements and
  their evaluator executes them against whatever it is configured to reach, many times over. The
  statements are generated, not theirs, so their trust in their own code is not the trust being
  asked for.

One optional question follows from it - **does the evaluator connect read-only?** - and that is the
whole safety story in a line: a read-only engine refuses a destructive statement by itself, so the
hazard is gone without any containment this guide would have to own. It is not asked here. The
pre-spend approval card below is its one home, because the answer bears on the moment money moves
and on nothing before it, and an optional question asked twice is a question that reads as a stop.
Record the answer there. **Silence proceeds**, and a `no` proceeds too: the disclosure above has
already done its work.

A separate manual containment design and review remains available outside this guide. It must
decide the execution boundary, mounted inputs, credentials, network, limits, cleanup, and SQL data
scope. The copied-actor route below is the one route this guide performs itself; a project may also
supply a result from its own measurement. Do not describe that manual work as available through this
guide, imply that a local subprocess fulfils it, or present it as something the customer must
complete before their first run.

Two moments sit behind that stop and only one of them is about the model's output, so each is
refused on its own reason rather than both on the stronger-sounding one. Calibration runs the four
probes this guide's own matrix authors; there is no model-written statement at that step, and the
question "why can I check a SQL scorer on five known pairs when I can check any other scorer that
way?" has no good answer in terms of candidate output, because there is none. What calibration does
do is import the scorer and let it open its engine against whatever database it is configured for,
and that database is the project's. That is the reason calibration is refused outside the contained
route: the target is unbounded, which is a containment question this guide declines to own rather
than a claim about where the statements came from. A trial is the other moment - there the model
writes the query and the scorer runs it - and this guide neither opens it nor stands in front of it:
it is the customer's own run against the customer's own engine, and the disclosure above is what
makes it a decision they took rather than one taken for them. What this guide will not do is
initiate that execution against the original target on its own account; that calibration stays
refused outside the copied-actor route below.

`scripts/calibrate_evaluator.py` now enforces this rule instead of relying on it being read. Before
it imports anything, it asks the same walk `preflight.py` reports through `evaluator-shape` of every
file the run would import - the scorer, and the module behind `--reply-transform`, which is loaded
and called in the same child on every probe and had never been looked at. Outside the copied-actor
route, a witness names its file and line and exits 2.

Read the direction of that check carefully, because it only goes one way. A witness establishes
that a file reaches an engine; finding none establishes nothing at all, since a walk of one file
cannot see an engine behind a helper module, a connection handed in with the row, or a name bound
while the process runs. A run this check does not stop is therefore a run it had no grounds to
stop, never a run it cleared, and nothing in the output offers it as an all-clear. Reading the
complete call path is still the instruction above, and it is still yours.

An in-process envelope is not a route to that evidence: bounding Python from inside the same
interpreter means bounding it against every extension module, every constructor and every native
handle it can reach, and that surface has no edge. A boundary the operating system enforces is a
different proposition, and it is one this guide deliberately does not own. The manual containment
design and review remains work a project can commission for itself, on its own time, and never a
precondition of its first run. The copied-actor route below bounds the target instead of the
process. A project may also measure its own evaluator and supply the result; without a result from
any of those routes, its calibration evidence remains uncollected.

On the original target, that customer's card is a consequence of this decision rather than of
their project. **The check is one this guide declines to PERFORM, and never one the customer is
forbidden to make.** A project's complete passing result earns ordinary calibration credit; an
observed failure still convicts. This guide takes that measurement only through the copied-actor
route below. Where no result was supplied, the check earns nothing. Without an observed failure
or timeout, a supplied incomplete or unreadable result also stays unestablished: calibration and probe spread receive no measured
credit. In both cases those declined checks leave the denominator rather than deducting points.
Observed failures and timeouts keep their own findings and remedies under
`evaluation-and-dataset.md`, instead of the refusal cap. Otherwise `readiness.py` raises
`evaluator-calibration-refused`, which **does not block** and carries the execution disclosure.
The pre-spend disclosure remains unconditional under Approval and budgets below, whatever finding
the readiness card carries.

For all these refusal states, **whether the refusal bounds the CLAIM depends on what preflight's
walk found**. Where the walk established the engine, the boundary is demonstrably ours: nothing is
bounded either. Where this run holds only the declaration, the claim is held at 45: the declaration supplies no measurement of grading correctness. Without complete
calibration, renormalization can raise a lower overall within that bound; it is not calibration credit.
The card carries the disclosure this section makes. It does not put the question: that happens
once, at the pre-spend approval, for the reason given above.
The card says which case a run
is in. The REFUSAL follows from nothing their evaluator did: its reason is the unbounded target
above. What their evaluator did still shows on the card where a result reached the score - a passing
one is counted and a failing one convicts - and the two are not in tension, because the refusal is
about the check we did not make and the pillar is about the measurement somebody did. The card gives
them no errand for the declined check: the unmade check is ours, so the refusal declaration alone
lifts no ceiling. That is a statement about THIS RUN, not about the containment review
above, which stays available to a project that wants the evidence for its own reasons - as does
measuring their own evaluator themselves, which this run will read.

### The copied-actor route

One contained route to the calibration evidence exists inside this guide, and the refusal above
stays everywhere it does not apply. What the refusal argues is that the target is unbounded. A
target that is bounded - a file copy this run makes, or one the customer bounds - is a different
proposition, and a copy of the actor pointed at it is one
this run can calibrate without opening the connection their original opens. Offer it where every
step below can be made honest; where one cannot, say which, and keep the disclosure route.

1. **Copy the evaluator - the actor, never the data as rows.** Copy the evaluator file into
   `traigent-runs/calibration/` inside the customer's project. Never edit or move their original;
   the copy is walkthrough material under the ignored run directory, like everything else the run
   writes. The reduced dataset and config space the walkthrough already builds stay where they are,
   and this route never changes the customer's agent, dataset, or evaluator in place. Route A in
   step 3 copies a database *file* as the copy's target; that file is never opened as data.
2. **Locate the connection target statically, in the copy.** The one place is the target argument
   of the engine's constructor call - `sqlite3.connect(...)`, `psycopg2.connect(...)`,
   `create_engine(...)`, `duckdb.connect(...)` and their kin - whether it holds a literal or an
   expression. An original whose target arrives some other way - a config-file key, a `dotenv`
   read, a connection handed in from a helper - has no such argument to replace and cannot take
   the route; it is refused under step 5. The run must be able to name that one place - file and
   line.
3. **Ask the customer for a safe target - one question, lettered, and this is its wording.** What
   the located argument holds decides the routes. A **local database file** - a literal or an
   expression that resolves to a path on disk, as `sqlite3.connect("<file>")` and
   `duckdb.connect("<file>")` take, resolved to an absolute path with links followed - `realpath`
   or the chosen interpreter's `os.path.realpath` for the path; `stat -L` (`-c %s` on Linux,
   `-f %z` on macOS) for each size, never `ls`, which reports a link's own size - lying inside the
   resolved project root, where the file exists and it and the sidecars beside the resolved file
   (`-wal`, `-shm`, `-journal`; DuckDB's `.wal`) together measure under 256 MB - the size a copy
   takes in seconds on any disk the project sits on, and a bound a first run may spend of the
   customer's disk without asking - earns route A: a copy this run makes itself, with a plain
   shell copy (`cp`) of the whole file and its sidecars into `traigent-runs/calibration/`, byte
   for byte, never opened, never read row by row, never printed. A copy costs seconds and no
   tokens; reading the database would cost both and put the customer's rows in this conversation.
   A `-shm` or `-journal` sidecar means a process may hold the file open: say so, and take the
   copy only once the customer confirms nothing is writing it, since a copy taken under a writer
   can be torn. After the copy, open the run's own copy - never the customer's file - once, for
   SQLite's integrity check, through the chosen interpreter's stdlib so no CLI is needed:
   `"<chosen interpreter>" -I -S -B -c 'import sqlite3, sys; print(*[r[0] for r in
   sqlite3.connect(sys.argv[1]).execute("PRAGMA integrity_check")], sep="\n")' "<copy>"`. It
   answers `ok` for a sound file and otherwise describes the damage by page, table, index and row
   number - names and counts, never a stored value - or refuses to open it at all. Treat anything
   but `ok` as a torn copy: take it again once nothing writes the file, or, where a second copy
   is also torn, re-put the question without route A, saying the copy could not be verified, so
   the pasted target is what they choose next. A torn SQLite copy is never calibrated, so on that
   engine a route-A failure is never the evaluator's. DuckDB offers no such check: there the
   customer's word that nothing writes the file is the whole guarantee, and a route-A calibration
   that fails on a DuckDB copy is reported as a copy this run could not verify, not as the
   evaluator's. A **server or unknown target** - anything else, a file outside the resolved
   project root, or a file over the bound - is never dumped, cloned, or guessed by this run, so
   the question drops route A, says why in one clause after `<what is there>` - `This run makes
   no copy of it: it lies outside your project root` or `it and its sidecars measure <size>, over
   the 256 MB a first run copies unasked` - and letters the other two from A, the pasted target
   marked recommended.

   `Your evaluator sets its connection target at <copy path>:<line> (<what is there>). This run can calibrate a copy of it against a target that is not the one your original uses. A. This run copies that database file (<absolute path>, <size> with its sidecars), byte for byte, into traigent-runs/calibration/ and calibrates the evaluator copy against the file copy - your file and evaluator untouched, no row read (recommended). B. Paste a read-only connection or a duplicate you made with a proper tool into <.env path> under <NAME> - there, never here in chat - and reply B. C. Skip the calibration; the run continues on the disclosure above.`

   `<NAME>` is a name this run states, such as `TRAIGENT_CALIBRATION_TARGET`; `<.env path>` is the
   owner-only `.env` the Setup sequence's step 6 handoff selects, which is why this calibration
   runs at that sequence's step 7, after the handoff. On route A this run writes the copied file's
   absolute path under `<NAME>` into that `.env` itself - the child runs from
   `traigent-runs/calibration/`, so a project-relative path opens nothing and fails as if the
   evaluator had - and the gate below reads it exactly as it reads a pasted one. Never make a duplicate any other way, never read rows to build one, never guess a
   target. The last route and silence take the disclosure route above.
4. **Repoint only that one place**, then calibrate the copy through the same gate, which hands the
   child that one value and nothing else: `scripts/calibrate_evaluator.py --calibrated-copy-of
   <original path> --target-name <NAME> --target-env-file <.env path>`. The rule the gate proves:
   the copy is the original with exactly one change - the engine's target argument becomes
   `os.environ["<NAME>"]` (plus a plain `import os` where the original lacks it) - and the tool
   refuses any other difference, naming where it found one. The gate admits the engine witnesses
   it would otherwise refuse and records them as admitted rather than clearing them. Because the
   copy may then hold only what the original holds, the rest of what it refuses bounds the
   original: a second binding of `os` or `environ`; a reference to the engine's constructor that
   is not the one call, or more than one engine; a settings reader (`dotenv`,
   `pydantic_settings`, `decouple`, `environs`, `dynaconf`, `envparse`, `starlette.config`,
   `django.conf`), each of which reaches their own `.env` or settings; a side door to the
   environment, a file, or code - `getattr` on a module, `sys.modules`, `vars`, `open`,
   `read_text`, `socket`, `builtins`, `pickle`, `marshal`, `exec`/`eval`/`compile` in any
   spelling; any other environment read; a process; and any relative or local import - the walk
   reads the scorer file and nothing it imports, while a package under `site-packages` is not
   local. The child is handed `<NAME>` alone: every other name that `.env` defines is stripped
   from it, so the value they paste must be a complete DSN - libpq fills an omitted host, user
   or password from `~/.pgpass` and `PG*` defaults, which is their original target by another
   road. On POSIX the `.env` must be readable by its owner alone; on Windows, which has no such
   mode, the gate does not check it. Record in `traigent-runs/run-plan.md` the original path,
   the copy path, the located line, what was changed, and the target's *name* - never its value.
   Any run-log event follows The run log's event and detail contract below; that shareable event
   does not carry this local provenance. Code already present in the customer's original is outside
   this route's threat model: this gate checks the copy and its supplied target, not a sandbox for
   the original program. On this route the tool withholds worker diagnostics, including driver
   errors that may expose target components, and supplies a local-inspection remedy. Numeric
   calibration evidence remains available; a failure still fails and never earns credit.
5. **Refuse the route, keep the disclosure**, and say which of these applied: the target cannot be
   located at exactly one place in the copy (no constructor argument to replace, or more than
   one - a connection handed in from a helper module is set somewhere the copy does not show); the
   evaluator shells out or executes arbitrary code rather than submitting SQL to an engine (a
   read-only target bounds nothing about `subprocess` or `exec`); or it opens more than one
   engine. Your read is the first pass and decides whether to ask; the gate's refusal is the
   proof, and it refuses every one of these shapes itself - a copy whose one change is anywhere
   but the constructor's target argument does not run.
6. **The result is evidence like any other calibration payload.** Use component-creation.md's
   Opening readiness procedure for the result and the original evaluator's scope declaration.
   Calibration of a copy does not remove the original evaluator's execution disclosure or establish
   what its target reaches. A passing payload credits and a failing one convicts, exactly as on any
   other shape. The card records the payload's copied-route declaration in words that fit either
   route - "against a target that is not the one your original uses"; the run's own evidence may
   say "calibrated a copy of your evaluator against the target you supplied as read-only or a
   duplicate" - or, on route A, "against a copy of your database file this run made" - only when
   that calibration completed. A supplied target's read-only or duplicate property remains the
   customer's declaration, not something the scoring command verified; a file copy this run made
   is its own, and a copy the engine cannot open fails the calibration rather than passing it.

### A replay that changes the customer's world asks first

The stop above is about an engine. An evaluator that replays a workflow reaches none: it calls the
customer's own functions, which is ordinary code by every signal the walk reads, so the gate is
silent and calibration runs it - four probes, four executions, four sets of whatever those functions
do - before the customer has approved anything. Their first chance to object comes after the thing
they might have objected to.

Widening the walk is not the answer and is refused here rather than left to be tried: no static
signal separates a function that appends to a log from one that sends an email, so "calls any
project function" would refuse most honest evaluators. What decides it is what the effect DOES, read
by the assistant from the call path it has already inspected.

| the replayed workflow | before calibration |
| --- | --- |
| writes a record, sends a mail, calls a paid or outward-facing API, changes state anywhere | **ask** |
| retrieves, reads, searches, embeds - changes nothing | do not ask |

If it changes nothing there is nothing to consent to, and an approval step that fires on read-only
retrieval is the false-refusal problem that made the wider walk unacceptable. The question is only
worth asking where the answer could be no.

**And the ask names what will actually run** - the functions, the database calls and the tools the
replay reaches, from the path already read - not "may I run your evaluator". A customer approving a
category has not been asked anything they can weigh. It is one stop, before calibration, and a `no`
routes to the manual containment design above rather than to a quieter version of the same
execution.

### Deterministic calibration and mock plumbing

Deterministic calibration is a separate execution gate and always requires a recorded `sufficient`
evidence-backed semantic-coverage verdict. Before every calibration this stage performs, run only a
non-executing evaluator whose complete call path is local-only, side-effect-free, and
standard-library-only. The same three words bind anything else this stage imports, and a reply
transform is the one other thing it does: reaching that function executes its module's top level,
which for an agent file is commonly a provider client. A non-executing evaluator that needs a
declared local dependency waits until that dependency is installed, and so does a transform whose
module does - the flag waits with it rather than pulling an install into this stage. That deferred
calibration is outside these three words and Environment and privacy's Setup sequence step 5 runs it: its path carries
the installed dependency by construction, so the inspection that declared it is what binds it
there. An execution evaluator had its evaluator check skipped at the scope gate above and the run
continued; nothing is owed here either, unless the copied-actor route was taken, whose calibration
the Setup sequence's step 7 runs once the target is in place. Run non-executing calibration
before creating `.env` or requesting a provider key. A generic outside-review wait is not a gate;
pause only when one unresolved product-grading ambiguity would materially change correctness or
ranking. Do not execute an LLM judge or an uncertain or external evaluator without explicit
approval in the stage where it runs, covering recipients, data, calls, runtime, and spend.

A Traigent mock run is a separate plumbing check:

- Use a fresh process.
- Set `TRAIGENT_OFFLINE_MODE=true` and `LITELLM_LOCAL_MODEL_COST_MAP=true` before imports. Traigent
  offline mode does not by itself suppress LiteLLM's import-time remote pricing-map fetch; use both
  in every generated mock wrapper and every documented free mock invocation.
- Enable the pinned SDK's mock responses in that process before importing or rehearsing the
  inspected agent integration; the two flags above do not mock model calls:

  ```python
  from traigent.testing import enable_mock_mode_for_quickstart

  enable_mock_mode_for_quickstart()
  ```

  Use a separate free-check entry point, not either paid-phase runner. Keep both paid runners'
  inherited-mock refusal intact and never supply pretend spend approval to launch this check.
  If the SDK refuses activation, use the static-only or approved-probe route below.
- Confirm the entire call path fits the pinned SDK's interception boundary: LiteLLM completion
  calls inside a Traigent optimized/evaluated run after its interceptor is installed, or LangChain
  calls through an installed Traigent framework integration. Direct calls before interception,
  raw provider SDKs, subprocesses, HTTP services, tools, and custom judges are not covered merely
  because mock mode is active. Agent logic and evaluators still execute normally. The installed
  SDK's interception of the actual path must be established rather than treating a framework name
  as proof.
- Treat proxy variables, removed keys, and mock flags as defense in depth, not as a sandbox or
  proof that an invoked path is local-only.
- If any path cannot be proven free, do not call it a free dry-run. Ask approval for the smallest
  real probe or use static validation only.
- If mock validation says trial settings are not consumed, return to **SKILL.md section 4**'s
  repair/continue/pause choice. Revalidate only after the user chooses that repair's scope; do not
  open a credential file while optimization remains phantom. A retrieval, tool, or multi-call
  control needs separately contained tracing that proves its own execution path before a later
  workflow can treat it as a paid search dimension.
- Exit the process after mock validation. Mock state has no reliable public undo.

Uniform mock scores can be expected for output-based evaluators. Plumbing success means trials
execute without failures; it does not mean mock accuracy is meaningful.

Mock results may contain a positive estimated `total_cost`. That is pricing metadata, not evidence
that a provider billed the account. Report charges only from trustworthy cost records for real
provider calls; SDK defaults and local token estimates are not provider observations.

The converse also holds: OpenRouter `:free`-suffixed model ids genuinely cost `$0`, so judge a real
run by its actual provider path, completed trials and meaningful outputs, with reported token usage
as corroboration when available. Neither a zero cost nor missing usage alone establishes a mock.

### Config-space document

`scripts/readiness.py --config-space` scores the agent pillar from the space this run actually
built. A file found before the current enhanced search, including one left by an earlier guided run,
is historical context only and never enters config-space scoring. A customer-authored file may guide
source inspection, but its values and `wired` list never enter `--agent-knobs`. Record provenance;
its existence, timestamp, hash, or non-empty `wired` list cannot prove current wiring. Omit either
file from opening and SKILL section-4 readiness. Those scores use the read of the agent's own source passed
as `--agent-knobs`, never the file.

The rule binds the run, not the invocation that reports. Omitting the document from the opening and
SKILL section-4 calls describes what those calls pass; a second call scoring the same file to see what the
number would have been reads as costless, and it is not: its output is evidence the moment it is
written down, and a figure sitting beside the real one gets quoted. So the document is not scored
in this run in any invocation, and no number derived from scoring one appears in the report, the
findings, or the bundle a reviewer is handed. Calling such a call internal is a claim about the
card and not about those documents. A run does not close on a second number, and it does not open
beside one either: it leaves no exploratory scoring at the opening gate.

A scoreable file means one thing: *this is the space the search that just completed received*.
The generated wrapper serializes the finalized space, removes any earlier file before the call, and
writes `traigent-runs/config-space.json` only after the search returns nonzero trials. Only that
current-run file enters closing readiness. A stopped, failed, or zero-trial search emits none, so
the agent pillar is scored from absent evidence and its 45 ceiling stays in force - the closing
score cannot exceed it.

The read's KNOBS half is deliberately not allowed to establish the space at the close, and this is
the only score in the run where it is left off. The opening read says what the agent makes
reachable; this score says what the search actually received, and they are different quantities.
Letting a read of the source stand in for a document the search never emitted would lift this
ceiling on exactly the runs it exists for - the ones that stopped, failed, or bought no trial.

Its BUILD half travels, and only where a config-space document decides the space beside it, but
remains unmeasured. A config space proves neither how the agent is built nor its source reader's
claims; dropping those observations would report four checks falling to unanswered between cards
while nothing about the agent changed. Where no document reaches the close, pass nothing: the knobs
half would establish a space the search never received, and the two halves arrive in one file.

`agent-no-varying-knobs` is advisory whenever a named agent's document and reading both fail to
reach the scorer, because the scorer cannot tell a document withheld before the search from one the
search failed to produce - both are the same absent input. So on a closing card after a stopped, failed, or
zero-trial search, `status: OK` describes only the evidence this cap was given, and is not a verdict
that the search succeeded. `recommended_action` reads `proceed` there only when nothing else blocks
and nothing else is asking: an asking cap carries its own remedy into that field, and so does an ask
that caps nothing, which arrives in `open_asks` rather than in `caps`. So `proceed` on this card is
the absence of every other finding rather than a
statement about this one, and a remedy standing beside an empty `caps` list is accounted for. Report that
search's outcome from the run itself - trials executed, spend, the error it stopped on - and never
let an advisory agent cap stand in for it. Whether a search that produced nothing may be retried or
paid for again is the approval question it always was, decided on that outcome, not on this score.

These are the only fields the scorer reads and the only keys it accepts: any other key is refused
by name (exit 2), listing the fields it may declare and naming the closest when there is one,
because it cannot be told from a misspelling of one - `max_trial` for `max_trials` is one
character, and it raised the band. A field that is
present but malformed is refused with a message naming it (exit 2), never
scored around - a document the scorer cannot read is not a document it may guess at. Refusal turns
on the *value*, not on how JSON spelled it: an empty list, a `null` and a `0` where an object
belongs are malformed, not absent, and are refused rather than read as an empty object; conversely
any value the documented type admits is accepted however it was written, so a document that scores
does not become an exit 2 because a writer emitted `12.0` instead of `12`.

Exit 3 from any bundled script is a different statement and must be routed differently: it
means the script itself failed, not that the user's material is wrong. Nothing was checked or
scored, so present no result and no band; say the check could not run, and never relay it as a
finding about their dataset, evaluator, or agent.

The table below is not a second description of the schema. `readiness.py` declares the field set,
each field's type, and the domain of every value inside it once, in `CONFIG_SPACE_FIELDS`, and both
the validator and this table are read from that declaration - `tests/test_skill_package.py` fails
when they disagree. So a field is either declared there and validated, or it is not a field.

| Field | Type | Required | What the scorer does with it |
|---|---|---|---|
| `knobs` | object: knob name to a non-empty list of scalar candidate values | one of the two | the preferred spelling; a non-empty `knobs` wins over `configuration_space`. A document declaring neither key says nothing about the space and is refused; `{"knobs": {}}` declares an empty one and scores 0 under the cap. Every entry's value must be a list, and a knob written as a bare scalar is **refused** - dropping it would shrink the space silently and often *raise* the score. A list with nothing in it is refused for the same reason: a knob with no candidate values is not a narrower space, and scoring it printed a wired-knob count and a combination count the document itself contradicts |
| `configuration_space` | same shape | accepted alias | read only when `knobs` is absent or empty. Emit `knobs`; never both. Whichever key is present is type-checked, so a malformed alias cannot hide behind a well-formed preferred key |
| `max_trials` | positive integer | no | the search-space sub-score is read against it: the score follows how many distinct configurations the run will actually try, and is damped when the declared space is more than twenty times the cap. Omitting it costs a step - a document that does not declare a budget does not establish that the run will compare the whole space, so the sub-score is held one step below full credit exactly as an oversized space is. **Emit it.** Deleting the field can never buy full credit. Deleting it can still raise the score from below, where the budget is the smaller number: on one 12-configuration space, `max_trials: 2` scores 35 and `max_trials: 1` scores 0, against the 70 the field's absence earns. A budget of one is a real statement that the run compares nothing; silence measures nothing. Any integral number is read, however JSON spelled it: `12` and `12.0` are the same budget, and an integer of any size is read as itself. A fractional value, zero, a negative, a boolean, or a non-number is refused |
| `wired` | list of knob names | **yes - always emit it** | the names the agent actually consumes; only these are scored. Do not rely on omitting it or sending `[]`: a document that does not state what the agent consumes attests nothing, and the scorer treats that as nothing-to-search rather than as "all of them". Emitting the list is the whole point of the document. Every name must be a knob of the declared space - a misspelled one is **refused**, because it matches nothing, silently shrinks the scored set, and makes the card print a wired-knob count the document contradicts |
| `bounds` | object: knob name to `{"low": number, "high": number}`, low below high | no | per-knob override of the scorer's canonical numeric ranges; an entry missing `low` or `high`, carrying a non-numeric or non-finite edge (`"inf"` or `"nan"`, either of which would collapse a genuinely sweeping knob), naming a knob absent from the space, declaring a range with no width (`low` above or equal to `high`), or declaring one whose width is unmeasurable even though both edges are finite and ordered - overflowing to infinity (`low: -1e308, high: 1e308`) or underflowing the noise floor to zero (`low: 0.0, high: 5e-324`) - is refused. A zero-width or unmeasurable range breaks the noise floor and span a knob is measured against, so two nearly-identical values read as a full sweep, or a genuine sweep collapses to nothing to search. It sets the noise floor, span, and endpoint coverage - it does not add search values. A numeric string (`"5"`) is accepted for either edge |

Candidate values are scalars: a string, a number, a boolean, or `null`. The scorer deduplicates,
compares and counts them, so an object or an array inside a candidate list is refused rather than
reaching the comparison as an unhashable value, and a non-finite number (`Infinity`, `NaN`) is
refused rather than scored - a knob is measured against the span its values cover, and an infinite
or undefined span is not a sweep.

`prompt_policy` is another name for `prompt_style`, and a document declaring it is refused (exit 2)
naming the spelling the scorer knows. Nothing is renamed on the author's behalf: two spellings of
one search dimension count as two dimensions everywhere downstream, which doubles the reported size
of the space and pays twice for one knob, so the document is corrected rather than guessed at.

`agent-no-varying-knobs` clears as soon as one wired knob carries two effective values. What counts
as "effective" depends on whether the knob has a range at all:

- A numeric knob **with** a range - one of the scorer's canonical knobs (`temperature`, `top_p`,
  `retrieval_k`, and so on) or any knob given a `bounds` entry - needs two values
  separated by more than the noise floor: 0.05 for `temperature` and `top_p`, otherwise 2% of that
  range.
- A numeric knob with **no** canonical range and no `bounds` entry is scored on breadth alone. Any
  two distinct values clear the cap, however close together they are - `[1, 1.01]` counts. There is
  no range to measure a noise floor against, so nothing collapses them.
- A categorical or boolean knob needs two distinct values. Two is also where it scores FULL
  breadth, not half: for a categorical knob there is no knowable "how many values exist" to divide
  by - `thinking_shape` may have two shapes today and four next year - so a denominator invented
  here would only underprice an honest two-value comparison. `model` is the one exception and keeps
  a ladder, because there more choices genuinely is better: 3 or more scores 100, 2 scores 60.
- Any knob declared with exactly ONE value scores 10, whatever its type. It adds nothing to the
  search, so it earns almost nothing; it is not zero because pinning can be the right call made on
  purpose - `temperature: [0]` on a task that must be reproducible is a decision, not an omission.
  Several values that collapse into one is a different case and still scores 0: that author did not
  pin the knob, they tried to sweep it and the sweep does not exist.
- `seed` never counts, however many values it lists, because sweeping it measures run-to-run
  variance rather than quality.
- `max_tokens` never counts either, for the neighbouring reason: it is a resource limit, not a
  behaviour setting, so sweeping it measures whether the answer **fit**, not whether it was good.
  **Never introduce a cap the user did not already have, and never sweep one.** If their agent
  sets `max_tokens`, carry it through verbatim - it works in their daily life. If it sets none,
  send none: the generated wrapper sends no `max_tokens` at any tier, reasoning models included,
  and the provider default stands. **No floor is imposed and no value is refused** either - a user
  may cap it however they like, and reasoning headroom is not predictable, so a floor is a guess
  that breaks runs which would have been fine (`2048` is absurd when the answer is `a`, `b`, `c`
  or `d`).

  A cap of *ours* is worse than one of theirs because it spans two runs: a number that fits the
  baseline's medium model is one the enhanced run's stronger or reasoning model can exceed, so the
  truncation is introduced by this guide on a configuration the user never chose. Either way the
  provider returns `finish_reason == "length"`, and a cut-off answer scores 0 rather than low, so
  the model it happened to loses a comparison it may have won - detected, not predicted, by the
  wrapper's `require_untruncated_completion`.

  Where a bound is genuinely needed, **bound the clock or the trial count, never the tokens**: a
  time limit stops the work and leaves what finished intact, while a token limit corrupts the
  answer at the cut and then scores the corruption.

Three honesty rules govern the file:

- List under `wired` only the controls the agent call really consumes. The scorer checks that every
  wired name is a knob of the declared space, but whether the *agent* reads that knob is an author
  claim it **cannot verify**: it reads the document, never the agent code. Naming a knob the
  agent ignores - a config key read into a variable the prompt never uses, say - inflates the agent
  pillar by scoring a dimension the search cannot actually move. A knob that does not influence the
  agent code is not a real optimization variable. The generated wrapper therefore probes the claim
  where the scorer cannot: `probe_wiring` re-builds the provider request under each alternative
  value and returns one verdict per knob.

  State the probe's limits exactly, because they are narrow. Its exact claim is **request
  visibility, per model** - that each declared value produces a distinct request dict for every
  model and tuning input in the space - and never provider *effect*: only the run can show effect; the probe only rules out
  the dimension that could not have one. The verdict semantics live beside the code in
  `references/sdk-execution.md`: `partial` and
  `invisible` fail; indirect behavior is outside this first-run paid space.
- `bounds` is likewise self-declared and unverified. It changes the noise floor and the span a knob
  is measured against, so a narrow declared range can turn two nearly-identical values into a
  "varying" knob and clear `agent-no-varying-knobs` on bounds alone. Declare the range the knob
  genuinely has, not the one that scores well.
- Re-write the document whenever the space changes, and before any later score reads it. A stale
  document describes a search that never ran. Because a document from one search would otherwise
  survive the next one failing, the wrapper deletes it before each search rather than relying on
  the next write to replace it - staleness is removed by the run, not by the reader noticing.

The walkthrough's document uses the exact generated space owned by
`references/sdk-execution.md`, with temperature declared at its one task-selected fixed value
because the agent does consume it. A fixed knob scores 10 of 100 on breadth
rather than 0: declaring it says the author considered the knob and decided, which is worth a
little, and worth only a little because the search still gets one value:

The JSON below is the exact-output worked example, so its selected value is `0.0`.

```json
{
  "knobs": {
    "model": ["provider/current", "provider/alternative", "provider/strong"],
    "prompt_style": ["plain", "structured"],
    "thinking_shape": ["direct", "chain_of_thought"],
    "reflect": ["off", "on"],
    "temperature": [0.0]
  },
  "max_trials": 12,
  "wired": [
    "model", "temperature", "prompt_style", "thinking_shape", "reflect"
  ]
}
```

## Approval and budgets

Use two short, contextual approvals; do not ask the user to design budgets, retries, or timeouts.

Before the provider-paid baseline, show only its immediate scope:

- Scope and bounds: the smallest live provider/key check, any pre-baseline LLM-judge calibration,
  preserved baseline or generated twelve-configuration sweep, tuning rows and limitations,
  configurations, calls, metric, runtime, estimated spend, and one total walkthrough ceiling,
  defaulting to `$5.00`. Call it an execution stop target, not a billing guarantee.
- Recipients: baseline-data services; for OpenRouter, the gateway and allowed upstream/fallback routes.
- Execution evaluators: the scope gate in `Static and mock validation` above skips their evaluator
  check and the run continues, so this card DOES price them - and it carries the disclosure, because
  this bullet is unconditional and the moment money moves is the moment it matters. Say what was not
  checked, that it is our boundary rather than their defect, and what the paid run will have their
  evaluator do with model-written statements. The asking-cap bullet below owns the QUESTION and the
  answer given to it, which is a different thing from what was not checked. Both land on this same
  card, and this bullet is why the order cannot be relied on: the disclosure is unconditional, so it
  is stated whatever the connection answer turns out to be. An earlier draft made it conditional on
  the cap still asking, which would have let the safest answer buy the quietest card.

### Rendering and enforcing baseline approval

When this run filled a gap for the walkthrough, or an active cap asks rather than blocks, that same
approval also carries the pre-spend card in this reference: what the gap was and how it
was filled, absolute paths to what was written, the easiest and hardest rows, what the evaluation
method counts as correct, and the provenance this run assumed, stated rather than asked. It is
content on the approval that already stops, never a second pause, and the card ends on exactly one
lettered ask: the proceed-or-fix pair, whose proceed route is the spend approval. A standing
`seam_probe_advisory` rides that same approval whether or not the card does: what the evaluator
scored the answer as the author wrote it and in the shape the probe sent, and every string the
advisory recorded - which is one string, not two, where no reply step ran.

When the opening gate found Traigent already set up here, that approval carries it too, beside the
figure: what was found, and that this run charges for its own baseline and search whether or not
they have optimized here already. One line on the approval that already stops.

Immediately before the paid baseline, show a short run card with model ids, each varying knob and
its explicit values, one plain-language note per knob, and the total combination count. The
enhanced card waits until after the baseline checkpoint.

Put the baseline estimate, selected row count and ids, and **30-minute completion target** in the
money approval. Preflight's first-run count is only a proposal; it cannot know the selected rows.
This is an estimate, not a hard wall-clock guarantee. Size the baseline before it starts.

When the SDK exposes trustworthy live progress, report only those values; otherwise report only
observable phase milestones. Never invent progress or quietly drop validation. A timeout follows
Recovery in this reference.

If the estimate exceeds `$5.00` or 30 minutes, first recommend a smaller representative slice
while preserving meaningful difficulty coverage; the baseline grid is never reduced - a generated
one runs its twelve configurations and a preserved one runs as the user defined it. Proceed after
one explicit approval and keep it process-only. The limits and retry rules below apply.
Maintain its single
running total across every paid phase, stop before the next estimate exceeds the remainder, and
do not layer another retry loop. Launch every paid process with the three approved figures below, so what the user approved is what the code enforces; a phase missing any one of
them stops before spending rather than falling back to a limit nobody approved.

After the approved live provider probe, derive internal time bounds from observed latency and the
baseline work. If they no longer fit the approval, offer a smaller run or quote the additional
time/cost; do not ask the user to select implementation timeouts.

### The pre-spend approval card

The baseline is the first thing in this run that costs money, and the last moment at which changing
what that money is spent measuring against is free. So whenever this run generated or repaired the
dataset or the evaluation method, or an active cap asks rather than blocks, the baseline approval
above carries this card too. It adds no pause of its own - the approval already stops, and this is
part of what it stops with.

Each bullet carries its own condition, because the two triggers do not produce the same card. On the
asking-cap path the customer's own dataset and evaluation method are the material under discussion
and this run wrote nothing, so a bullet written for generated material describes a gap that does not
exist and points at a file that was never created.

- **The gap, and how it was filled** - where this run generated or repaired the dataset or the
  evaluation method. Name the condition in the user's own words - no examples were
  connected, the answer key was written by a model, no grading method existed - and then what this
  run put there instead. Both halves: "a dataset was created", without the gap it answers, reads as
  a feature rather than as a substitution for something they do not have. Where the dataset was
  topped up, add the ceiling its generated share now carries, with its number: the ask deliberately
  left the number out, and this is the first place the customer hears it. Where this run created and
  repaired nothing, drop the bullet; there is no gap of ours to name, and describing the customer's
  own material as one is the claim this card exists to avoid making.
- **Absolute paths** - one for each file this run actually wrote: the generated or repaired dataset
  when this run wrote or changed it, and the evaluation method when this run wrote one, each as a
  full path they can open in another window while they read this. A relative path is not openable
  from wherever their terminal happens to be. Two paths at most, not an inventory: every file this
  run wrote is listed at the close, and `references/evaluation-and-dataset.md` owns that list. These
  are here because they are what the decision below is about, so a run that wrote neither lists
  neither.
- **Two rows: the easiest and the hardest.** Not a random pair - the two that show the range, so the
  reader sees what both ends of this dataset look like. Quote each row's input and its expected
  answer from the file rather than describing them. When the rows carry no difficulty tags, pick the
  pair by the ladder in `references/evaluation-and-dataset.md` and name the rung it came from, so an
  unstratified pick is not read as a measured one.
- **What the evaluation method counts as correct.** One or two plain sentences: what it compares,
  what it accepts, what it rejects. This is the half a person can hold against their own idea of a
  right answer, and it is where a generated method most often misses - one that grades wording where
  the product cares about the number will rank every configuration on the wrong thing, and no later
  check in this run would catch that.
- **What an asking cap asked, and what was answered** - where one is active. A cap that asks has one
  home for its question, and some of them own a quoted one already: `dataset-unsound-expected-outputs`
  is put through "A `no` is never a silent edit" in `references/evaluation-and-dataset.md`, which
  SKILL section 4 routes it to by name, and it is settled there while a repair is still free. Restate
  the finding, the answer taken, and what proceeding on that answer means for the money about to be
  spent - do not put the question a second time in different words, with a different pair of exits.
  Where the cap's route owns no question of its own, this card is that one home and asks it here.
  `evaluator-calibration-refused` is one of those, and it is asked here and nowhere else: whether
  the evaluator connects read-only, and so which connection answer this spend is being approved on.
  The scope gate above raises the question and deliberately does not put it, because this is the
  moment the answer bears on. What was NOT checked is a different thing and is stated once, in the
  scope bullet above, which fires whether or not this cap is still asking.
- **Where we are.** `Stage 3/5 · Baseline`, so the choice arrives placed in the run rather than
  loose.
- **Proceed, or fix.** Two lettered routes with the recommendation on one of them, in the shape
  SKILL.md states for every named-route choice this run offers: `A.` proceed, marked recommended,
  and `B.` fix. Proceeding approves this material as the thing the run will be graded against;
  fixing returns to the repair route SKILL section 4 owns and re-runs its gate before anything is
  spent. Approving the spend is not approving the material, and silence is neither.

  The mark goes on proceeding for the reason `references/component-creation.md` gives for marking a
  route that continues, and it holds harder here: fixing needs no push, stays available at any time
  and costs nothing, while the run not happening is the outcome this walkthrough exists to avoid -
  and what is approved here is deliberately small, a bounded taste of the workflow at a priced
  ceiling rather than a full search. An unmarked pair is a menu, and a menu offered instead of a
  recommendation is no recommendation: a run that meets one supplies the default itself.

  The mark moves rather than lifting, on the same condition that reference states for choosing among
  routes that continue - mark the route that can produce the result being paid for. So where the
  card carries a `FIX BEFORE PAID RUN`, where any cap blocks, or where the run as scoped cannot
  answer the question it is being paid to answer, fixing is the route that can produce that result:
  `B.` carries the mark, `A.` proceed stays offered unmarked, and the sentence beside it names the
  finding that moved it. The mark is never withheld from the pair.

  The final reply-ready block below places this pair too.

An asking CAP is what this card exists to discharge, and discharging it means the customer meets its
remedy at the moment they are asked to pay - not that its question is put here a second time.
Bound, never block - the run is still worth making, and the question is what to settle before it
rather than instead of it.

An ask that caps nothing is deliberately NOT carried here, and the difference is a decision rather
than an omission. A ceiling standing on the score is a bounded claim the customer is being asked to
pay for, so it belongs at the moment of paying. An unread answer key bounds nothing: putting it here
invites a customer to stop and go and read a key nobody was asking them to read, when the run is
small, its spend is bounded by the ceiling on the approval below, and what it buys is seeing the
thing work end to end. It is carried
where the card is explained instead, in the order
`references/evaluation-and-dataset.md` sets out.

After showing the baseline result, give the connected stage a preview and approval:

- Search: added enhanced controls/combinations and why they fit the observed failures,
  the configuration ceiling below, approximate calls,
  how Traigent's managed search chooses trials while retaining baseline values, objective
  directions and weights, and the rule for recommending among tradeoffs.
- Held-out check: price the actual reserved rows after selecting one configuration on tuning
  scores, including a judge call per row when needed. If no independent rows remain, report that
  the check is unavailable and place no held-out calls. Include those calls in
  this same approval rather than asking again afterward, and add their known cost or conservative
  deduction to the single running total. The wrapper refuses the whole held-out pass rather than starting one the remaining
  cannot fund to the last row; say that here, because a pass that is refused returns no held-out
  score at all. `references/sdk-execution.md` owns which of this run's paid calls no permit covers -
  a judge's are among them, on every scored row of the search as well as these.
- Bounds and value: runtime, known cost, budget debit and remaining ceiling; provider/Traigent recipients,
  zero-LLM probe, portal history/direct links, and exclusions. Dataset/configuration insights remain
  conditional on verified run-scoped SDK artifacts.

The enhanced run card's trial line is a ceiling paired with the size of the space it is drawn from, because
at approval time the user is asking what the worst case is, and a range answers a question they did
not ask. State it in their words, reusing the card's own total combination count:

> Your agent has `<total combination count>` possible configurations.
> Traigent will test up to `<enhanced trial cap>` of them, choosing which ones as it goes rather
> than working through a fixed list.

Both numbers come from the approved space itself - the count this card already computed and the cap
this run passes as `max_trials` - never from a worked example in a reference, whose spaces are not
this agent's. Name this count in `configurations` rather than `trials`, and give it as a ceiling,
never as a range; `trials` remains the right word for a failed-trial count or an SDK field. When
the approved space's combination count cannot be computed - a preserved space whose values are not
enumerable, for instance - state the ceiling on its own rather than estimating or rounding a total.
Report actual coverage afterwards as `Tested <distinct configurations> of <total combination count>
configurations in <executed trials> trials`, omitting the total when unavailable.

Do not manufacture urgency. If baseline and evaluator show a measured quality, cost, or latency
opportunity, say `Recommended next: continue with Traigent optimization because <observed reason>.`
That observed reason is one reason among several and never the whole of the case, and a preview
resting on it alone has nothing left to say on a baseline that measured none. The workflow value remains on
a sound baseline: continuing is the only way the customer sees managed
selection run against their own agent, which a local fixed grid by definition does not show;
when independent rows are available, the held-out check reports on rows the configuration was
not chosen on - a finding about their own dataset that no other part of this run produces. Name those where no
measured opportunity exists, so the preview still carries a stated reason instead of an unmarked
pair. Neither may be written as an expected gain: they are what the run shows and what it tells
them, never what it will improve, and the no-lift wording below is unchanged by them.

What may fill `<observed reason>` is a finding a wider search has room to move. Rows that no
configuration solved is one, because more configurations is the thing that could solve them. A
statistical tie among the top configurations is not, and the frontier section below already says
why in the opposite direction: it names one as a bound on what this run may claim. At this sample
size a tie says the rows cannot separate the configurations already tried, and adding candidates
adds nothing to separate them with - resolution comes from rows, never from more things to rank.
Name it as a limit on what the result may claim, and where it is the binding one name it as the
limitation the `traigent-dataset-curate` handoff below addresses after the run. It is never a
reason to spend. When the dataset and evaluator are sound but the baseline showed no measured
quality headroom and, where cost was measured, no cost headroom, the bounded managed run stays the
marked route, on the workflow value above, and is offered as an optional no-lift-possible verification run. On that preview,
say that it is not expected to find a gain, that stopping is route `B` on the standard preview, and that
declining leaves the honest baseline-only result intact, and name the no-headroom finding beside
it as a limit on the claim and that same handoff's limitation, never as a route; the operating
contract in `SKILL.md` owns that bound. An invalid or non-discriminating dataset/evaluator has
already stopped before this preview and gets the evidenced repair instead. Never promise
improvement.

Every offered connected preview ends on its routes, in the shape SKILL.md states for every
named-route choice: lettered from `A`, exactly one marked, and each one answerable by replying. A
route this guide names and prices is a route the customer can take by replying.

Final reply-ready block, on both approval cards as to its position. Render it as its own block,
after the disclosure prose, with nothing following it: a reply form sitting in the tail of a long
paragraph is not an instruction. The route texts below are the connected preview's; the pre-spend
card renders its own `A.` proceed and `B.` fix in that same position. When telemetry is the gap,
use the continue/optional-repair routes under "Missing cost or usage telemetry" in this same block.

> **A. <action>** *(recommended - <reason>)*
> Reply `continue` and I will <next safe step>.
>
> **B. Stop here and keep the baseline result.**
> Reply `stop` and I will preserve the local result and report the run as baseline-only rather than
> as a completed Traigent optimization.
>
> Or reply with a smaller trial cap or a lower ceiling and I will re-price this same step.

Route `A` carries the reply-ready `Recommended next:` line above, whose reason is the observed
opportunity where the baseline measured one and otherwise the workflow value above; it
stays a direct evidence-based statement rather than a question. The last line is not a third route:
it answers how big rather than what to do, so it rides last and unnumbered exactly as `I have it`
does on the asks about material, and nothing follows it. Replying `continue` on an approval card
approves exactly what that card disclosed and priced - recipients, effects, bounds, and cost - and
nothing more.

The mark on `A` follows the pre-spend card's rule above, which
`references/component-creation.md` states in full and this file does not repeat, and its moving
conditions cannot hold at this preview: a dataset or evaluator that
fails the distinguishing check stopped before this card, as the paragraph above says. So the mark
stays on `A.`, the bounded managed run, including when `B.` offers optional telemetry repair.
Stopping is never the marked route.

Keep the default `$5.00` ceiling across both approvals. If a stage exceeds the remaining ceiling or
is materially long, recommend a smaller slice or, for the search, a lower trial cap; expand only if the user prefers.

The approved total is not a number the assistant carries in its head between phases. Launch every
paid process with three figures in its environment, supplied by the process and never by `.env`,
exactly as `TRAIGENT_FIRST_RUN_PHASE` is: `TRAIGENT_FIRST_RUN_COST_CEILING_USD` is the total
approved above; `TRAIGENT_FIRST_RUN_COST_SPENT_USD` carries the cumulative budget debit when the
process starts: known costs plus conservative reservations for calls whose cost is unknown.
Include any earlier live probe or judge calibration; use `0` only before any debit.
`TRAIGENT_FIRST_RUN_UNTRACKED_CALL_COST_USD` is the
conservative amount one provider call is deducted for when its route reports no cost, rounded up
from the observed per-call cost once the probe has one and from the estimate the approval card was
priced with until then. None of the three has a default, so a paid phase launched
without them stops before its first call instead of running on a per-optimization limit that knows
nothing about this walkthrough. State the three on the approval that sets them, in the same numbers
the card shows. `references/sdk-execution.md` owns what the wrapper does with them. A fourth
variable, `TRAIGENT_FIRST_RUN_BASELINE_TIMEOUT_SECONDS`, the baseline phase's wall-clock bound, has
no default either and is placed in the process the same way; `references/sdk-execution.md` owns
its sizing under "Automatic run bounds".

Do not persist `TRAIGENT_COST_APPROVED=true`; set approval only in the current paid process, which
is what keeps the SDK's own prompt from offering to raise the approved total. The SDK enforces its
optimization-call limit, but it does not yet share one cumulative budget with calibration and other
calls. Until it does, keep a single running total rather than a phase ledger: each paid phase prints
its budget debit and known cost separately against the figures it was launched with, and the
cumulative debit that line names -
not the SDK's tracked cost, which cannot see a conservative deduction or a refused trial - is the
running total, passed to the next process as its `TRAIGENT_FIRST_RUN_COST_SPENT_USD`.
Before the next phase, stop if its estimate does not fit the remaining total ceiling.
Never call the walkthrough ceiling a hard provider-billing cap, tracked cost or not.

A phase that reaches the remaining stops there and is reported as what it is: the trials it
completed, its stop reason, and the work that did not run. The way past it is a fresh approval for
a larger total, taken back to the user with known cost and budget debits so far - never a larger figure
handed to the same process, and never a second attempt at the same phase on top of what the first
one already spent. A phase that DIED having spent is the same arithmetic and not a fresh start:
a paid process prints its ledger on every ending that runs `atexit` - finishing, `sys.exit` with
any status, an uncaught exception, `SystemExit` and SIGINT are each measured printing it once - so
take the running total from that line, carry it into whatever runs next, and report the phase as
stopped part-way rather than as not having happened. An ending that never reaches `atexit` prints
nothing at all, and that rule is what to hold rather than a list of two: measured, SIGTERM, SIGKILL
- what `kill -9`, the out-of-memory killer and a container eviction send - SIGHUP, a dropped SSH
session, SIGQUIT, `os._exit` and `os.abort` each printed no line. When no ledger line was printed,
that phase's complete accounting is not recoverable from the SDK's tracked cost. Carry the whole
of its remaining approved allowance forward as a conservative budget debit, say that it was killed
and its exact cost is unknown, and take any further work back to them as a fresh approval.

The SDK already retries transient Traigent-backend requests and classifies provider failures.
Do not layer another retry loop over it, expose retry counts to the user, or set
`TRAIGENT_VENDOR_MAX_RETRIES` for the first run. Preserve retry behavior already present in the
user's agent/provider client, with two exceptions the spend ledger requires. Retries the provider
client would take underneath the wrapper are turned off, because a call it repeats down there costs
real money the ledger never sees and the running total never moves for; and resilience expressed
through a knob the reservation cannot size - `retry_policy` among them - is refused rather than
guessed at, because pricing it at one call is what let six requests be billed against one. An
explicit retry count the caller set is kept and is charged for rather than absorbed, and
`references/sdk-execution.md` owns the mechanism and what it trades away - a transient failure now
surfaces instead of being retried silently. Generated walkthrough provider calls add
no explicit retries. When the preserved client has bounded retries, include their possible extra
calls in the internal runtime/spend estimate without asking the user to configure them.

After the approved live probe, calculate internal request and SDK optimization bounds from
observed latency, rows, trials, calls per example, and concurrency, with a reasonable completion
margin. These are implementation details, not user choices. If observation makes the run
materially longer than the approved estimate, offer a smaller run or quote the additional
time/cost. A timeout, with or without completed trials, follows the Recovery rules below.

Verify selected model IDs are live before scaling and inspect their cost coverage. Missing cost
alone neither blocks the run nor authorizes replacing a model. If a model chosen by the
assistant is unavailable, replace it only with a working model from the same chosen
provider for the same task and data, with unchanged-or-lower call counts and combined worst-case
spend. Record the replacement. Any other change requires revised approval. If the user chose the
model, never replace it silently; present the limitation and one recommended alternative.

### Missing cost or usage telemetry

A successful provider response can support a quality measurement without cost or token metadata.
Keep actual call-path, evaluator and truncation checks; missing usage alone is not evidence of a
fake call. Retain trustworthy reported charges, including an explicit zero, even when usage is
absent. For manual calls, prefer the provider's public response or response metadata. Do not
recalculate a completed OpenRouter response with `litellm.completion_cost()`: a missing local
model-map entry can raise after the call. An SDK `0.0` default or estimated token count does not
establish a free call or provider-reported usage.

Before each baseline or search operation, use cost as an SDK objective only when its cost coverage
is trustworthy for the actual agent and evaluator call paths. Otherwise use the public SDK's
primary-only objective path owned by `references/sdk-execution.md`. Keep the primary criterion and
its direction unchanged. This is a quality-only comparison, with no cost-ranked recommendation,
savings claim or objective-cost frontier. Missing usage by itself does not remove a trustworthy
cost measurement; a provider cost field alone does not prove the SDK's cost objective consumed it.
Repair before the first baseline may establish cost coverage normally. Once an operation has used
primary-only objectives, keep that mode for the rest of this comparison. Recovered trustworthy
cost can be reported with its source; adding a cost objective belongs to a separate future run.

Put the telemetry limitation on the existing stage approval card: which cost or usage records are
absent, the bounded rows/trials/calls and runtime, the credible conservative per-call estimate and
remaining allowance, and that **actual charges for unpriced calls are unknown to this run and stay
unknown**.

For direct provider calls outside the SDK ledger, say on that card: `The SDK's dollar stop target
does not cover these calls; <separately verified call bound and debit coverage, or not established>.`
Apply the call-accounting contract in `references/sdk-execution.md`; a path the controls cannot
observe is not a dollar-limited path.

Use the same final reply-ready block, not another setup question:

- `A.` **Continue the bounded run on the primary criterion** *(recommended - it can still show a
  meaningful quality comparison)*. Reply `continue`.
- `B.` **Repair telemetry first**, an optional route for a user who wants cost comparisons or token
  records before proceeding. Reply `repair`.

Do not ask again when the existing explicit approval already covers these conditions and bounds.
Otherwise record the `blocked`/`approval` line before waiting; silence is not approval. The user
can still stop and keep completed results. Repair is not a prerequisite to the quality-only route.
Every unpriced call deducts the approved estimate, including manual calls outside the wrapper;
known charges are retained separately. The call gate, whole-holdout preflight, trial cap and timeout
still apply. If a credible estimate cannot be established, the existing approval requirement is
not satisfied. These controls bound execution and allowance, not the actual provider bill.

If cost coverage is lost mid-run, retain that run and its quality observations, name its actual
declared objectives, and mark its cost comparison and cost-based recommendation unavailable. The
SDK does not atomically change objectives within that operation: do not relabel an earlier
cost-aware search as quality-only or restart a paid baseline to repair metadata. Use primary-only
objectives for the next already-planned phase under its valid approval, recording the removal of
the unavailable secondary objective. Unchanged primary scoring still permits the disclosed quality
comparison; the phases no longer establish a like-for-like cost-aware search comparison.

At the close, show the quality result and its evidence limits, then name missing usage or cost,
known cost subtotal, unknown-cost call count, cumulative budget debit and remaining allowance.
Report provider usage as unverified where absent; never substitute SDK estimates or defaults.
Include optional telemetry repair as a future action when cost comparison is the useful next step,
without turning it into a required detour or adding another paid round.

## Connected-run readiness

The connected run's most damaging failure is not a missing key - it is a present key that silently
stops tracking. A permanent trial rejection (HTTP 400 for a config the backend will not accept) or a
present-but-unscoped key (HTTP 403 when the key lacks the `experiment.write` scope) can drop the run
to local-only tracking: `results.cloud_url` is `None`, no experiment reaches the portal, and the SDK
warns once and proposes the next trial anyway - so a user with a valid key reasonably believes the
run reached the portal when it did not.

Prove the tracking path before connected spending, with a zero-LLM probe:

1. Build a trivial stub agent that returns a constant and makes no provider call, so the probe costs
   `$0` in LLM spend.
2. Run the smallest possible connected optimization through the installed SDK's public path (one or
   two trials) and confirm each rung in order: the portal key is present, it authenticates, it is
   scoped for `experiment.write`, a session is created, the first trial is accepted, and a
   `cloud_url` is returned.
3. If any rung fails, stop before any connected paid trial. Show a sanitized reason and stable
   status/request id when available. Preserve the useful diagnostic category, but remove secrets,
   prompts, examples, outputs, and personal data before showing or saving external error text.

When the key does not authenticate, re-run `preflight.py --env <handoff file>` before blaming the
key - it is free and makes no call - and report what `env-shadowed-key` says: it compares the shell
against that file, names whatever disagrees, and prints its own remedies. Read `env-source` first:
it names the file compared, or `process environment only` if none was; another name there is
another file's verdict.

This probe is general readiness, not a workaround for any single validation rule: the installed SDK
owns the local pre-checks (config-in-space, numeric-type, `example_id` uniqueness) and the loud
local-only signal; the skill's job is only to confirm at `$0` that tracking actually attaches before
paying, and to keep confirming it during the run. A mid-run 403/400, and the `rejected` persistence
state a permanent rejection leaves, are stamped on the run's own configuration where
`references/sdk-execution.md` reads them: every later provider call is refused, so the trial already
evaluated when the backend broke is the last one paid for. A missing `cloud_url` is not visible
while the search runs - it exists only on the returned result - so that one is read the moment the
search returns and stops the run before the next paid pass rather than after it.

The probe answers whether tracking attaches, at the moment it runs. It cannot answer whether the
managed brain is still reachable when the paid search starts a moment later, and the two failures
are not the same: a run can keep tracking trials to the portal while the search choosing those
trials has quietly become local. `references/sdk-execution.md` owns the setting that closes it -
the connected phase runs with local fallback disabled, so a session that cannot be created raises
instead of degrading - along with the environment settings that defeat it and how a raised run is
reported. Neither replaces the probe: the flag governs the SDK's own fallback, while the probe is
what proves the key is scoped and the session reaches the portal at all.

That setting turns one class of silent degradation into a stop, so decide the stop with the user
before it costs anything. If the inventory finds a no-egress setting in the environment or `.env`,
the connected phase cannot honestly run. Ask once, in a message of its own before the connected
preview and never inside it, ending on two lettered routes: `A.` keep no egress and finish on the
local baseline, marked recommended because the setting is theirs and that result is complete and
reportable, or `B.` lift it deliberately for this run. Never clear it for them, and never carry
the question past the approval card into the middle of a paid phase.

## Baseline and optimization

### Comparison sequence

Use the same tuning slice, evaluator, primary criterion and direction, and agent call path for both
measurements. Record any secondary-cost transition under Missing cost or usage telemetry.
Preserve the user's existing baseline exactly, including its original configuration count; never
pad it. Only when missing, prepare the credible twelve-configuration fixed sweep, including the
initial configuration. The space construction rules below own the enhanced dimensions and values.
Keep every baseline value and model, add only meaningful controls the agent consumes, and test up
to 12 configurations. Any new model is a separately disclosed experiment. This is the last run,
so the controls that carry cost are varied here or not at all, within that approved experiment.

For an operation that declared cost optimization and has trustworthy comparable cost evidence,
report its measurement as a **Pareto frontier over the declared objective and cost**, naming the
objective in the customer's own words. Otherwise show
the primary-criterion comparison and mark cost comparison unavailable. Both read completed trials
and make no provider call. Never show a frontier point worse than the configuration the user is
already running under the declared objective direction. The objective-cost frontier below owns
claim strength; SDK Result checks owns the read.
The three-tier ladder applies only when this walkthrough supplies a missing baseline: one fast,
one mid, and one strong tier one step below - never the vendor's newest flagship. Preserve a
customer baseline's exact model set and do not add cheaper tiers without separate disclosure.
Frame the enhanced run as a deliberately small enhancement: a small slice of what Traigent can
drive, not its full capability.

The baseline needs only the user's provider credential. Run its explicit fixed grid without a
Traigent key in that process, preserving any existing key on disk. Say plainly that this is a
**local fixed grid**, not Traigent choosing which configurations to test. It is local, not free:
provider calls spend from the same approved total.

Immediately after it returns, show a **Local baseline checkpoint** before any Traigent-key or
account request:

- Start with the recorded target project and selected agent identity; put substitute limits before
  numbers where applicable. State that this was a local fixed grid, not Traigent choosing trials.
- Show the best configuration, the primary tuning metric by its actual name, cost, latency, and
  executed and failed trial counts. Report unavailable cost or latency as `not measured`.
- Show this grid's own objective-cost frontier beside the winner only when it declared cost
  optimization and has trustworthy comparable cost evidence; otherwise show the primary-criterion
  result and its telemetry limitation. Read completed
  trials without another paid call. Explain each baseline knob in one plain-language note.
- State that no generalization or production-improvement claim exists yet and this phase created
  no portal experiment. Do not disclose the held-out score before section 8.

Check whether the dataset and evaluator distinguish configurations. If not, stop before search
and recommend the evidenced repair before any connected preview. For a free repair to code this
run wrote or to a working copy preserving their files, use component-creation.md's repair routes:
never offer a route that carries the diagnosed fault into paid work, and do not put abandoning the
run as a co-equal letter beside the free repair.
For a nearly perfect baseline with no informative failures, report little or no measured quality
headroom, and cost headroom only where cost was measured, as a limit on the claim; a ceiling effect
remains a hypothesis. Harder realistic
cases belong to the post-run `traigent-dataset-curate` handoff. Offer `A.` the bounded connected
run as an optional no-lift-possible verification with no expected gain, recommended for the
capability and information it adds; or `B.` stop with the preserved baseline-only result.
A quality-only search with walkthrough material requires a workflow-demonstration label. A cost
objective may proceed at equal objective score only when materially lower cost remains possible;
report any gain as cost and flag weak evidence.

Recommend the sound continuing route: measured headroom can strengthen the case but is not its
only basis. State what continuing produces: managed trial selection, a portal experiment/link,
a recommendation across both runs, and a held-out score when independent rows are available. Approval and budgets owns that workflow value. Declining stays available and plainly answerable. Stopping here
leaves a real measured baseline, reported as baseline-only rather than a completed Traigent
optimization. Never promise improvement or what the held-out score will be, or suggest stopping
is a mistake.

Present `Stage 4/5 · Optimize` through Approval and budgets' connected preview: managed selection,
portal history, bounded calls/cost, and deeper insights as conditional capabilities. Its lettered
routes are last, below the disclosure prose. Obtain explicit approval for this connected stage
before its key, probe, sync, or calls. Do not ask the user to choose trial counts or knobs; select
them from the inspected agent and include their calls in connected-stage approval.
In the enhanced run card, repeat the baseline knobs, label
every addition new, and give the total combination count beside this run's trial cap as a ceiling,
never a range. Disclose any reduction here; never promise a pause at minute 30. Size the run first.
Explain Traigent's documented synchronization, exclusions, and exceptions inside the preview,
above its routes; call it a service contract rather than a packet audit and stop if runtime
behavior contradicts it.

Only after that checkpoint, ask for the Traigent key: a provider-backed result precedes any
account request. The key needs full access rather than the read-only default. Reuse a suitable
preserved key or resolve the four account/key states under Environment and privacy, using its
same local handoff file and two 10-day windows: the access code, then portal access.
Enter credentials locally, never in chat.
Once the key is present, run the zero-LLM portal probe. Then feature-detect a public exact sync id
and use SDK Carrying the local baseline into the portal. Without a supported id, keep the baseline
local; never inspect private storage or use `--all`. Never pay to repeat the baseline for a portal
entry. Run the enhanced optimization connected and verify its own link without implying it covers
an unsynced baseline.

Before either paid phase, prove the applicable wrapper and spaces locally; re-prove after changes.
Historical `wired` is never proof. Generated `reflect` uses `off`/`on` because the pinned cloud
session rejects bools; never recode a customer boolean. Refuse an SDK-rejected final space before
baseline approval. Space construction below owns meaningful dimensions and the bounded arithmetic.
Follow the freeze/remove/persist lifecycle: save `traigent-runs/config-space.json` only after this
search returns nonzero trials, from the exact space received. Only that current-run file enters
the closing readiness `--config-space` score.
Select the recommendation on tuning scores across both measurements, never on held-out rows, then
score only that one against the reserved rows, when available, under the dataset reference's
Held-out set and claims. Do not fabricate configurations to hit a count: a preserved baseline of one configuration
stays one, while a generated walkthrough must supply twelve configurations.
If provider, backend, or portal connectivity fails, stop with the concrete failure and one recovery;
never substitute mock or synthetic results or call offline checks a completed optimization. Resume
the connected path after resolution. The baseline and the enhanced search are this run's only paid
passes; the operating contract owns that bound. Further iterations belong after this result under
a specific hypothesis and newly scoped approval.

### Space construction and request proof

Follow SKILL section 7 for the comparison order, evidence held constant, checkpoint, and exact-sync
decision. This section owns configuration-selection depth and execution/reporting safeguards.

Keep both spaces tied to the real agent and observed failure modes. Preserve a user-owned baseline
space unchanged, even when it contains one configuration. The generated walkthrough's two exact
sizes and their derivation live in `references/sdk-execution.md`; use those values rather than
restating the arithmetic here. The baseline trials are one per configuration, and the approval card
names that count - as a count, never as a change from whatever this guide did before, which the
customer has never run.

The three default behaviour knobs are prompt style, thinking shape (direct or chain-of-thought),
and reflect; temperature stays fixed at the task-selected value owned by `sdk-execution.md`, so
every swept knob is real for every model. They are
selected from the seven direct-parameter controls in the nine-control catalog
`references/sdk-execution.md` owns. The approval card shows
the selected three and why they fit; the customer does not have to design a space from the whole
catalog. The
models are the fast, mid, and strong rungs of the walkthrough model
ladder from the selected route - the strong rung one step below the vendor's newest flagship, at a
pinned effort in both runs when it is a reasoning model, and never the flagship itself. The
enhanced space keeps the identical model list and every baseline value, so the baseline is a strict
subset of it and an enhanced win is attributable to knobs and the managed search, never to a model
the baseline did not measure. Explain this generated-only
ladder in one line before the
approval: skipping the flagship keeps the first run faster and cheaper, and the flagship stays
available for a separately disclosed later comparison if the evidence supports one. A preserved
baseline keeps its exact model set, including a flagship when present. Do not add cheaper tiers or
any other model unless a separate model comparison is disclosed and approved. For preserved
agents, add only direct request parameters, such as context format or few-shot count; do not force
the generated example's controls onto an unrelated task.

The three-control limit belongs to the generated walkthrough. A user-owned baseline retains every
existing dimension and candidate value in both spaces, even when it has more than three controls.
Do not remove or pin baseline controls to fit the generated shape or improve a readiness score.
The automatic run bounds above still govern actual paid work; disclose limited coverage of a large
preserved space rather than silently narrowing it. This does not authorize more trials or spend.

In the generated walkthrough, all three controls and all their values are fixed before either run,
exactly as `references/sdk-execution.md` shows. A baseline observation that suggests a different
value or fewer controls is a hypothesis for a later run, not an undisclosed edit to the approved
comparison. Read which knobs it varied off the space that actually ran. Small baseline samples
cannot prove a knob has no effect. Say `did not move the baseline` or `the baseline's best
combination used X`, never `does not matter` or `X is better`, and give a knob this baseline never
ranked no verdict at all.

The generated controls are limited to demonstrate the principle cheaply: a first run has to finish,
cost little, and be readable. Traigent knows tens of knobs it can recommend once the principle is
shown. This is a demonstration, not the ceiling of what Traigent can do, and no result here should
be read as the best the system could reach. Never present the smaller generated space as though
the improvement were bought by shrinking a customer baseline.

The generated `reflect` control ships as `off`/`on`; the pinned cloud session rejects bools, so the builder compares labels explicitly because `off` is a non-empty string. A generated walkthrough fixes the
one task-selected temperature owned by `sdk-execution.md` across both phases and carries the search
on behaviour knobs instead. Preserve a user-owned baseline's temperature behavior exactly,
including an unset provider default; record resulting nondeterminism as a limitation rather than
silently changing the baseline. Multi-call controls are outside this first-run paid space. Match
each direct parameter to an observed single-call failure; blind wiring adds cost and can worsen the objective.

Managed `auto` is a guided search, not an exhaustive grid: `max_trials` is a cap, not a minimum,
so the service can stop with fewer trials. `auto` already runs Traigent's smart cloud search, so do
not hand-pick a named optimizer such as `bayesian`, `tpe`, or `optuna`; use `auto`, `grid`, or
`random` unless a named selector is confirmed to run consistently on the installed SDK. For an
assistant-prepared baseline, use local `grid` so all twelve distinct configurations are
predictable. For a user-owned baseline, preserve its space and selection behavior exactly in the
local phase. Use connected `auto` with a default cap of 12 for the enhanced space, then report the
actual count and stop reason; `references/sdk-execution.md` owns the shortfall obligation beneath
that cap, so never silently present a two-configuration generated run as the intended comparison.

Composite patterns are a later workflow, not a first-run paid dimension.

### The objective-cost frontier

SKILL section 7 owns when a frontier is reported and its incumbent score bound; `references/sdk-execution.md`
owns the read. Owned here: what it may claim, and the wording of its two outcomes. It costs nothing
and adds no stage: where cost coverage is trustworthy, this is arithmetic over trials already in
hand. Report it whichever way it comes out. A quality-only run reports its primary scores and
evidence limits instead; no cost frontier does not mean no quality result.

The floor is a number this run reads rather than a judgement it makes: the incumbent's score on
this run's own metric, the incumbent being the configuration the user is already running. It is a
lower bound for a maximized objective and an upper bound for a minimized objective; use that same
declared direction for admissibility, dominance, and the user-facing comparison.

It needs measured cost to exist at all, and two runs fail that for opposite reasons the user is
told apart:

- **Cost was not tracked.** An unpriced trial is not a cheap trial, and a `0.0` standing in for
  pricing the run could not resolve is an absent cost wearing a number - indistinguishable in the
  metrics map from a real one. Report no frontier, and say why.
- **The route genuinely costs nothing.** A trustworthy provider-reported `0.0` for an actual call
  is a real measurement even when token usage is absent. A route with no cost has no trade-off to
  plot. Say that instead, rather than the reason above.

Each point is one configuration's measured cost beside its score on this run's own metric, over the
same rows, evaluator, and agent call path as everything else it reports. Dominated points are
dropped - a configuration that cost more and performed no better under the declared objective
direction than another on the same evidence is not a trade-off anyone would take.

Known cost can vary when a configuration is evaluated again, inside one run or across two.
Report each point's measured cost and let
the reader see the gap; never present two points a few percent apart as a saving.

A frontier asserts no win, so it needs no threshold to clear and states none. What it does need is
the score claim `references/evaluation-and-dataset.md` decides from paired evidence on the shared
tuning rows: binary outcome counts or graded per-row changes in the declared objective direction.
When those per-row results are unavailable, say the paired comparison was not measured; never
derive it from aggregate scores or pay for another pass. Where paired evidence exists, keep the
claim directional, and say "the score did not get worse" only where a justified paired uncertainty
analysis over the completed outputs supports it. Report rows where the cheaper point performed
worse than the incumbent even when they are outnumbered, because failing to detect a drop on a
first-run slice is not evidence there was none. A point reaching the frontier is not evidence its
score held: several configurations can be statistically indistinguishable at this size, so the one
that matched the incumbent's number may simply have measured lucky. Never let "the optimizer picked
it" stand in for evidence that the score held.

That bound is why a cheaper point is never sold as settled. What a frontier this size supports is a
hypothesis worth testing at full scale - "a cheaper tier scored level with the winner on these
rows" - so it travels to the close as one, under the rule the continuation handoff below already
states. It does not earn another paid round here.

#### The two outcomes

Both are results. Neither is apologized for.

**The frontier holds more than the incumbent.** Report the recommended point against the
configuration the user runs now, then the rest of the frontier as the trade-offs it measured:

> `<config>` scored `<value>` at `<measured cost>`, against `<value>` at `<measured cost>` for the
> configuration you are running now, on the same rows, evaluator, and agent call path -
> `<paired tuning evidence, or paired comparison not measured>`. Cost here comes from
> `<the verified cost source>`; token usage is `<reported or unavailable>`. The score comparison
> covers `<n>` rows: `<the claim the available paired evidence supports, or its absence and the
> resulting limit>`. The whole frontier this run measured is `<points, cheapest first>`.
> These are the measured costs of this run; repeatability was not tested.

**The incumbent is the only point on it.** This is a finding, and it gets its own copy. Report what
this run counted, never a property of the space: the space is larger than the run's trial cap, so
any claim about the space quantifies over configurations the run never reached.

> This run tested `<distinct configurations>` of `<total combination count>` configurations
> in `<executed trials>` trials. On
> `<what you are optimizing for>` against cost, the configuration you are already running is still
> the only point on the frontier:
> nothing tested cost less at its score, and nothing scored better in the declared objective
> direction at its cost. So keeping it is
> the answer this run supports. A run this size reaches few configurations by design; the skills
> named at the close help you apply what you learned to your own project.

That is a measured answer to the question this run asked, and a service rather than a shrug: the
user wanted to know whether a better trade-off was sitting there, and now they do instead of
chasing one. It is bounded as honestly as the other outcome - it establishes nothing about
configurations the run did not test, and a bounded run tests few. That bound is the forward half,
and it points at an action and never at a result: the handoff below names what a wider search would
let the user *do*, never what it would find. Do not answer it with another paid run.

## Post-run verification

### Reporting procedure

Lead with a layered summary whose opening layers are enough for a quick read and whose details are
auditable:

1. **Outcome** - baseline versus enhanced result and whether a recommendation is supported.
2. **What the evidence establishes** - baseline tuning result, enhanced tuning result, and actual
   persisted runs.
3. **Current state and limits** - component provenance (for a topped-up dataset, the ceiling its
   generated share carries, with its number; the details layer keeps the mixture's counts),
   exclusions, uncertainty, incomplete phases, missing cost/usage telemetry, and any small-sample
   held-out gap.
4. **Next action** - apply the most useful lesson to the customer's own project through the
   continuation handoff below.
5. **Details** - configurations, objectives, trials, failures, cost, stop reason, artifacts, and
   verified links.

Include:

- Best baseline configuration versus best enhanced configuration on the tuning set.
- Each run's objective-cost frontier only when it declared cost optimization and has trustworthy
  comparable cost evidence; otherwise its primary scores and telemetry limitation. Keep these in
  the details layer. One recommendation still leads;
  a frontier put where the recommendation belongs is the menu this stage already refuses.
- The recommended configuration's held-out score and small-sample note when completed; otherwise
  state why that check was unavailable.
- Known cost subtotal with its source, unknown-cost calls, cumulative budget debit and remaining
  allowance; the configurations tested out of the space's total, failures, stop reason and direct
  portal links. Name each phase's actual objectives when cost coverage changed.
- Which components were `✅` real and which were walkthrough substitutes.
- What this run created or repaired, and what that costs the claim: examples it wrote are weaker
  evidence than examples collected from the product, and an evaluation method it wrote is a
  starting point rather than the product's grading policy - one a person may want to move in
  either direction, so it rewards what their product values.
- The run's scope, in this run's own recorded numbers: rows scored beside the dataset's usable
  rows, distinct configurations measured beside the enhanced space's combination count, executed
  trials separately, and knobs varied beside the
  controls this run identified on the agent. Say plainly that those bounds were the walkthrough's
  own choice - a getting-familiar run rather than the largest one available - and keep it a scope
  statement, never a pitch. Drop any clause this run did not measure instead of estimating it.
  Run-scope statement below owns each number's source and how the sentence degrades.
- When the enhanced run does not beat the baseline, report the observed flat/negative delta first,
  then separate verified facts, evidence-backed inferences, and untested hypotheses. Use
  `cause not established by this run` unless the evidence rules a cause in. The hypotheses and
  rule-out order below guide the next test; they are not mandatory
  diagnoses. When the reference is demonstrably ambiguous, wrong, or degenerate, say so rather
  than blaming the model. A flat result on demonstration data shows only that this comparison ran
  and found no lift on its evidence, not that production cannot improve. Carry the run-scope
  statement above into this no-lift report beside the delta itself, not only in the scope line: the
  bounds are what let no lift be read at the scale it was actually measured at.

Retain every experiment that was actually persisted in the Traigent portal. Never delete one as
automatic teardown or cleanup. Give the user a direct verified link for each persisted run and
label the baseline local-only when exact sync was unsupported or failed.

If any substitute was used, lead the interpretation with:

> Completed in this run: `<verified phases>`. Not completed or independently verified:
> `<missing phases>`. Because `<components>` were prepared as walkthrough substitutes, the
> measured result is not evidence of expected production performance.

Do not promote a configuration from a fully synthetic run. For real components, promotion still
requires explicit user approval and a later validation check that is tracked separately from the
baseline/enhanced comparison. When the assistant inspected or authored that material, call it
assistant-authored or assistant-inspected evidence and do not present it as independent
production-promotion evidence.

Name every row the comparison did not score, with its id: rows excluded as degenerate references,
and the ids of the bounded subset when one was drawn. State it even when nothing was excluded, so
silence never has to be interpreted.

Do not close on a second number. Re-run `scripts/readiness.py` on the post-run evidence for the one
reading nothing earlier could take - the agent pillar, scored from the space the enhanced search
actually received - passing the current run's `--config-space traigent-runs/config-space.json` only
when that search emitted it, and the same row-level read, so this score is not held for a gap an
earlier card already closed; otherwise score the agent from absent evidence. The opening and section-4
scores withhold every config-space document by construction, so this is the run's only measurement
of the space the customer paid to search. Its dataset and evaluation caps rank nothing and settle
nothing about what is still open: a gap this run filled with a substitute reads exactly like one the
customer closed themselves. Never show that
score or set it beside the opening one.

Two things read that call. Its agent cap is a finding about the search that just ran: a document
that varies nothing means the paid run compared one configuration, so the card blocks and the close
reports it beside the search's own outcome. And this is the only place anything reads
`traigent-runs/config-space.json`, so a file this run wrote and cannot itself parse is refused here
by name rather than left in the customer's project for them to find. The verification rules below own how that card reads after a stopped, failed, or zero-trial search. Leave the user knowing which
remaining gap to close first.

### Verification checks

Before claiming success, verify:

1. Trials exist; distinguish failed examples, failed trials, and repeated configurations.
2. Baseline was actually evaluated.
3. Best configuration exists.
4. Primary objective measures appear and vary meaningfully. Record any unavailable secondary cost
   objective as a limitation under "Missing cost or usage telemetry"; it does not erase quality.
5. Real calls do not show the mock's constant response pattern.
6. Verify the actual provider path and successful responses. Report provider token usage where
   available and mark it unverified where absent; missing usage alone does not invalidate quality.
   Separate known cost, including a trustworthy reported zero, from unknown cost and budget debits.
   Do not present SDK default cost or estimated token counts as provider observations. Attribute
   discrepancies to their sources; one unpriced call does not make every trial unpriced. Use
   retained final artifacts for durations and totals, not earlier progress estimates.
7. Inspect per-example failures as well as trial status. The SDK can absorb a truncation exception
   as a zero-scored example inside a completed trial. Exclude incomplete measurements from the
   recommendation through the Result checks adapter; report affected trial/row ids and the
   recorded denominator, never recompute a success-only average. Preserve their spend, including
   `REFUSED_TRIAL_COSTS`; unreported cost remains unknown.
8. Portal persistence status is complete or precisely described as degraded/failed.
9. `cloud_url` exists before saying the result is on the portal.
10. The pre-connected-run portal-tracking probe passed and tracking did not silently drop to
    local-only during the run; a degradation refused every provider call after it, and an absent
    `cloud_url` stopped the run before the next paid pass rather than at the end.
11. Baseline and enhanced tuning results are shown side by side, with the tuning-data limitation
    named before any generalization claim. Show the completed held-out score beside them, or
    explain why that check was unavailable.
12. Every reported frontier carries measured costs, a score claim supported by the available paired
    evidence or an explicit statement that the paired comparison was not measured, and no point
    worse than the incumbent under the declared objective direction. Trials that came back without
    reported cost carry no cost claim: report that, not a number. Quality-only runs show primary
    scores and the telemetry limitation instead.
13. Each paid process ran against the approved figures it was launched with, and the close reports
    them: the approved total, cumulative budget debit, known cost subtotal, unknown-cost calls and
    remaining allowance. A conservative reservation is a budget deduction, not a measured charge.
    A phase that refused to start, or stopped at the remaining, is named with the work it did not do.
    Name each phase's actual objectives if cost coverage changed. Retain each phase's printed
    ledger summary with the run artifacts so its totals can be checked after the process exits.

An optimized winner that does not beat the baseline is a valid no-lift result. Report the observed
delta first, then separate verified facts, evidence-backed inferences, and untested hypotheses.
Candidate hypotheses include an uninformative space, limited or easy data, evaluator mismatch,
controls the search never varied, output truncation, generated data with no headroom, or insufficient
model capability. Use the checks below to choose the next test, but say `cause not established by
this run` unless evidence rules one in. A flat demonstration result says only that this comparison
found no lift on its evidence; it does not predict production.

Investigate in order: verify semantic equivalence and references, inspect truncation and whether
every declared control varied; then, as the user's own next run rather than this one, add one
structural knob tied to a failure mode or consider a separately disclosed stronger-model comparison. Distinguish a genuinely hard item from a
demonstrably ambiguous, wrong, or degenerate reference. Attribute the latter to the reference, not
model capability, and never change a validated metric merely to manufacture a win.

Frame no-lift for a first run too, in the recorded numbers the run-scope statement below supplies
rather than as a general remark: a bounded getting-familiar pass deliberately searches a few
relevant knobs on a small budget, so a flat result can simply be a normal first look rather than a
fault. The honest next step, the user's own next run, is one deliberate iteration adding a single
structural knob where the evidence points, not piling on knobs or spend to force a win.

Read a flat result at a favorable score the other way round, and only on collected data. Use the
declared objective direction and its product meaning: high accuracy can be favorable, while high
error is not. When the completed paired analysis detects no difference between configurations, say
they did not separate on the measured tuning rows. That does not establish equivalence or prove
that these configurations are not limiting performance. Keep the configuration recommendation
under the existing tuning-selection and frontier rules; an inconclusive comparison does not make
the cheapest point the winner.

For a favorable flat result with measured costs, a tier BELOW anything tested can be a hypothesis
for a later experiment instead of a stronger model. Carry that hypothesis into Continuation
handoff's ranked recommendation; it does not displace a more important unresolved gap.
Without trustworthy comparable costs, report the favorable-score tie without calling a
configuration cheapest; telemetry repair is an optional next step if cost comparison is what the
user wants to learn next.

Two bounds it keeps, both already owned above. It is a statement about what this run tested and
never about the space - a cheaper tier nobody ran is a hypothesis for a later experiment, exactly as
a cheaper tier that did run and matched is - and it does not earn another paid round here. And it
requires collected data: on generated rows a favorable flat score measures material this run invented;
an easy-looking task may reflect how the walkthrough examples were constructed.

If any component is synthetic, put the limitation before the score. A synthetic Pareto frontier
can look identical to a production one.

Then explain what remains to validate for the intended product use, as one paragraph rather than
a warning. For every pillar this run generated - the dataset, the evaluation method, the agent -
name the needed real replacement or human review of its task fit. Those are next validation
actions, not proof of production readiness. Reporting procedure above and "Held-out set and
claims" in `references/evaluation-and-dataset.md` own the later promotion requirements; human
review alone does not satisfy them. Describe the answer-key review on the terms "Say what you
reviewed and what you assumed" in that reference sets out.

Say what the run actually gave the user, using only completed phases and verified artifacts.
A preserved local baseline is useful even without a portal result. Name results in the portal only
when persistence and their links were verified; otherwise report the local result or the precise
missing work. Discuss easy-versus-hard behavior only where measured outcomes support it, and a
held-out score only when that scoring completed. With zero completed trials, describe the checks
performed and the remaining work, not an optimization result. This is a bounded first look, neither
proof of production readiness nor evidence to discard merely because a later phase did not finish.

Name what this run built around what, because that is the part a provenance field cannot say. An
evaluation method written around a dataset may fit those examples more closely than unseen inputs;
when both were written here, shared assumptions can make their agreement look stronger than it is.
The held-out split does not resolve that risk: both sides use the same evaluation method. So say,
plainly and without provenance vocabulary, which pillars were built around which and how that can
limit the claim. Do not assert that bias occurred or quantify it without evidence.
Where this run repaired rows the review found unsound, say that
too, with the count: their dataset had problems and this run changed some of it. Neither is a
deduction - the generated-provenance ceilings already price the material once, and charging twice
for one fact would be a second ceiling nobody decided on.

### Run-scope statement

The close states the run's own bounds so its numbers are read at the scale they were measured at.
Every clause is a number this run already recorded; a clause whose number the run does not have is
dropped, never estimated to complete the sentence.

- **Rows** - the scored row count beside the dataset's usable row count, both already recorded when
  the bounded subset was drawn. When no subset was drawn the two are the same number: say the run
  scored every usable row and let the other clauses carry the bound.
- **Configurations** - distinct configurations measured beside the enhanced space's total, with
  executed trials stated separately; repeated trials do not expand coverage. With no enhanced
  search, drop this clause and name the completed baseline instead.
- **Knobs** - the controls the enhanced space varied, beside the candidate controls this run
  identified on the agent. When it never enumerated a wider candidate set there is no denominator
  to quote: say instead that the space varied only the controls whose wiring this run verified, and
  name that as the bound.

Then one sentence saying those bounds were the walkthrough's own choice, so this was a
getting-familiar run rather than the largest one available.

Keep it a scope statement. It reports what was measured and what was not; it does not predict that
a larger run would have won, attach a deadline, or supply a reason to act now.

### Continuation handoff

If the throwaway route changed the agent's dependency versions, name the original and walkthrough
versions beside the existing reinstall reminder, using setup evidence; compatibility with the
original environment remains unmeasured unless this run established it separately.

Close by connecting what the user learned to their own agent, dataset, and evaluation method.
Use the run-scope terms above, and say what remains to validate before production use: which
material was generated or repaired, what this run built around what, and which original material
was never changed. A clean working copy does not establish that the customer's full dataset is
clean. Readiness findings identify useful work; raising a score or clearing a ceiling is not the
customer's goal, and accepting a substitute does not certify the product.

Recommend one concrete next action using the most important remaining evidence gap, with the
relevant Traigent skill below as the way to do it on the customer's own material:

- Generated data or model-written answers: collect representative real examples and check their
  expected answers. Human review can improve the generated material, but does not change its origin.
- A generated, repaired, thin, or uncalibrated evaluator: review its task fit and validate the
  customer's evaluation policy on known right, equivalent, and wrong answers before adopting it.
- Duplicates, leakage, uneven difficulty, or missing labels: apply the demonstrated check and
  repair to the customer's own dataset, preserving a separate evaluation split.
- A substitute agent: connect the real agent and verify its inputs, outputs, and evaluation method.
- With those pieces sound, use the measured failure examples to choose a useful control or
  analysis for their next optimization. A larger search is an option only when that evidence and
  the user's objective support it.

Name why the action matters to their project. The deliberately small walkthrough is complete;
do not make another first-run walkthrough or an automatic full-dataset run the default next step.
More rows alone do not fix a wrong answer key or evaluation policy. Keep any claim about a wider
search as a hypothesis, not a promised improvement.

A menu offered *instead of* a recommendation is the same as no recommendation; put extras later.

End with a reply-ready block for the recommended next action, using the route shape in SKILL.md.
Replying `continue` prepares that action and obtains any new approval its scope requires. Replying
`stop` preserves the actual completed phases and results and starts no further work. Neither reply
changes whether the completed run was baseline-only or included a connected optimization; do not
reuse the connected preview's baseline-only stop text here.

After the state-specific recommendation and the result, these are available whenever the user wants them:

- Hand over the Traigent optimization skills so the user can continue alone on their own agent,
  dataset, and evaluation method. Tell the user first and remind them to restart the
  session so the new skills load. List them with `npx skills add Traigent/traigent-skills --list`,
  install one with `npx skills add Traigent/traigent-skills --skill <name>`, or take all of them
  with `--skill '*'`. Then name the two or three this run's own evidence points at and what each
  would let them do next; the map below selects those skills. Offering this is not a
  state-specific recommendation and never displaces the one above; only which skills get named
  comes from this run's evidence.
- Continue into the advanced Traigent lifecycle.

Choose the two or three skills from the run's observations using this map:

| What this run recorded | Skill to name | What it would let them do |
|---|---|---|
| One control accounted for most of the observed spread, or the search barely moved the others | `traigent-analyze-variable-importance` | rank which tuned variables mattered, at a sample size that can support the ranking |
| Controls left out of the space, or a space barely larger than its trial cap | `traigent-optimize-config-space` | build the wider search space this run bounded away |
| Dataset defects, generated examples, or limited coverage | `traigent-dataset-curate` | check, label, deduplicate, and split the customer's own dataset |
| An evaluator was generated, repaired, uncalibrated, or too thin | `traigent-eval-audit` | validate the customer's evaluation policy before adopting a working copy |
| The user wants to re-read this run's own result rather than pay for another | `traigent-analyze-results` | read the winner, trials, and trade-offs from the terminal |
| The earned next move is a larger search | `traigent-optimize-run` | choose algorithm, trial count, and cost limit for a full-scale run |

Measured defects remain findings; causal claims about controls remain hypotheses this run is too
small to settle. Recommend testing those hypotheses, never as an established finding. Name no skill that is
not in that repository, and no `npx skills add` flag beyond `--list` and `--skill`.

## Recovery

- Portal persistence `degraded`: trials may be present while summaries lag. Explain and verify the
  link before discarding anything.
- Portal persistence `failed`: recover/sync the existing run when supported; do not repay for a
  rerun by default.
- Permanent HTTP validation error or missing `cloud_url`: surface a sanitized precise backend
  reason; do not replace it with a guessed explanation or claim portal success.
- Tracking degraded to local-only during a connected run: stop paid work at once - the wrapper has
  already refused every later provider call. Report a sanitized backend reason and the spend it
  cost, rather than restarting the phase to recover the link or re-deciding whether to continue.
- Cost ceiling reached, with or without completed trials: show the best partial result where
  trials completed - never a failure, never with the paid trials dropped - and report the phase as
  "Approval and budgets" above states.
- SDK or optimizer exception mid-run, including a Rust/pyo3 panic during result serialization (a
  known class): surface the error in plain language with one recommended recovery, never a raw
  traceback. Completed trials were already paid and written to the selected
  `TRAIGENT_RESULTS_FOLDER` - beneath `traigent-runs/` for the generated wrapper, or at the named
  preserved project path. Recover them and, for a connected run, upload the partial session with
  `traigent sync <session_id>` before reporting - never present already-paid work as a total loss.
  A foreground command timeout can kill `optimize_sync` mid-run without rolling back its spend, so
  run a long paid optimization detached and poll its log rather than letting the tool timeout
  abandon paid trials.
- Rate limit or temporary provider outage: preserve partial results and use the SDK/provider
  classification.
- Invalid credentials, quota exhaustion, or insufficient funds: stop with the specific category;
  do not retry or describe every case as "no tokens." An unfunded OpenRouter key returns HTTP 402 and
  silently fails trials - verify funding before paid work; a free-tier optimization-sample quota
  rejection means shrink the run, not retry blindly. For an uncategorized provider error, surface a
  sanitized provider message rather than guessing a category.
- Timeout with completed trials: show the best partial result. Another bounded pass is offered
  only when a specific hypothesis justifies it, under a newly scoped approval with its extra
  approximate time and cost, and never as the second attempt at the same phase that `Approval and
  budgets` above refuses.
- Timeout with zero trials: diagnose provider latency, a hung call, or setup failure before
  considering another run.
- Evaluator exceptions or all-zero/all-one measures: repair evaluator/data and rerun only after
  calibration, under a newly scoped approval that carries what was already spent.
- Dataset examples that fail under every configuration: inspect gold/reference and evaluator
  policy before blaming the model.
- Environment creation, installation, or installed-preflight failure: preserve every existing
  environment and stop with the chosen environment's absolute path and the concrete failure,
  quoting pip's own message for a failed install. Recommend inspecting it, or remove and recreate
  only the throwaway environment after explicit user approval; a failed install into the
  customer's own environment offers the throwaway route instead, and nothing falls back to a
  shared or dependent environment.

For generated wrappers, set the process-only SDK results folder to a child of `traigent-runs/`
before importing Traigent so its local optimization logs and state remain inside the ignored
walkthrough directory. Store no secrets, raw private content in run names, or prompts/outputs in
numeric telemetry, and keep error text and metadata recorded with the run content-free.

### Run record and resuming

Keep its stage-status block current from the moment the record exists: at every stage boundary and
before every stop-and-wait, mark each stage done, in progress, or skipped with the reason; the
next stage is always the first neither marked done nor skipped. A session finding
`traigent-runs/run-plan.md` with a matching target and agent - target plus the recorded task answer
when the agent line is `none discovered` - begins resume validation rather than automatically
restarting: read it top to bottom and treat its status and results as resume hints. Independently
verify the target and agent, rerun the cheap read-only/free gates required by the next action,
including execution-evaluator scope and call-path checks, and verify a paid artifact before quoting
it.
After that verification, continue through free work at the first stage neither marked done nor
skipped. For this unfinished run's completed setup, first apply the same-run environment
verification in Environment and privacy. Continue the remaining setup without repeating creation
or installation only when that verification passes. The record may avoid repeating paid work,
never waive a safety precondition.
Recorded scores, spend, completed paid results, and the opening score stand; recorded approvals do
not. Open with where the run stands, not the opening message. Before a new or restarted provider,
private-data, connected Traigent, or other approval-gated external call, re-ground in the latest
user approval in the current conversation and confirm it covers the remaining recipients/data,
scope, runtime, and ceiling. If absent, revoked, or insufficient, re-render that remaining-scope
card and obtain explicit approval; the record alone grants no authority. Before that call, compute
the current comparison invariants and compare them byte-for-byte with the pre-baseline invariants
recorded after free validation; never rewrite the recorded invariants. They are the objective,
agent/call behavior, exact tuning and held-out rows, evaluator, and baseline model/value set. The
only permitted objective difference is a recorded removal of unavailable secondary cost before a
later planned operation under Missing cost or usage telemetry; the primary criterion and direction
stay fixed, and the original objective history remains recorded. Validate that disclosed transition
instead of restarting or repeating paid work. The enhanced space is deliberately excluded because
it must add controls; before a connected call,
verify separately that it retains every recorded baseline model/value and that its only additions
exactly match the freshly rendered and approved enhanced card. If the invariants are incomplete or
differ beyond that recorded cost-only transition, do not resume this run: rename the old record to
the next unused
`traigent-runs/run-plan-historical-<YYYYMMDDTHHMMSSZ>.md` (never overwrite), keep its spend and results
historical or baseline-only, copy a fresh template to canonical `traigent-runs/run-plan.md`, start
at section 1 with a new opening score; the operating contract owns re-running paid work. That
opening score re-reads the agent, because the old record's readiness directories are historical
with it: an opening score over an old reading is not one. Observe a live process, but never restart or expand it from the record alone. A record with every
stage done or skipped is finished, not a resume point. The operating contract owns the mismatch
rule.

### The run log

Every event named below gets a line in `traigent-runs/run-log.jsonl`, appended when it happens
rather than at the end of the stage. It exists so a person handed this directory can say where the run stopped and
why. The record says what is true now, the log says when it happened and whether it cleared. Where
the record already holds a finding - the portal probe's pass/fail among them - that field keeps the
value and the log's line does not restate it.

**The file is append-only: a line, once written, is never rewritten, and nothing in the run reads
it back as run state.** What that gives up is a count and the time of the latest encounter: a
problem is stamped when it was first met.

| Key | What it holds |
|---|---|
| `ts` | `YYYYMMDDTHHMMSSZ` as SKILL.md defines it, on the write of this line |
| `event` | `blocked`, `stopped`, or `warning` |
| `stage` | the run record's stage, 1 to 8 - the internal numbering, not the `n/5` the user saw |
| `class` | a string, one value from that event's own closed set below. Never authored prose - the same failure met twice has to land on the same class, and a sentence written twice will not |
| `state` | `open` when it happens, `cleared` when it stops applying |
| `detail` | one sentence, under the allowlist below |

`event`, `stage`, and `class` together are the identity. Write one `open` line when that identity
first occurs and one `cleared` line if it later clears; nothing else is ever written for it. A problem that recurs after clearing opens again and is visible as the second `open` line,
so flapping survives while a silent retry loop does not.

Read it by collapsing on that identity, last line wins. A `blocked` or `stopped` identity left
`open` is where the run stopped. `refused-trial` and `untracked-cost` never stop applying; a
`cap-standing` clears when the revalidation gate lifts that cap, so a finished run ends with
whatever it met and did not clear still standing. `traigent-runs/run-plan.md` remains the only resume authority. The log belongs to the record beside
it, so a fresh record starts a fresh log and no `cleared` from an earlier run is read as this one's.

Each event names what its `class` may be.

- `blocked` - waiting on the user: `approval`, `key`, or `answer`. Written before every
  stop-and-wait that happens after the record exists, which is what says where a stuck run stopped.
- `stopped` - this run cannot go on, or a phase ended early. A gate this guide defines refused:
  `credential-file-tracked`, `ignore-check`, `readiness-cap`, `invariants`. A
  bundled script could not run, or a command failed to execute: `tool`, with its exit status in
  `detail`. A provider, portal, or Traigent refusal, under the category this file already gives it:
  `authentication`, `key-scope`, `account-access`, `quota`, `rate`, `validation`. The run or a phase
  ended early for its own reasons: `timeout`, `cost-ceiling`, `outage`, `persistence` - which is a
  degradation that carries no refusal category, so a refusal that halts the run keeps its own. And
  `uncategorized`, for anything the four groups above do not name, the provider error this file
  elsewhere says to surface without guessing a category among them.
- `warning` - observed, and able to distort the result without stopping the run: `containment`,
  `refused-trial`, `untracked-cost`, `cap-standing`, or `uncategorized`. The first is the evaluator
  check of the original evaluator that the scope gate declined; any supplied or copied-actor
  result is interpreted under the scope gate above. The warning itself stops no work. Recording it under the event above would say, in the artifact a
  user hands to somebody else, that a completed run had halted. Nothing that halts the run is one of these,
  however it presents: tracking that degrades to local-only stops paid work, so it is a `stopped`.

`detail` and the `class` beside it carry the event and nothing else: one sentence naming what
happened, with no path, no id, no session or account address, no user or machine name, no secret or
access code, no provider error body, and no text or identifier taken from the project's data. This
is the file a user may hand to somebody else, so it names the class of thing that failed rather than
the instance.

It exists once the record does, under the same anchoring condition, and nothing is backdated into
it afterwards.

Run `scripts/validate_run_log.py --log traigent-runs/run-log.jsonl` through the selected Python,
from the script's literal absolute path under the resolved skill directory, before every
stop-and-wait that happens after the record exists, and before this run names the file to the user. It opens
the log read-only and refuses what the paragraphs above state; its own docstring carries the list,
including the five things the allowlist names that no checker can settle. Its docstring states what each exit means; exit 3
routes as it does for every bundled script. A rejected line is reported to the user with what it
carries.
