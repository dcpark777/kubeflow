# AI Tooling for the ML Platform Team

A working catalog of AI-powered tools to scale platform support across a team of ~20 data scientists, organized by leverage and effort. The premise: a single platform engineer cannot manually review every PR, answer every question, and propagate every standard. AI is the mechanism for encoding judgment into substrate that scales without you in the loop.

## The underlying philosophy

Most of the tools below are instances of a small number of patterns:

- **Encoding tacit knowledge as substrate.** Standards, decisions, failure modes, and platform opinions live in your head and in scattered Slack threads. Convert them into machine-readable form (skills, audit rules, decision archives, lineage graphs, incident libraries) so AI can mediate access to them.
- **Closing latent feedback loops.** Drift, cost, depr