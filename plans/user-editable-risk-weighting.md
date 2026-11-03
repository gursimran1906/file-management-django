# Letting the firm change the risk weighting itself

Today the weighting lives in `backend/risk_scoring.py`: the points each answer
carries, each section's ceiling and floors, the bands, and the reason behind
every number. Changing any of it needs a developer. This is a plan for moving
that control to the firm without losing the things that make the weighting
defensible.

Nothing here is built yet. The open questions at the end need answering before
it is.

## What should and should not become editable

**Editable:** the points an answer carries, a section's cap and its medium and
high floors, the band thresholds, the matter-type starting points (already
editable in admin), the transaction value steps, and the reason recorded
against any of them.

**Not editable:** the questions themselves. Adding or removing a question
changes the database and the form, so it stays a developer change. This line
matters — it keeps the editable surface to numbers and prose, where a mistake
is recoverable and reviewable, rather than schema.

**Not editable, deliberately:** the automatic high-risk triggers. Sanctions, a
designated person, a high-risk third country, a non-domestic PEP, proliferation
financing and a transaction with no apparent economic purpose are high risk
because the Money Laundering Regulations say enhanced due diligence is
mandatory, not because the firm chose a number. The editor should show them and
refuse to remove or demote them.

## Shape

### Data

The constants become rows, versioned the way `WEIGHTING_HISTORY` already is:

- `WeightingVersion` — version, effective date, summary, status (draft, active,
  superseded), created by/at, approved by/at.
- `WeightingCategory` — version, side (client or matter), key, label, cap,
  `medium_at`, `high_at`, reason, order.
- `WeightingFactor` — category, label, the field(s) and answer it reads,
  points, whether it is an automatic trigger, reason, order.
- `WeightingValueBand` — version, threshold, points, label, reason.
- `MatterType.inherent_risk` already exists and is already editable.

A data migration writes the current code tables in as version 2026.1, so
nothing changes on the day it ships.

### Engine

`risk_scoring` keeps its dataclasses and all of its logic. The only change is
where the tables come from: load the active version's rows into the same
`Category`/`Factor` shapes, cached per process and invalidated when a version
is activated. The code constants stay as the seed and as the fallback if no
active version exists, so the module still works in a fresh database and in
tests that do not care about weighting.

Scoring an assessment continues to stamp `scoring_version` and store the full
breakdown, so per-file provenance is unaffected.

### Editing

Not the Django admin: this needs guardrails, a reason per change, and a
preview, none of which admin gives.

A manager-only page that clones the active version into a draft, edits it
inline, and then:

1. **Validates.** See below.
2. **Dry runs.** Scores every live matter under the draft and reports the
   movement: *"of 143 live matters, 12 would move Medium to High and 3 High to
   Medium"*, with the list. This is the feature that makes the whole thing
   safe to hand over, and on its own is a good reason to build it.
3. **Requires a summary and a reason per change**, which become the version's
   history entry and appear in the exported PDF.
4. **Is approved before it takes effect**, with an effective date.

### Guardrails the validator must enforce

These come from LSAG 5.13, which is explicit that a weighting can be wrong in
specific ways:

- **High must stay reachable.** LSAG: weighting must not "lead to a situation
  where it is impossible for any business to be classified as high risk".
  Check that some realistic combination of answers still reaches High, and
  refuse a draft where it cannot.
- **No single factor should dominate.** Warn where one factor is worth more
  than, say, two thirds of its category's cap, unless it is an automatic
  trigger (which is meant to dominate).
- **Floors must be coherent:** `medium_at` ≤ `high_at` ≤ `cap`.
- **Every factor keeps a reason.** The current code has a test that fails if
  any weight lacks one; the editor should enforce the same thing.
- **Automatic triggers cannot be removed or demoted.**

## Phasing

**Phase 1 — the likely tuning, cheaply.** Make the three band thresholds and
the transaction value steps editable, alongside the matter-type inherent risk
that already is. Covers most of what the firm would realistically want to
change in the first year, with no new approval flow: these are few enough to
go through the existing version history by hand.

**Phase 2 — the full editor.** Per-factor weights, caps and floors in a
versioned draft with validation, dry run and approval. This is the bulk of the
work.

**Phase 3 — retire the constants** to seed-only, once Phase 2 has been used in
anger and the fallback is no longer load-bearing.

Rough effort: Phase 1 is small. Phase 2 is the real build — the models and
engine change are straightforward, and most of the cost sits in the editing
page, the validator and the dry run.

## Questions to settle first

1. **Who approves a weighting change?** The risk assessment itself needs a fee
   earner's sign-off. A change to the weighting affects every future
   assessment, so it arguably needs the COLP or MLRO specifically, and
   arguably someone other than whoever drafted it. Reusing `is_manager` is the
   cheap answer; a dedicated permission is the honest one.
2. **When a version is activated, what happens to matters assessed under the
   old one?** Today they keep their rating and the register marks them
   superseded, to be reviewed deliberately. The alternative is pushing them
   into the sign-off queue so the review is forced. The first respects that an
   assessment is a signed-off record; the second is harder to ignore.
3. **Should the dry run be able to block activation** — for example if more
   than some proportion of live matters would move — or only inform?
4. **Does the firm want to keep the question set fixed?** This plan assumes
   yes. If questions ever need to be firm-editable, the shape is different and
   considerably larger.

## Why this is worth doing carefully

The weighting is the part of this the SRA would ask about. It is already
documented, versioned, and exportable with its reasoning. Handing the controls
over is fine, but only if a change still has to say what it is, why, who
approved it and when — which is what the versioning and approval in this plan
are for. An editable weighting with no history would be worse than the code
constants it replaced.
