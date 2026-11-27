# AGENTS.md — working agreement for AI assistants

These rules apply to any automated coding assistant operating in this project.

## Git — never automate

- **Never run `git commit`, `git push`, or create tags, branches, or PRs on your own.**
- Do these **only** when the user explicitly asks in that message (e.g. "commit this", "push to
  origin"). A general instruction to "build" / "fix" / "add a feature" is **not** permission to commit
  or push.
- **Read-only** git commands (`git status`, `git diff`, `git log`) are fine any time.
- When changes are ready, **stop and tell the user** what changed and suggest the git commands — let
  them run them (or ask first and wait for a clear yes).
- Never commit secrets or generated data: `.env`, `*.crt`, `store/`, `data/parsed/`.
  (Until 27 Nov 2026 this list also named the report PDFs. The team decided to include the 30 annual reports
  in `data/manual-collection/` for the submission.)
  (`.gitignore` already blocks these — do not override it.)

## General

- Prefer small, reviewable changes. Explain what you did and why.
- Don't delete or overwrite the user's files without saying so first.
- Keep `BUILD_PLAN.md` as the source of truth for scope and architecture.
