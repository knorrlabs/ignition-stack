# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Pull Request Titles

Write every PR title as a Conventional Commit, `type(scope)!: subject` with the scope and `!` optional, such as `feat: add module version manager and pre-install modules in create`. The generated release notes list PRs by title, and `.github/workflows/pr-labels.yml` labels each PR from it:

| Title | Label | Release notes section |
|-------|-------|-----------------------|
| any type with the `deps` scope, such as `chore(deps):` | `dependencies` | Dependencies |
| `feat` | `enhancement` | Features |
| `fix` | `bug` | Bug Fixes |
| `docs` | `documentation` | Documentation |
| `build`, `chore`, `ci`, `perf`, `refactor`, `revert`, `style`, `test` | `maintenance` | Maintenance |

- Renovate's `security` label puts a PR under Security, ahead of every row above.
- Any other title gets no label and lands under Other Changes.
- To move a PR to another section, retitle it. The workflow reruns on edit and swaps its label.
- Use the `deps` scope only for dependency updates.
- Branch names don't affect labels.
- Write commit messages in the same form: a single-commit PR's squash commit takes the commit message, not the PR title.
