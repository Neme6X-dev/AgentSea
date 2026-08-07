# Core Rules for Git: Real-World Engineering Practices

This guide summarizes key Git practices, branch & commit conventions, common mistakes to avoid, conflict resolution procedures, and recovery tools.

---

## 1. Core Conventions

### Branch Naming
Format: `<type>/<short-description-in-kebab-case>`

* **`feature/`**: New functionality (e.g., `feature/user-registration`, `feature/direct-message`).
* **`fix/`**: Correcting bugs in existing code (e.g., `fix/login-segfault-on-empty-password`).
* **`refactor/`**: Restructuring code without changing behavior (e.g., `refactor/extract-network-layer`).
* **`test/`**: Adding or fixing automated tests (e.g., `test/add-criterion-test-framework`).
* **`chore/`**: Build system, configuration, dependencies (e.g., `chore/setup-makefile-and-gitignore`).
* **`docs/`**: Documentation updates only (e.g., `docs/update-readme-build-instructions`).

*Anti-pattern examples:* `test`, `fix`, `wip`, `paul`, `new-feature`, `FINALFINAL`, `main2`.

---

### Commit Messages (Conventional Commits)
Format: `<type>(<scope>): <short imperative description>`

```text
feat(auth): implement user registration with hashed passwords
fix(server): prevent crash when client disconnects mid-send
refactor(client): extract command dispatcher to separate module
test(auth): add unit tests for password hashing edge cases
chore(build): link libcriterion in Makefile
```

*Rules:*
1. State what action was taken in the imperative present tense ("implement", not "implemented").
2. Use well-defined scopes mapping to architecture layers (`auth`, `team`, `channel`, `message`, `server`, `client`, `protocol`, `db`, `test`, `build`).
3. Avoid vague messages like `fix`, `wip`, `done`, `it works`, `update`, `debug`.

---

### `.gitignore` Requirements
Create a `.gitignore` in the repository root as the **very first commit** before adding code.

* Exclude compiled binaries, object files (`*.o`, `*.a`, `*.so`), build dirs (`build/`).
* Exclude local runtime files, database files (`*.log`, `server.db`).
* Exclude secrets and configuration (`.env`).
* Exclude editor and OS metadata (`.DS_Store`, `.vscode/`, `.idea/`, `*.swp`).

---

## 2. The 10 Essential Git Rules & Anti-Patterns

### 1. Never Commit Directly to `main`
* **Rule:** `main` must represent clean, tested code that compiles at all times. Enable branch protection on `main` to enforce Pull Requests (PRs).
* **Workflow:**
  ```bash
  git checkout main
  git pull origin main
  git checkout -b feature/channel-create-delete
  # ... work, test, commit ...
  git push -u origin feature/channel-create-delete
  # Open Pull Request on GitHub
  ```

### 2. Rebase Daily to Avoid Stale Branches
* **Rule:** Do not let feature branches drift for days. Rebase on top of `origin/main` daily to keep conflicts small and incremental.
* **Workflow:**
  ```bash
  git fetch origin
  git rebase origin/main
  # If conflicts occur: resolve file, git add <file>, then:
  git rebase --continue
  git push --force-with-lease origin <branch-name>
  ```

### 3. Make Atomic Commits
* **Rule:** Each commit must be a self-contained, logical step that builds and passes tests on its own.
* **Tip:** If changes were made across multiple components at once, use patch mode (`git add -p`) to interactively select and stage hunks for separate logical commits.

### 4. Never Commit Compiled Binaries or Artifacts
* **Rule:** Binary executables, object files, and editor configs permanently bloat history and create merge noise.
* **Fixing untracked binaries:**
  ```bash
  git rm --cached <binary-file>
  echo "<binary-file>" >> .gitignore
  git add .gitignore
  git commit -m "chore: stop tracking binary files"
  ```

### 5. Never Resolve Conflicts with "Accept Both" Blindly
* **Rule:** Understand both sides of a conflict using `diff3` before making changes.
* **Verification steps:** Always compile (`make`) and run tests (`make test`) **before** staging resolved files with `git add`.

