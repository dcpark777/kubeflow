---
name: plan-decomposition
description: Use this skill when turning a goal, project, or initiative into a concrete, sequenced plan with milestones, dependencies, and risks. Trigger on phrases like "plan out," "how should I approach," "break this down," "roadmap," "what steps," or any request where the user has a desired outcome and needs a path from here to there. Use this even when the user doesn't say "plan" explicitly — if they're describing a multi-step effort and asking what to do, this skill applies. Especially important for technical migrations, project kickoffs, and any effort spanning more than a few days of work.
---

# Plan decomposition

A plan is useful when each step is something a person could start on
Monday morning. Plans that bottom out at "figure out X" or "handle
the Y situation" aren't plans — they're restatements of the goal with
more words.

The skill here is knowing when you've decomposed enough, and when
you've decomposed too much.

## The decomposition test

For each step in your plan, ask:

1. **Could someone start this in the next hour?** If no, decompose
   further.
2. **Would two different people doing this produce similar output?**
   If no, the step is under-specified.
3. **Is "done" visible?** If you can't describe what finished looks
   like, the step isn't ready.

A step that fails any of these needs to be broken down or sharpened.
A step that passes all three is ready.

## When to stop decomposing

Over-decomposition is as bad as under-decomposition. A plan with 47
sub-sub-tasks nobody will read is worse than a plan with 6 milestones
the team will actually follow.

Stop decomposing when:

- The next level down is obvious tactical detail the executor will
  figure out
- The decomposition would be speculative (you don't yet know what's
  inside milestone 5 because milestone 2 will reshape it)
- The plan is already actionable at the current level

Rule of thumb: 4–8 top-level milestones for most efforts. More than
10 is usually a sign of over-decomposition or a goal that should be
split into separate efforts.

## Structure the plan emits

```
# Plan: [goal in user's language]

## Approach
[2–4 sentences on the shape of the solution. Why this approach over
alternatives. What the plan is NOT trying to solve.]

## Milestones

### 1. [Milestone name]
- **Outcome:** [what exists / is true when this is done]
- **Key work:** [2–4 bullets on what gets done]
- **Depends on:** [previous milestones, or "none"]
- **Rough size:** [days / weeks / sprints — coarse is fine]

### 2. [Milestone name]
...

## Risks
- **[Specific risk]** → [concrete mitigation]
- **[Specific risk]** → [concrete mitigation]

## Assumptions
- [Assumption 1]
- [Assumption 2]

## Paths not taken (optional)
- [Alternative approach] — [why not]
```

## Writing good milestones

Good milestones are *outcomes*, not activities. Compare:

**Weak (activity):**
> Research vendor options

**Strong (outcome):**
> Vendor shortlist of 3 with cost and capability comparison

The second tells you when you're done. The first is open-ended.

Name milestones with nouns and past-tense-feeling verbs:
- "API contract defined" > "Define the API"
- "Feature flag rollout complete" > "Roll out the feature flag"
- "Migration playbook drafted" > "Write migration docs"

## Writing good risks

Generic risks are noise. "The timeline might slip" is true of every
plan ever written. A useful risk is specific enough that you could
imagine it happening, and has a mitigation that's actually different
from the default plan.

**Weak:**
> Risk: technical challenges

**Strong:**
> Risk: the existing auth system's session format is undocumented,
> and the migration might hit edge cases we haven't seen. Mitigation:
> spend the first 2 days auditing session payloads across prod logs
> before committing to the migration approach.

Aim for 2–4 risks. One or two specific risks is better than ten
generic ones.

## Handling unknowns

Plans are written under uncertainty. Handle that honestly:

- If a milestone depends on information you don't have, make
  "gather that information" the first milestone and keep later ones
  deliberately less detailed.
- If two approaches are both viable and you can't tell which is
  better without more info, pick one, note the other under "paths
  not taken," and flag the decision point.
- If the goal itself seems under-specified, say so — don't produce
  an elaborate plan on a shaky foundation.

## Anti-patterns

- **Milestone soup.** Flat list of 15 items with no sequencing. A
  plan needs a shape.
- **Hedging through the main path.** "Could do X or Y or Z" in the
  milestone body. Pick one; put alternatives under "paths not taken."
- **Phantom precision.** Week-by-week breakdowns for a 6-month effort
  where milestone 4 is speculative. Be coarse where you're
  uncertain; be precise where you're confident.
- **Risk theater.** Filling the risks section with generic items to
  look thorough. Two real risks > ten fake ones.
