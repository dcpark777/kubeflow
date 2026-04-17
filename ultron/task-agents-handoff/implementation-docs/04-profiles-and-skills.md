# 04 — Profiles and skills

This is the content layer. Eight markdown files (six profiles, two
skills) that define how Claude behaves mid-execution. No code.

Drop these in early — the pipeline references them by path and will
fail if they're missing.

## Profiles

**Location**: `task_agents/profiles/`

**Files to create** (all `.md`):

```
planning-execute.md
planning-refine.md
brainstorming-execute.md
brainstorming-refine.md
coding-execute.md
coding-refine.md
research-execute.md
research-refine.md
```

A reference draft of planning/brainstorming/coding (both modes) exists
in the source package this plan is derived from — use them as the
starting point. Research profiles are NOT drafted and need to be
authored from scratch.

### Profile anatomy

Every profile has five sections, in this order:

1. **Header** — `# Profile: {Type} ({mode})`
2. **How to behave** — 3-6 bullets describing the mode. Not abstract
   principles ("be helpful") but specific behaviors ("Commit to a
   recommended path; hedged plans are useless").
3. **Tool posture** — which tools to lean on, which to avoid in this
   mode.
4. **Output contract** — the shape of the deliverable. Section
   structure, what "done" looks like, what NOT to produce.
5. **(optional) Anti-patterns** — common failure modes for this mode.
   Not required but helpful for fiddly modes.

Length target: 40-80 lines per profile. They get injected into every
execution in this mode; long profiles are expensive and ignored.

### Execute vs refine

**Execute profiles** produce the actual deliverable. The output
contract should spell out exactly what shape the user gets.

**Refine profiles** run during the chat-to-sharpen loop. They have a
different output contract per turn:

1. A one-sentence reflection of what the task is (so the user can
   correct cheaply).
2. 1-3 gaps to clarify, each with a proposed default (not an open
   question).
3. A proposed revised task description the user can accept or edit.

Refine profiles must NOT start executing the task. If Claude catches
itself outlining the plan or writing code during refinement, it
should stop.

### Research profiles (not yet drafted)

For `research-execute.md`:

- Behavior: lead with the synthesis, not the journey. Cite sources
  where factual claims matter. Distinguish what's established from
  what's contested. Commit to a recommendation if the task asks for
  one, and say so explicitly if it doesn't.
- Tools: web_search liberally. web_fetch for specific sources the
  user referenced. File tools for attached context.
- Output contract: summary, key findings (with sources), points of
  disagreement or uncertainty, recommendation if applicable.

For `research-refine.md`:

- Gaps to surface: decision the research will inform; scope (which
  dimensions to compare); acceptable sources / evidence bar;
  deliverable shape (brief? comparison table? decision memo?).
- Cap at sonnet in the selector (refine profiles are conversational
  by nature).

Model prior drafts on the planning and coding profiles' style and
length.

## Skills

**Location**: `task_agents/skills/`

**Files**:

```
task-refinement/SKILL.md
plan-decomposition/SKILL.md
```

These are the procedural "moves." They get loaded by Claude when a
specific procedure applies during execution. They don't know about
profiles — they just work when called.

### Skill anatomy

Every skill has YAML frontmatter + markdown body:

```markdown
---
name: skill-name
description: When this triggers. Be slightly "pushy" — skills tend to
  undertrigger. Include both what the skill does AND specific contexts
  that should trigger it.
---

# Skill title

## The core move

What this procedure does, concretely.

## When to use it

When to reach for this. Concrete examples of triggering contexts.

## The procedure

Step-by-step instructions for doing the move well.

## Anti-patterns

Failure modes to avoid.
```

Length target: 80-200 lines. Skills can be longer than profiles
because they're loaded on-demand, not always.

### task-refinement

Triggers on any refinement-style conversation. Independent of task
type — the procedure is the same whether you're refining a planning
task or a coding task.

Core moves:
- **Reflect** the current understanding in one sentence
- **Probe** the 1-3 gaps most likely to cause a bad outcome
- **Propose defaults** (not open questions)
- **Draft** a revised task description
- **Check for done** — stop when the task is executable

Anti-patterns:
- Refining into planning (if you catch yourself planning, stop)
- Exhaustive questioning (ten questions per turn is a failure)
- Echo refinement (restating without sharpening)
- Over-formalization (not every task needs an acceptance matrix)

### plan-decomposition

Triggers when the task involves turning a goal into a sequenced,
actionable plan. Loaded during planning-execute sessions when Claude
recognizes it's decomposing.

Core test for a plan step:
1. Could someone start this in the next hour?
2. Would two different people doing this produce similar output?
3. Is "done" visible?

A step failing any of these needs further decomposition.

Structure for the plan:
- Goal (one sentence)
- Approach (2-4 sentences)
- Milestones (4-8 of them, each with outcome + key work + dependencies + size)
- Risks (2-4 specific, with mitigations)
- Assumptions
- Paths not taken (optional)

Anti-patterns: milestone soup, phantom precision, risk theater,
activity-as-milestone ("research vendors" vs "vendor shortlist ready").

## Deployment to Claude Code

Skills must be discoverable by Claude Code at runtime. Two options:

1. **User-scope**: drop files into `~/.claude/skills/{name}/SKILL.md`.
   Available across all sessions for the logged-in user.
2. **Project-scope**: drop into `{project}/.claude/skills/{name}/SKILL.md`.
   Available only when Claude Code is launched in that project.

For an app backend, project-scope is cleaner — each task's execution
directory can include a `.claude/skills/` symlinked or copied from the
package. User-scope is simpler but pollutes the dev's environment.

The pipeline shouldn't worry about this; it's a deployment concern.
Document it in the deploy runbook.

## Profiles and skills are orthogonal

A profile is a persistent mode (the whole session). A skill is a
triggered procedure (loaded mid-session when applicable).

The planning-execute profile sets the mode ("you're making a plan,
here's the output contract"). When the agent is mid-plan and needs to
decompose a goal into milestones, it loads the plan-decomposition
skill for the specific procedure.

Don't try to bake skill content into profiles or vice versa. The
separation is load-bearing: profiles stay short, skills stay bounded,
and neither has to duplicate the other's content.
