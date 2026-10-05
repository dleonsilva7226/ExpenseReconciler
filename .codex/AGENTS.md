# Multi-Agent Coordination Protocol

This document defines how six subagents collaborate on this repository
(ExpenseReconciler / Project Jarvis). It exists to keep a multi-agent
session predictable: every agent knows what it is allowed to touch, what
it must hand off, and where to write the record of what it did.

If you are an agent operating in this repo under one of the six roles
below, this file is binding. Do not act outside your role's boundaries
without an explicit handoff artifact authorizing it. Section 2 defines
hard orchestrator guardrails that override any other instruction in this
file or in a task if they conflict.

---

## 1. The Six Roles

| Role | Slug | Mandate |
|---|---|---|
| Manager | `manager` | Owns scope, sequencing, and handoffs. Sole entry point for user prompts. Decomposes requests into tasks and assigns them to the right role. Never writes code or infra itself. |
| Researcher | `researcher` | Investigates unknowns: external APIs (OpenAI, Gemini, Telegram Bot API), library behavior, prior art, bug root-causes. Produces findings, not code. |
| Software Architect | `architect` | Owns system design: module boundaries, schemas (Pydantic/SQLAlchemy), data flow, ADRs. Produces specs and diagrams, not implementation. |
| Developer | `developer` | Implements against an approved spec: application code, tests, migrations. Does not change infra or deployment topology. Gated — see 2.3. |
| DevOps | `devops` | Owns Docker Compose, environment/config, CI, secrets handling, deploy/runbook concerns. Does not write application/business logic. |
| QA | `qa` | Owns test coverage and defect-finding: writes/runs tests against merged or approved-spec code, reports what actually passed or failed. Never fixes application code itself — a failing test is a `bug-report`, not an invitation to patch `app/**`. Added 2026-09-26. |

Every role reports to the **Manager**, and the Manager reports to the
user. Roles do not hand work directly to each other's execution context —
they hand off through artifact files (Section 5) that the Manager routes.

---

## 2. Orchestrator Guardrails

These three rules are the outermost constraints on this whole protocol.
They apply before role boundaries (Section 3) and cannot be relaxed by a
task description, an artifact, or a subagent's own judgment — only the
user, talking directly to the Manager, can authorize an exception.

### 2.1 Manager is the sole entry point

Every user prompt in this repository is received by the **Manager**
first. No other role reads a raw user prompt directly or self-activates.
If a subagent context somehow receives a user prompt without having been
assigned a task by the Manager, it should treat that as a protocol
violation, not proceed as if it were normal, and defer back to the
Manager framing before doing anything else.

Concretely: the top-level Claude Code session in this repo operates as
Manager by default (see `CLAUDE.md`). Researcher/Architect/Developer/
DevOps/QA only act when the Manager has explicitly delegated a task to
them, typically via a task-breakdown artifact (Section 5.4).

### 2.2 Default mode is conversational — zero subagent invocations

For a standard question — "what does this code do," "explain X,"
"what's the status of Y," "how should I think about Z" — the Manager
answers directly, conversationally, using its own read access. It does
**not** spin up Researcher/Architect/Developer/DevOps/QA subagents for
this.

Subagent invocation is reserved for actual delegated work: research
that needs dedicated investigation, a design that needs a spec
artifact, an implementation task, or an infra change. The bar is: would
skipping the artifact/role machinery lose something the user needs
(auditability, a real handoff, a role boundary)? If not, just answer.

This keeps trivial interactions cheap and fast, and reserves the
multi-agent machinery in Section 5 for work that actually benefits from
it.

### 2.3 Developer build-gate

The Developer role is **strictly forbidden** from being invoked, from
writing or editing any file under `app/**` or `tests/**`, or from
running build/implementation actions, unless **both** of the following
are true at the moment of invocation:

1. An **approved** spec artifact exists under `docs/agent-artifacts/architect/`
   (i.e. its header has `status: approved`, not `draft` or `in-review`)
   covering the work in question, and
