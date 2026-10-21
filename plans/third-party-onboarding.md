# Third parties (authorised and paying parties): compliance data and portal onboarding

Plan written 21 Oct 2026, on branch `feature/compliance-stats-refresh` (which added
`WIP.paying_party`). Two codebases are involved: this office app and the client
onboarding portal at `../../client_onboarding_portal` (FastAPI + Next.js; see its
`CLAUDE.md`). Sections marked **Portal** are a paste-ready brief for that repo.

## Goal

For every authorised party and paying party on a matter, hold the same compliance
evidence we hold for clients, collected through the portal where possible:

- proof of ID and proof of address (with expiry), plus the selfie-with-ID
- a PEP declaration (everyone)
- a source of funds declaration (paying parties only)
- the Veriphy AML / ID check date (already held)

and show it on the matter home, the compliance stats and the expired-document reports.

## What exists today

Office app:

- A third party is an `AuthorisedParties` row (name, relationship, address, contact,
  `id_check`, `date_of_id_check`, `date_of_last_aml`). The matter points at up to three:
  `authorised_party1`, `authorised_party2`, `paying_party` (`WIP.THIRD_PARTY_FIELDS`).
  One person may hold both roles.
- Clients have `ClientKeyDocument` (proof_of_id / proof_of_address / selfie_id, with
  expiry, verified on/by, optional scan) reused across matters, and a per-matter
  `MatterClient` (terms, NCBA, source of funds, PEP: signed / on / by) with
  `MatterClientDocument` uploads. `backend/matter_compliance.py` builds the Client care
  cards on the matter home from these.
- Onboarding: `OnboardingGroup` → `Onboarding` members (one person each: name, email,
  `client_ref`, `required_documents`, typed address, `client` FK set at convert) →
  `OnboardingItem` per document. Convert creates clients and key documents, then hands
  off to the Open File form with the clients pre-selected; `link_group_to_matter` applies
  the declarations to `MatterClient` and tells the portal the matter reference.
- Compliance stats: third parties only have the "Third-party AML / ID check" tile.

Portal (`backend/app`): `POST /invites` takes `client_name`, `email`, `client_ref`,
`matter_ref?`, `required_documents?` (any of `proof_id`, `proof_address`, `selfie_id`,
`source_of_funds`, `pep`, `terms_of_engagement`; omitted means all). The upload page
shows one step per required item; the selfie is taken inside the terms step when terms
are required, otherwise as its own step. Declarations are rendered to PDF with server
captured metadata (`acting_for`, company details, IP, time). `GET /submissions/{id}`
returns documents, declarations, terms, the typed address and the capacity block.
The portal has no notion of who the person is in relation to the matter: everyone is
"the client".

## Decisions (defaults; say if any are wrong)

1. **Roles stay on the matter, the person is shared.** `AuthorisedParties` remains the
   one third-party record; roles come from the three WIP fields (a roles table replaces
   them in Phase D). Nothing about the record says "authorised" or "paying".
2. **PEP and source of funds are per matter**, like clients' declarations (SRA: redone
   for each engagement). Identity documents are per person and reused across matters,
   like clients'.
3. **Both routes in.** Third parties can be onboarded through the portal as members of
   a case (Phase C) and can still be picked or created on the open/edit file forms, with
   scans uploaded on the matter home (Phase A). Phase A ships first so staff can record
   paper evidence today.
4. **Selfie with ID is requested from third parties by default** (same assurance as
   clients); staff can untick it per invite.
5. **A portal upload of proof of ID does not set the Veriphy AML / ID check date** for a
   third party. It sets `id_check` / `date_of_id_check` and creates the key document;
   `date_of_last_aml` stays staff-entered from Veriphy. (Convert currently sets
   `date_of_last_aml` for clients from a portal ID upload; see open question 2.)
6. **One table for key documents and one for matter documents**, each gaining an
   optional third-party link, rather than mirror models: the preview views, private
   storage, expiry rules and reports then cover both without duplication.

## Data model changes (office)

```
ClientKeyDocument
  client        FK ClientContactDetails  -> now nullable
  third_party   FK AuthorisedParties, null, related_name='key_documents'   (new)
  CheckConstraint: exactly one of client / third_party is set
  upload path:  '{client_id}/...' or 'tp{third_party_id}/...'

MatterThirdParty (new)                       mirrors MatterClient
  matter        FK WIP, related_name='matter_third_parties'
  party         FK AuthorisedParties, related_name='matter_links'
  is_authorised BooleanField, is_paying BooleanField   (synced from the WIP fields)
  pep_signed / pep_on / pep_by
  source_of_funds_signed / _on / _by / _details          (payers only in the UI)
  source        captured | carried_over                  (as MatterClient.source)
  created_at;  unique (matter, party)

MatterClientDocument
  matter_client        -> now nullable
  matter_third_party   FK MatterThirdParty, null, related_name='documents'   (new)
  CheckConstraint: exactly one set
  categories used for third parties: source_of_funds, pep, aml_id_check, other

Onboarding
  party_type              'client' | 'third_party'   (default client)
  is_authorised_party     bool
  is_paying_party         bool
  relationship_to_client  CharField(50)               (copied to AuthorisedParties)
  party                   FK AuthorisedParties, null  (set at convert, idempotent, like `client`)
  required_item_types():  third parties default to proof_id, proof_address, selfie_id, pep
                          (+ source_of_funds when is_paying_party); never terms_of_engagement
```

