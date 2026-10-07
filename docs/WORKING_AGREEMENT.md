# Working agreement (reusable across projects)

## Developer profile

- Reads a lot and understands software and ML concepts, but is new to implementing full projects.
- Goal is learning that sticks: speedrun a working v1, study reference books, then revisit
  modules and try alternative implementations to understand the tradeoffs.
- Target: machine learning engineer interviews. The developer must be able to explain and
  extend everything in the ML path.
- The developer also wants hands-on experience with production operating conditions.
  Use staged workload and failure/recovery exercises to practice observing and diagnosing
  a system, alongside the modeling work.

## Two modes

**Scaffold mode** (default for everything outside the ML path): generate freely. Project setup,
docker, CRUD endpoints, auth, forms, admin screens, migrations, frontend. Explain briefly what
was created and how to run it.

**Learn mode** (for the ML path: `backend/app/ml/**`, `backend/app/logging/**`,
`backend/app/experiments/**`, and anything that touches ranking or embeddings):
1. Explain the approach and its main alternative in a few sentences before writing code.
2. Write the skeleton with clear interfaces, types, and TODO markers for the core logic.
3. Let the developer write the core logic. If they ask you to write it, do so, but walk
   through it line by line afterwards.
4. Review their code: correctness first, then one or two things a Pinterest interviewer would ask about.

## Checkpoints

- After finishing a module, ask 2–3 explain-back questions (how it works, what breaks at
  scale, what the alternative would be). Do not grade harshly; point to gaps.
- After any significant choice, append an entry to docs/DECISIONS.md.
- When a module is built, note the matching revisit experiment from PLAN.md so it is not lost.
- For each ML milestone, name a baseline or correctness invariant, record a reproducible
  comparison, and use the explain-back outcome in PLAN.md. A well-explained result that
  does not beat the baseline still counts as learning.
- For an operational exercise, record the workload, expected behavior, measured symptoms,
  diagnosis, and recovery. Let the developer reason through the evidence before supplying
  the full explanation; scaffold the surrounding tooling as needed.

## Style

- Prefer simple, readable code over clever code; this codebase is also study material.
- Name things after what they are in industry (candidate source, ranker, reranker, impression)
  so the vocabulary carries over to interviews.
- When something is a deliberate simplification of how production systems work, leave a
  one-line comment saying so and what production would do instead.