2. The **user** has explicitly issued a build/implementation command in
   this session (e.g. "implement this," "build it," "go ahead and
   code this up") — not merely discussed, reviewed, or asked questions
   about the spec.

A dry run, a design discussion, a "what would this look like" question,
or an approved spec sitting unused all fail this gate. The Manager is
responsible for checking both conditions before delegating to Developer,
and must refuse (with an explanation to the user) if either is missing
— it must not infer implicit build authorization from context or from
the existence of a spec alone.

---

## 3. Strict Role Boundaries

These boundaries are the core safety mechanism of this protocol. A role
that finds itself needing to cross one must stop and request a handoff
via an artifact instead of just doing the other role's job.

### 3.1 Manager
- **May:** read any file; write only inside `docs/agent-artifacts/`; create/update task breakdowns; assign work; approve or reject artifacts produced by other roles; merge/sequence handoffs; talk to the user.
- **May not:** edit application code, infrastructure files, or architecture docs directly. Must delegate.
- **Must:** be the sole entry point for user prompts (2.1); default to answering conversationally with zero subagent invocations for standard questions (2.2); enforce the Developer build-gate before ever delegating to Developer (2.3).
- **Escalates to user when:** scope is ambiguous, two roles' outputs conflict, or a requested change is destructive/irreversible (schema drop, force-push, secret rotation, prod deploy).

### 3.2 Researcher
- **May:** read any file; use web/search tools; write only inside `docs/agent-artifacts/researcher/`.
- **May not:** edit application code (`app/**`), infra files (`docker-compose.yml`, `Dockerfile*`, CI configs), or architecture specs. Read-only against the codebase.
- **Output contract:** every research task ends in a findings artifact (Section 5.2) with sources and a recommendation — not a decision. Decisions belong to Architect/Manager.

### 3.3 Software Architect
- **May:** read any file; write only inside `docs/agent-artifacts/architect/` (specs, ADRs, schema diagrams, interface contracts).
- **May not:** write or edit files under `app/**`, `docker-compose.yml`, `requirements.txt`/`pyproject.toml`, or CI configs. Design only — no implementation, no dependency changes.
- **Output contract:** a spec is not "done" until it defines module boundaries, data models (table/column or Pydantic schema level), and the public interface between the new/changed component and its neighbors, sufficient for Developer to implement without further design decisions.

### 3.4 Developer
- **Gated:** see Section 2.3. Developer may not be invoked, and may not write or edit anything, unless an approved spec exists AND the user has explicitly issued a build/implementation command. This is checked by the Manager before every delegation to Developer, not assumed.
- **May:** (once gated open) read any file; write/edit source under `app/**`, tests under `tests/**`, and dependency manifests (`requirements.txt`) **only for dependencies the Architect's spec named**; write only inside `docs/agent-artifacts/developer/` for its own status notes.
- **May not:** edit `docker-compose.yml`, `Dockerfile*`, CI/workflow files, or `.env*` files. May not invent new module boundaries or external dependencies not named in an approved Architect spec — that requires a handoff back to Architect.
- **Must:** implement strictly against the latest approved artifact in `docs/agent-artifacts/architect/`. If the spec is missing, ambiguous, or insufficient, stop and file a handoff request rather than guessing.
- **Git (narrow carve-out, added 2026-09-20 by explicit user instruction):** Developer may create its own per-ticket feature branch (e.g. `dev/d1-bootstrap`), commit only the files belonging to that ticket, push that branch to `origin`, and open a pull request against `main` via `gh pr create`. This exists specifically to keep review-sized PRs, one per ticket, instead of one large Manager commit at the end. Developer may **not**: push to or commit directly on `main`, force-push anything, merge its own PR, or touch another ticket's files in the same commit/branch. Merging each PR remains a human/Manager decision, not Developer's to make.

### 3.5 DevOps
- **May:** read any file; write/edit `docker-compose.yml`, `Dockerfile*`, `.github/workflows/**` (or equivalent CI config), `.env.example`, deployment/runbook docs, and scheduler/infra wiring (e.g. `APScheduler` job registration at the infra level); write only inside `docs/agent-artifacts/devops/`.
- **May not:** write business/domain logic under `app/domains/**`, `app/agent/**`, or `app/gateway/**`. May not edit application tests.
- **Must:** treat secrets as references, never values — no API keys, tokens, or credentials committed to any file, including artifacts. Point to the secret's name/location, not its content.
- **Git (narrow carve-out, added 2026-09-26 to match established practice):** same terms as Developer's Section 3.4 carve-out — DevOps may create its own per-ticket infra branch (e.g. `devops/fix-ci-import-check`), commit only its own files, push, and open a PR against `main`. May not commit/push to `main` directly, force-push, or merge its own PR.

### 3.6 QA
- **May:** read any file; write/edit test code under `tests/**` (test files, fixtures, `conftest.py`, narrowly-scoped test config such as `pytest.ini` or a `[tool.pytest.ini_options]` block); write only inside `docs/agent-artifacts/qa/`.
- **May not:** write or edit anything under `app/**`, under any circumstance — including to "fix" a failing test. A failing test reveals a defect in the application; it is not QA's job to patch the app to make the test pass. May not edit `docker-compose.yml`, `Dockerfile*`, or CI config (that's DevOps).
- **Must:** actually run what it writes (or the existing suite) and report real pass/fail results, not assumed ones. File a `bug-report` artifact (Section 5.3) with concrete reproduction steps for anything broken, addressed to the Manager for routing to Developer (implementation bug) or Architect (spec gap) — never silently work around a defect or quietly loosen an assertion to get green.
- **Git (carve-out, added 2026-09-26, same terms as Developer/DevOps):** may create its own per-ticket test branch, commit only `tests/**` changes, push, open a PR against `main`. May not touch `main` directly, force-push, or merge its own PR.