`ensure_matter_third_parties(wip)` (in `matter_compliance.py`, beside
`ensure_matter_clients`) creates or updates one `MatterThirdParty` per distinct person on
the WIP fields and sets the role flags. Rows are never deleted automatically; the matter
home shows only rows whose party is currently on the matter.

## Phase A: office only, no portal change

Ship first; it stands alone and is what Phases C and D write into.

1. Migrations for the three model changes above (one migration after 0088).
2. `matter_compliance.py`: `matter_third_party_compliance(wip)` returning, per party:
   roles, relationship, `id_check` / AML date, the two declaration flags, and a documents
   list built the same way as `client_documents()` (identity rows from key documents with
   `third_party` set; matter rows for PEP, source of funds (payers), AML / ID check, other;
   every row has an upload). `apply_third_party_declarations(mtp, provided, user)` like
   `apply_declarations`, for `pep` and `source_of_funds`.
3. Matter home: a `partials/matter_third_party_care.html` block inside Client care &
   compliance, after the client cards: one collapsible card per third party with role
   pill(s), relationship, AML / ID date (link to the edit-party page), an engagement
   checks form (PEP; source of funds with details for payers) and the documents folder.
   Header badges: ID, AML / ID, PEP, SOF (payers).
4. Views in `matter_compliance_views.py`: `matter_save_third_party_compliance`,
   `matter_upload_third_party_doc`, `matter_upload_third_party_identity_doc` (mirror the
   client ones; reuse the two preview views). Audit with `create_modification` on the
   party record, as the client views do.
5. Reports: `get_live_matter_client_document_issues(category)` gains a `subjects`
   argument (`clients` | `third_parties` | `all`); the Proof of ID / Proof of address
   issues reports include third parties with a "Who" column (Client, Authorised party,
   Paying party) and the hub counts follow. Matter home expiry alerts include them.
6. Compliance stats, client due diligence group, four tiles: "Third-party proof of ID
   valid", "Third-party proof of address valid", "Third-party PEP declaration signed",
   "Paying party source of funds signed". The snapshot loads `MatterThirdParty` rows for
   live matters; the two document tiles reuse `_document_collector` with the new
   `subjects` argument.
7. Tests: `tests_matter_third_party.py` (sync from WIP fields, both-roles person, home
   card renders, saves and uploads, audit rows), additions to `tests_compliance_stats.py`
   and `tests_report_pages.py`.

Estimate: two to three days.

## Phase B: Portal, third-party invites

**Portal brief** (paste into a session in `client_onboarding_portal`):

> Add third-party invites. A third party is a person connected to a client's matter who
> is not the client: an *authorised party* (acts or gives instructions for the client) or
> a *paying party* (provides money for the matter), or both.
>
> 1. `InviteCreate` gains `party_role: Literal['client','authorised_party','paying_party',
>    'authorised_and_paying'] = 'client'`, `for_client_name: str | None` (the client the
>    person relates to, display only) and `relationship: str | None`. Store all three on
>    `Submission`; echo them in `SubmissionOut` and `SubmissionState`.
> 2. Required items: when `party_role != 'client'`, reject `terms_of_engagement` (422) and
>    make "omitted" mean the role default: `proof_id, proof_address, selfie_id, pep`, plus
>    `source_of_funds` for paying roles. Extend `parse_required_items` / the `RequiredItem`
>    tests accordingly.
> 3. Frontend copy keyed on role: the landing and checklist say "ANP Solicitors act for
>    {for_client_name}. They have named you as the person paying for the matter / as
>    authorised to deal with the matter on their behalf." The PEP intro becomes "We have to
>    ask everyone involved in a matter this". The terms step never shows; the selfie step
>    shows on its own when required (already supported). The capacity step (self /
>    company) still applies: a company can be the payer.
> 4. Source of funds for paying roles: a payer preamble before the existing source
>    options: what you are providing (our fees only / a deposit / the purchase price /
>    other, with amount), whether it is a gift or repayable, and your relationship to the
>    client. Hide the "A friend or relative is providing funds" and "A company or business
>    is paying" options for payers (they are the payer). Keep `backend/app/forms.py` and
>    `frontend/components/declarations.tsx` in step as now.
> 5. Declaration PDFs: title "Source of Funds Declaration (paying party)" / "PEP
>    Declaration" and include `party_role`, `for_client_name` and `relationship` in the
>    server-captured metadata block.
> 6. No change to SharePoint paths (keyed by `client_ref`, which is per person), audit
>    events or the office authentication. Pydantic ignores unknown fields, so the office
>    can send `party_role` before this is deployed; it is simply dropped.
> 7. Tests: schema validation (terms rejected for third parties; role defaults),
>    submission echo, PDF metadata, frontend copy snapshot for each role.

