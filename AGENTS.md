# PromptMeld repository instructions

## GitHub publication

Use the dedicated `build\github-publish` checkout for every PromptMeld commit,
push, pull request, tag, or release. Do not publish from the development
checkout, even when it is already on a feature branch.

For a pull request:

1. Run `gh auth status` in the normal Windows user context. If the sandbox sees
   a different credential store or reports dubious repository ownership, use
   the normal user context rather than adding a broad global `safe.directory`.
2. Confirm the development worktree's intended scope with `git status -sb`,
   `git diff --stat`, and `git diff --check`.
3. In `build\github-publish`, fetch `origin --prune`, require a clean worktree,
   and create a new `codex/<description>` branch from the current
   `origin/main`. Never reuse an old or previously merged publication branch.
4. Transfer only the verified source, test, documentation, and version files.
   Confirm the transferred files are byte-identical to the tested development
   worktree.
5. Run the complete test suite and relevant package/helper smoke tests before
   publication. For a distributable release, increment `project.version`, build
   the application, then build and hash the matching installer.
6. Stage files by explicit path. Do not use `git add -A` in a mixed worktree,
   and never commit `build`, `dist`, installers, secrets, logs, or local caches.
7. Run `git diff --cached --check`, inspect the staged diff/stat, commit, push
   with upstream tracking, and open a draft pull request against `main` unless
   the user explicitly requests ready-for-review status.
8. Read the pull request back from GitHub and verify its base, head, commit,
   draft state, and changed-file count before reporting success.

Direct pushes to protected `main` are not the PromptMeld publication path.
Changes intended for `main` must go through a pull request and merge.