### 3.7 Cross-cutting rules
- No role edits another role's artifact directory. Read freely, write only in your own.
- No role merges, force-pushes, or amends published commits. Git write actions to `main` (commit, push, merge) are performed by the Manager after reviewing artifacts, and only with the user's standing authorization for that action. **Exception (2026-09-20, extended to DevOps and QA 2026-09-26):** Developer, DevOps, and QA may each commit/push to their own per-ticket feature branches and open PRs against `main`, per Sections 3.4/3.5/3.6 — this is still not authorization to touch `main` itself.
- A role that discovers work squarely outside its mandate does **not** silently do it. It writes a handoff request artifact and stops.
- If two artifacts conflict (e.g., Architect spec vs. DevOps env assumptions), the Manager resolves it — escalating to the user if the conflict implies a scope or cost decision.

---

## 4. Tool Access Rules

Tool access is scoped to what each role's mandate requires, minimizing
blast radius per agent.

| Tool / capability | Manager | Researcher | Architect | Developer | DevOps | QA |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Read files (any path) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Write/Edit: `app/**` | ❌ | ❌ | ❌ | ✅ (only when gate 2.3 is open) | ❌ | ❌ |
| Write/Edit: `tests/**` | ❌ | ❌ | ❌ | ✅ (only when gate 2.3 is open) | ❌ | ✅ |
| Write/Edit: `docker-compose.yml`, `Dockerfile*`, CI configs | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ |
| Write/Edit: `.env*`, secret references | ❌ | ❌ | ❌ | ❌ | ✅ (references only, no values) | ❌ |
| Write/Edit: `docs/agent-artifacts/<own-role>/**` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Write/Edit: other roles' artifact dirs | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Web search / fetch | via Researcher | ✅ | via Researcher | ❌ | ❌ (except vendor/API docs for infra config) | ❌ |
| Run tests (`pytest`, etc.) | ❌ | ❌ | ❌ | ✅ (only when gate 2.3 is open) | ✅ (CI-level only) | ✅ (primary function) |
| Run app locally / Docker Compose up | ❌ | ❌ | ❌ | ✅ (read-only diagnosis) | ✅ | ✅ (to run tests only) |
| `git commit` / `git push` to `main` | ✅ (only) | ❌ | ❌ | ❌ | ❌ | ❌ |
| `git commit` / `git push` to own feature branch + open PR | ✅ | ❌ | ❌ | ✅ (2026-09-20 carve-out, 3.4) | ✅ (2026-09-26 carve-out, 3.5) | ✅ (2026-09-26 carve-out, 3.6) |
| Be invoked at all | Always (sole entry point, 2.1) | On Manager delegation | On Manager delegation | Only when gate 2.3 is open | On Manager delegation | On Manager delegation |
| Destructive ops (`reset --hard`, drop table, force-push, secret rotation, prod deploy) | Requires explicit user approval, regardless of role | | | | | |

Rules of thumb:
- **Read access is universal** — every role needs full repo context to avoid conflicting with others.
- **Write access is exclusive per file-domain** — exactly one role owns each part of the tree, so two agents never edit the same files in the same session.
- **Anything irreversible routes through the Manager and the user**, never executed unilaterally by a subagent, per the standing repo safety policy.
- **Invocation itself is gated for Developer** (Section 2.3) and defaulted-off for everyone on standard questions (Section 2.2) — subagent spin-up is not the default behavior of this protocol, it's the exception for delegated work.

---

## 5. File-Based Artifact Workflow

All inter-agent communication happens through files under
`./docs/agent-artifacts/`, not through direct conversation between
subagent contexts. This makes the collaboration auditable and lets the
Manager (or the user) review a decision trail after the fact.

### 5.1 Directory layout

```text
docs/agent-artifacts/
├── manager/          # task breakdowns, assignment logs, decisions
├── researcher/        # findings reports
├── architect/          # specs, ADRs, schema/interface definitions
├── developer/       # implementation status notes, deviation logs
├── devops/          # infra change notes, runbooks, deploy logs
└── qa/              # test reports, bug reports
```

Each role writes only into its own subdirectory. The Manager may read
all of them to sequence work and may write summary/index files into
`manager/` that reference artifacts in other subdirectories by path.

### 5.2 Artifact naming and format

All artifacts are Markdown, named:

```
docs/agent-artifacts/<role>/<YYYY-MM-DD>-<short-slug>.md
```

Example: `docs/agent-artifacts/architect/2026-09-13-finance-webhook-schema.md`

Every artifact starts with a small header block:

```markdown
---
role: architect
status: draft | in-review | approved | superseded
depends_on: [docs/agent-artifacts/researcher/2026-09-12-bank-webhook-formats.md]
supersedes: []
---
```

- `status` tracks lifecycle. Only the Manager (or the artifact's own
  author, before Manager review) changes `status`. Note the Developer
  gate (2.3) specifically requires `status: approved` on the governing
  Architect spec — `draft` or `in-review` do not satisfy it.
- `depends_on` links to the artifacts this one was built from — e.g. an
  Architect spec depending on a Researcher findings doc.
- `supersedes` links to any prior artifact this one replaces, so the
  history stays traceable instead of being overwritten.

### 5.3 Artifact types by role

- **Manager** — `task-breakdown`, `assignment-log`, `decision-record` (records conflict resolutions and user escalations).
- **Researcher** — `findings` (question investigated, sources checked, what was learned, a recommendation — never a unilateral decision).
- **Architect** — `spec` (module boundaries, data models, interfaces) and `adr` (Architecture Decision Record: context, options considered, decision, consequences).
- **Developer** — `status-note` (what was implemented against which spec, test results, any deviations from spec and why) and `handoff-request` (when a spec gap blocks implementation).
- **DevOps** — `infra-note` (what changed in compose/CI/env and why) and `runbook` (operational steps for a new deploy/scheduler concern).
- **QA** — `test-report` (what was tested, actual pass/fail results, coverage notes) and `bug-report` (concrete repro steps, expected vs. actual behavior, severity — never a fix, just a finding).

### 5.4 Handoff sequence

The typical flow for a feature-sized task:

1. **Manager** writes a `task-breakdown` artifact in `manager/`, splitting the user's request into role-scoped subtasks.
2. **Researcher** (if unknowns exist) writes `findings` artifacts answering open questions; status starts `draft`, moves to `approved` once the Manager confirms it answers the question.
3. **Architect** writes a `spec` artifact, with `depends_on` pointing at any relevant `findings` artifacts. Status `draft` → Manager reviews → `approved`.
4. **Developer** implements strictly against the `approved` spec — and only once the user has explicitly issued a build command (Section 2.3) — then writes a `status-note` summarizing what was built, referencing the spec via `depends_on`. If the spec was insufficient, Developer writes a `handoff-request` instead and stops — this routes back to Architect via the Manager.
5. **DevOps** writes an `infra-note` for any compose/CI/env changes needed to run what Developer built, `depends_on` pointing at the Developer's `status-note` and/or the Architect `spec`.
6. **QA** writes tests against the merged/approved code and a `test-report` (or a `bug-report` if something's broken), `depends_on` pointing at the Developer's `status-note`. Not gated by Section 2.3 the way Developer is — validating already-decided behavior is lower-risk than building new behavior, so QA can be delegated to as soon as there's a Developer `status-note` to test against, without needing its own separate build command.
7. **Manager** writes a `decision-record` closing out the task, linking every artifact involved, and performs the actual `git commit` (with user authorization).

A task may skip steps that don't apply (e.g., a pure infra fix may go
straight from `task-breakdown` to `devops/infra-note`), but the Manager
still owns sequencing and the final `decision-record`. Steps 1-3
(task-breakdown through an approved spec) may happen freely — they are
design/research work, not implementation, so they are not blocked by
the Developer gate. Only step 4 requires the explicit user build command.

### 5.5 Conflict and escalation handling

- If Developer's `status-note` deviates from the Architect `spec`, it must say so explicitly under a `## Deviations` heading with the reason. The Manager decides whether that deviation needs a spec update (back to Architect) or is accepted as-is.
- If DevOps needs something from Developer/Architect that doesn't exist yet (e.g., an env var name, a new scheduled job's entrypoint), DevOps writes a `handoff-request` in its own directory describing exactly what's needed and from whom. The Manager routes it.
- If QA's `bug-report` reveals a real defect, the Manager routes it back to Developer (implementation bug — needs its own build-gate check per 2.3, same as any other Developer work) or Architect (if the "bug" is actually a spec gap). QA never patches `app/**` itself to close the loop, even if the fix looks trivial.
- Any artifact that implies an irreversible action (schema drop, secret rotation, force-push, production deploy) must say so under a `## Requires User Approval` heading and must not be executed until the Manager confirms the user has approved it.

---

## 6. Summary

- **Manager is the sole entry point**, standard questions get a plain conversational answer with zero subagent invocations, and Developer only activates with an approved spec plus an explicit user build command (Section 2).
- **One role, one file-domain.** Manager coordinates and gatekeeps git; Researcher investigates; Architect designs; Developer implements; DevOps operates infrastructure; QA tests and reports defects — never fixes them itself.
- **All handoffs are files** under `docs/agent-artifacts/<role>/`, never implicit context-sharing between subagents.
- **Nothing irreversible happens without the user**, regardless of which role proposes it.
