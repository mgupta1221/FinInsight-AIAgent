# AGENTS.md — working agreement for AI assistants

These rules apply to any LLM/agent (Claude Code, Copilot, Cursor, etc.) operating in this project.

## Git — never automate

- **Never run `git commit`, `git push`, or create tags, branches, or PRs on your own.**
- Do these **only** when the user explicitly asks in that message (e.g. "commit this", "push to
  origin"). A general instruction to "build" / "fix" / "add a feature" is **not** permission to commit
  or push.
- **Read-only** git commands (`git status`, `git diff`, `git log`) are fine any time.
- When changes are ready, **stop and tell the user** what changed and suggest the git commands — let
  them run them (or ask first and wait for a clear yes).
- Never commit secrets or generated data: `.env`, `*.crt`, the report PDFs, `store/`, `data/parsed/`.
  (`.gitignore` already blocks these — do not override it.)

## General

- Prefer small, reviewable changes. Explain what you did and why.
- Don't delete or overwrite the user's files without saying so first.
- Keep `BUILD_PLAN.md` as the source of truth for scope and architecture.