Estimate: one to two days. Deploy before Phase C goes live.

## Phase C: office onboarding of third parties

1. Start form and "Add another person" form: a person-type toggle (Client / Third
   party). Third party rows take name, email, role checkboxes (authorised, paying),
   relationship, or an existing third party picked by search (`party_search_json`,
   sibling of `client_search_json`). `_add_existing_party_member()` mirrors
   `_add_existing_client_member()`, skipping identity documents still valid on file.
2. `portal.create_invite()` sends `party_role`, `for_client_name` (the case's lead client
   name) and `relationship`. `onboarding_email.send_invite_email()` gets a third-party
   body: "ANP Solicitors act for {client}. You have been named as …; please upload …".
3. Detail page: member cards carry a role pill and "for {client}"; the counts line says
   "2 clients · 1 third party". Conflict check runs as today (the name search already
   covers `AuthorisedParties`) and the address gate applies to third parties too.
4. Convert: third-party members create or reuse an `AuthorisedParties` row (contact
   fields, `relationship_to_client`, `id_check` and `date_of_id_check` when proof of ID
   was provided; `date_of_last_aml` untouched) and key documents with `third_party` set
   (proof of ID, proof of address, selfie). The session prefill adds
   `authorised_party_ids` and `paying_party_id`; `open_file.html` pre-selects the pickers.
   A case with more than two authorised parties is refused with a message until Phase D.
5. `link_group_to_matter`: `ensure_matter_third_parties(matter)`, then
   `apply_third_party_declarations()` for each third-party member from the portal items;
   `attach_matter` as for clients.
6. Tests: additions to `tests_onboarding_portal.py` (member types, invite payload, email
   wording, convert creates and links the party, prefill, declarations applied) and
   `tests_open_file.py` (prefilled pickers).

Estimate: two to three days.

## Phase D: later

- **Requests after the file is open.** A "Request documents" action on a client or
  third-party card creates an `OnboardingGroup(matter=wip)` member with the matter
  reference passed to the portal; completion applies straight to the matter (no Open
  File hop). This also serves re-collection when a proof of ID expires.
- **Roles table replaces the WIP fields.** `MatterThirdParty` becomes the source of
  roles (any number of authorised parties); the three FKs are migrated into rows and
  `THIRD_PARTY_FIELDS` consumers (home, logs, AML export, key dates, conflicts, stats)
  read the table.
- **Risk assessment cross-check.** When a matter has a paying party but its latest risk
  assessment answers "receiving funds from third parties: No", show a notice on the
  flags panel and in the sign-off queue.

## Contract summary

| Field / behaviour | Office sends or reads | Portal |
|---|---|---|
| `party_role`, `for_client_name`, `relationship` on `POST /invites` | Phase C sends | Phase B stores, echoes |
| `required_documents` defaults and `terms_of_engagement` rule by role | Phase C computes `required_item_types()` by type | Phase B validates |
| `GET /submissions/{id}` extra fields | Phase C reads `party_role` to double-check the member type | Phase B |
| Declaration PDF metadata | unchanged read | Phase B adds role fields |
| SharePoint paths, audit, `X-Internal-Api-Key` | unchanged | unchanged |

## Rollout

1. Merge the current branch (paying party, archive dates, sign-off queue).
2. Phase A on a new branch off main (`feature/third-party-compliance`), migrations
   numbered after 0088; deploy the office app.
3. Phase B in the portal repo; deploy the portal (Vercel + droplet per its
   `docs/DEPLOYMENT.md`).
4. Phase C on `feature/third-party-onboarding`; mock portal mode works throughout, so it
   can be built before Phase B is live.

## Open questions

1. Is collecting from a third party *after* the file is open (Phase D) needed in the
   first release, or is pre-matter onboarding plus staff uploads enough to start?
2. Convert currently stamps a client's `date_of_last_aml` from a portal proof-of-ID
   upload, which the compliance stats read as the Veriphy check date. Keep that for
   clients, or make it Veriphy-only for everyone as proposed for third parties?
3. Confirm the payer source-of-funds questions with the firm (what is provided, amount,
   gift or loan, relationship, then the money's origin). Is a separate gifted-deposit
   letter still needed on conveyancing files?
4. Include third parties in the existing Proof of ID / Proof of address issues reports
   (proposed, with a "Who" column) or keep separate reports?