### 6. Golden Rule: Never Rebase Shared/Public Branches
* **Rule:** Only rebase branches that belong exclusively to you. Rewriting history on shared branches (`main`, `develop`) corrupts teammates' local histories.
* **Emergency Reset (unpushed local rebase):**
  ```bash
  git reflog
  git reset --hard <SHA-before-rebase>
  ```

### 7. Recovering "Lost" Work from `git reset --hard`
* **Rule:** `git reset --hard` removes branch pointers, but commit objects remain in Git's object store accessible via the `reflog`.
* **Recovery:**
  ```bash
  git reflog
  git checkout -b recovery/lost-work <SHA>
  ```

### 8. Avoid Long-Lived Branches
* **Rule:** Keep branches short-lived (merge within 1–3 days). Break large features into smaller, vertically integrated PRs. Set a team norm to review PRs within 24 hours.

### 9. Configure `pull.rebase` to Avoid Spurious Merge Commits
* **Rule:** Default `git pull` creates unnecessary merge commits when local and remote branches diverge slightly.
* **Global Configuration:**
  ```bash
  git config --global pull.rebase true
  ```
  Or run explicitly: `git pull --rebase origin <branch-name>`.

### 10. Avoid & Escape Detached HEAD State
* **Rule:** Detached HEAD occurs when checking out a specific SHA or tag instead of a branch. Commits made here are orphaned unless saved to a branch.
* **Saving work from detached HEAD:**
  ```bash
  git branch recovery/investigation
  git checkout main
  ```

---

## 3. Merge Conflict Mechanics & Resolution

### Enable `diff3` Style
Enable 3-way conflict view globally to show the common ancestor alongside your changes and incoming changes:
```bash
git config --global merge.conflictstyle diff3
```

### Marker Structure
```text
<<<<<<< HEAD
// YOUR version (Current branch edits)
||||||| common ancestor
// ORIGINAL baseline (What both branches started from)
>>>>>>> feature/incoming-branch
// THEIR version (Incoming branch edits)
```

### Conflict Resolution Checklist
1. Run `git status` to list all conflicted files.
2. Inspect all 3 sections (`HEAD`, common ancestor, incoming) to understand intent.
3. Edit the file to produce the correct combined implementation and remove all conflict markers.
4. Compile the project (`make`).
5. Run tests (`make test`).
6. Stage resolved files: `git add <file>`.
7. Complete merge/rebase: `git merge --continue` or `git rebase --continue`.

---

## 4. Recovery Toolkit & Emergency Commands

| Objective | Command |
| :--- | :--- |
| **Undo last commit (keep staged)** | `git reset --soft HEAD~1` |
| **Undo last commit (keep unstaged)** | `git reset HEAD~1` |
| **Undo last commit (discard all changes)** | `git reset --hard HEAD~1` |
| **Discard unstaged changes in file** | `git restore <file>` |
| **Unstage a file** | `git restore --staged <file>` |
| **Abort merge in progress** | `git merge --abort` |
| **Abort rebase in progress** | `git rebase --abort` |
| **Revert a merged commit safely** | `git revert <commit-SHA>` |
| **Revert a merge commit on `main`** | `git revert -m 1 <merge-commit-SHA>` |
| **Amend last commit message** | `git commit --amend -m "new message"` |

---

## 5. Debugging Regressions with `git bisect`

When a bug/crash is introduced across a long commit history, use binary search to locate the exact commit:

```bash
# 1. Start bisect
git bisect start

# 2. Mark current state as bad
git bisect bad

# 3. Mark a known historical good commit
git bisect good <known-good-SHA>

# 4. Test each midpoint checked out by Git (build & run test)
git bisect good   # if working
git bisect bad    # if broken

# 5. Reset back to HEAD after culprit is identified
git bisect reset
```

*Automated bisect:* `git bisect run make test`

---

## 6. Golden Rules Summary

1. **`main` is sacred:** Never push directly; always use branches and Pull Requests [cite: 3].
2. **Push daily:** Remote commits are safe; local-only commits are vulnerable to accidents [cite: 3].
3. **Rebase daily:** Keep conflicts small, incremental, and easy to resolve [cite: 3].
