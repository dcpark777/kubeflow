---
name: task-refinement
description: Use this skill when refining, sharpening, or clarifying a task before execution — whenever the user is iterating on a task description rather than asking you to perform it. Trigger on phrases like "let me refine this," "help me make this task better," "is this specific enough," or any conversation where the user is editing a task's scope, goals, or constraints. Also trigger when you notice a task prompt is ambiguous enough that executing it would likely produce the wrong result. This skill is independent of task type (planning, coding, research, brainstorming) — use it whenever the move is "sharpen the ask."
---

# Task refinement

Refinement is a distinct phase from execution. The user isn't asking
you to do the task — they're asking you to help them describe it well
enough that someone (you or another agent) can do it successfully.

Good refinement ends with a task description that a competent executor
would read once and start working from, without needing to ask
clarifying questions mid-flight.

## The core loop

Each refinement turn has the same shape:

1. **Reflect** — one sentence on how you currently understand the task.
   This gives the user something concrete to correct.
2. **Probe** — surface the 1–3 gaps most likely to cause a bad outcome.
   Not every gap — the ones that matter.
3. **Propose** — for each gap, propose a default the user can accept,
   rather than asking an open question.
4. **Draft** — a rewritten task description incorporating the proposed
   defaults. The user edits or accepts.
5. **Check for done** — is the task ready to execute? If yes, say so
   clearly.

This loop is cheap. Run it once per user turn; don't try to do five
rounds in one response.

## What makes a gap worth surfacing

Not all ambiguity is worth fixing. A gap is worth surfacing when the
answer changes what gets built. Litmus test: "if the executor assumed
A vs. B here, would the output look meaningfully different?" If yes,
surface it. If not, let it slide.

High-value gaps, in rough order:

- **Success criteria** — what does "done" look like? This is
  under-specified in ~80% of tasks.
- **Scope edges** — what's explicitly out? Users often forget to say
  what they *don't* want touched.
- **Constraints** — budget, timeline, tools allowed, style to match
- **Audience / consumer** — who reads this, runs this, uses this?
- **Format** — what shape is the deliverable?

Low-value gaps (don't ask):

- Preferences the user clearly hasn't thought about and doesn't care
  about (pick a reasonable default silently)
- Things you can infer from context
- Things that would only matter in edge cases the user hasn't hit

## Proposing defaults, not asking open questions

Open questions put the work on the user. Proposed defaults put the
work on you. Example:

**Weak (open question):**
> What format should the output be in?

**Strong (proposed default):**
> I'll deliver this as a single markdown file with sections for
> context, findings, and recommendations. Sound right?

The user can say "yes" with one word, or correct you with one
sentence. Either is faster than them composing an answer from scratch.

## Knowing when to stop

Refinement has diminishing returns. Stop when:

- The remaining ambiguities are small enough that reasonable defaults
  would produce acceptable outcomes
- The user signals satisfaction ("looks good," "let's go," "that's it")
- You've run the loop 3+ times and are chasing diminishing sharpness

Say it explicitly: "I think this is ready to execute. Want me to go,
or is there more to sharpen?"

## The handoff

When refinement finishes, produce a clean final task description — not
a summary of the conversation. The executor shouldn't need to read the
refinement transcript. Everything they need should be in the final
description.

A good final description has:

- The goal in one sentence
- The success criteria
- The scope (including what's out)
- Relevant constraints
- The expected deliverable format

## Anti-patterns

- **Refining into planning.** If you catch yourself outlining *how* to
  do the task, you've drifted out of refinement. Stop. The plan
  belongs in execution.
- **Exhaustive questioning.** Ten questions per turn is a refinement
  failure mode. Three is a ceiling; one well-chosen question is often
  better.
- **Echo refinement.** Restating the task back in slightly different
  words without actually sharpening anything. Every turn should move
  the description forward.
- **Over-formalization.** Not every task needs an acceptance test
  matrix. Match refinement depth to task stakes.
