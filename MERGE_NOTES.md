# Merge notes — local branch vs main

**Date noted: 2 Sep 2026**

This local branch (`feature/policy-word-export`) has diverged from `origin/main`.
Separate fixes/features are being developed in worktrees branched directly off
`origin/main` (worktree at `../fm-wt-pdf-docs`) and pushed to the remote. As of
today that includes `fix/pdf-wrapping-and-docs-features` (pushed to origin,
destined for main), which contains:

- Estate account PDF: wrap long description text instead of overflowing.
- Documents folder: combine documents into one PDF **without** numbering/index.
- Bundle index: wrap long headings in the index table.
- Bundle/documents: upload multiple PDFs as a single index item.

**Update 3 Sep 2026:** `fix/pdf-wrapping-and-docs-features` was merged to main
(PR #74). A second worktree branch `feature/risk-assessment-signoff`
(worktree `../fm-wt-risk-signoff`) adds the risk assessment sign-off workflow,
including backend migrations **0065/0066** — this local branch has its own
0061–0071 migrations, so expect a migration renumber/merge when reconciling.

**TODO (future):** when this local branch is ready, reconcile it with `main` —
main will contain the above changes (and possibly others) that are not in this
branch's history. Expect conflicts in at least:

- `frontend/templates/estate_account_export.html` (modified locally too)
- `backend/pdf/bundle_builder.py` / documents views & templates
- anything else touched by both streams since the branches diverged

Plan the merge deliberately (likely `git merge origin/main` into this branch and
resolve by hand) rather than rebasing the long-lived local history.
