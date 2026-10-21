# Authorised parties, paying parties and third parties: compliance data and portal onboarding

Plan written 21 Oct 2026, on branch `feature/compliance-stats-refresh` (which added
`WIP.paying_party`). Two codebases are involved: this office app and the client
onboarding portal at `../../client_onboarding_portal` (FastAPI + Next.js; see its
`CLAUDE.md`). The section marked **Portal brief** is paste-ready for that repo.

## Definitions

Who a person *is* (their kind) and what they *do* on a matter (their roles) are
separate things. The roles decide what evidence we must hold.

| Kind | Who | Example |
|---|---|---|
| **Client** | The person or company we act for | Jane Example; Acme Ltd |
| **Representative** | An officer of a client that is a company or organisation. Part of the client, not an outsider. Always an authorised party on that client's matters | A director or company secretary of Acme Ltd; a partner; a trustee |
| **Third party** | A person who is neither the client nor the client's own representative, connected to the matter by one or both roles below | The client's mother; an attorney under an LPA; a relative funding a deposit |

| Role (on a matter) | Meaning | Who can hold it |
|---|---|---|
| **Authorised party** | Entitled to give us instructions for the client | A representative (by definition) or a third party the client has authorised |
| **Paying party** | Provides money for the matter: fees, a deposit, the price | A third party. (A director paying the company's fees personally is, for that money, a third party too: the role, not the kind, drives the source of funds check.) |

The same person can hold both roles: the client's mother who both acts for the client
and pays is a third party who is an authorised party and a paying party.

What we must hold, by role:

| | ID, address, selfie | PEP declaration | Evidence of authority | Source of funds |
|---|---|---|---|---|
| Representative (authorised) | yes | yes | yes: Companies House officer check or board resolution | no: the company's declaration is the client's |
| Third party, authorised | yes | yes | yes: LPA, letter of authority, deputyship order | no |
| Third party, paying | yes | yes | no | yes |

## Goal

Hold that evidence for every representative and third party on a matter, collect it
through the portal where possible, and show it on the matter home, the compliance stats
and the expired-document reports, the way we do for clients.

## What exists today

Office app:

- Representatives and third parties alike are `AuthorisedParties` rows (name,
  relationship, address, contact, `id_check`, `date_of_id_check`, `date_of_last_aml`).
  The matter points at up to three: `authorised_party1`, `authorised_party2`,
  `paying_party` (`WIP.THIRD_PARTY_FIELDS`). Nothing records whether a row is an officer
  of a company client or an outsider; the free-text `relationship_to_client` ("Director",
  "Mother", "Attorney") is the only clue.
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
- A company client is onboarded as one member; the director completes it and the portal
  reports a *capacity* block (acting for a company: name, number, their role). The
  director's ID documents are stored against the **company's** record and the director
  is not recorded as a person.
- Compliance stats: third parties only have the "Third-party AML / ID check" tile.

Portal (`backend/app`): `POST /invites` takes `client_name`, `email`, `client_ref`,
`matter_ref?`, `required_documents?` (any of `proof_id`, `proof_address`, `selfie_id`,
`source_of_funds`, `pep`, `terms_of_engagement`; omitted means all). The upload page
shows one step per required item; the selfie is taken inside the terms step when terms
are required, otherwise as its own step. `CapacityIn` records `acting_for`
(self / company), `company_name`, `company_number`, `signatory_role` but **not the
signatory's name**. Declarations are rendered to PDF with server-captured metadata.
`GET /submissions/{id}` returns documents, declarations, terms, the typed address and the
capacity block. Everyone is "the client" in the portal's copy.

## Decisions (defaults; say if any are wrong)

1. **One shared person record, kinds on the record, roles on the matter.**
   `AuthorisedParties` stays the record for representatives and third parties and gains
   `kind` and, for representatives, which client they represent. The three WIP fields
   keep the roles (a roles table replaces them in Phase D).
2. **Representatives are not invited separately.** A company client gets one invite; the
   director completes it in the company's capacity, as now. The portal captures the
   signatory's name; at convert the office creates the representative record from the
   capacity block, attaches the director's identity documents to **the person** (no longer
   to the company), and makes them `authorised_party1`. This changes current behaviour
   for company clients; see open question 2.
3. **Third parties are invited as members of the case** with their roles (Phase C) and
   can still be picked or created on the open/edit file forms with scans uploaded on the
   matter home (Phase A, shipped first).
4. **PEP and source of funds are per matter**, like clients' declarations. Identity
   documents are per person and reused across matters. Evidence of authority is per
   matter (an LPA or board resolution is matter-specific in practice).
5. **Selfie with ID is requested from third parties by default**; staff can untick it.
6. **A portal upload of proof of ID does not set the Veriphy AML / ID check date** for a
   representative or third party. It sets `id_check` / `date_of_id_check` and creates the
   key document; `date_of_last_aml` stays staff-entered from Veriphy. (Convert currently
   sets `date_of_last_aml` for clients from a portal ID upload; open question 3.)
7. **One table for key documents and one for matter documents**, each gaining an
   optional link to the person / matter-person row, rather than mirror models: preview
   views, private storage, expiry rules and reports then cover both without duplication.

## Data model changes (office)

```
AuthorisedParties                           (the shared "connected person" record)
  kind          'representative' | 'third_party'   default third_party        (new)
  represents    FK ClientContactDetails, null: the company client an officer acts for (new)
  data migration: kind=representative where relationship_to_client matches
                  director / secretary / partner / trustee / officer (case-insensitive)

ClientKeyDocument
  client        -> now nullable
  third_party   FK AuthorisedParties, null, related_name='key_documents'      (new)
  CheckConstraint: exactly one of client / third_party is set
  upload path:  '{client_id}/...' or 'tp{third_party_id}/...'

MatterThirdParty (new)                       mirrors MatterClient; one row per person on the matter
  matter        FK WIP, related_name='matter_third_parties'
  party         FK AuthorisedParties, related_name='matter_links'
  is_authorised BooleanField, is_paying BooleanField   (synced from the WIP fields)
  pep_signed / pep_on / pep_by
  source_of_funds_signed / _on / _by / _details          (shown for payers)
  authority_evidenced / authority_on / authority_by      (shown for authorised parties)
  source        captured | carried_over                  (as MatterClient.source)
  created_at;  unique (matter, party)

MatterClientDocument
  matter_client        -> now nullable
  matter_third_party   FK MatterThirdParty, null, related_name='documents'   (new)
  CheckConstraint: exactly one set
  categories add 'authority' (evidence of authority); for third parties the rows are
  authority (authorised), source_of_funds (paying), pep, aml_id_check, other

Onboarding
  party_type              'client' | 'third_party'   (default client; representatives
                          are never members, they come from a company member's capacity)
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

Company clients: in `client_documents()`, a client with `is_business` shows "UK business
check" (`date_of_last_aml`) in place of its own proof of ID / address rows, plus one line
per representative: "{name}, {role}: ID verified dd/mm/yyyy" linking to that person's
documents. The expired-ID reports then look at representatives, not the company.

## Phase A: office only, no portal change

Ship first; it stands alone and is what Phases C and D write into.

1. Migrations for the model changes above (one migration after 0088, including the
   `kind` backfill).
2. Edit-party page (`AuthorisedPartyForm`): `kind` and, for representatives, a company
   client picker for `represents`. Open/edit file pickers show the kind after the name
   ("Dan Director, director of Acme Ltd" / "Edna Harris, mother").
3. `matter_compliance.py`: `matter_third_party_compliance(wip)` returning, per person:
   kind, roles, relationship, `id_check` / AML date, the declaration flags, and a
   documents list built the same way as `client_documents()` (identity rows from key
   documents with `third_party` set; matter rows per the requirements table; every row
   has an upload). `apply_third_party_declarations(mtp, provided, user)` like
   `apply_declarations`, for `pep` and `source_of_funds`.
4. Matter home: a `partials/matter_third_party_care.html` block inside Client care &
   compliance, after the client cards: one collapsible card per person with kind and role
   pills, relationship, AML / ID date (link to the edit-party page), an engagement checks
   form (PEP; authority for authorised parties; source of funds with details for payers)
   and the documents folder. Header badges: ID, AML / ID, PEP, AUTH, SOF as applicable.
   The file-summary cards keep the contact details and gain the kind line.
5. Views in `matter_compliance_views.py`: `matter_save_third_party_compliance`,
   `matter_upload_third_party_doc`, `matter_upload_third_party_identity_doc` (mirror the
   client ones; reuse the two preview views). Audit with `create_modification` on the
   person record, as the client views do.
6. Reports: `get_live_matter_client_document_issues(category)` gains a `subjects`
   argument (`clients` | `third_parties` | `all`); the Proof of ID / Proof of address
   issues reports include representatives and third parties with a "Who" column (Client,
   Representative of X, Authorised party, Paying party) and the hub counts follow. Matter
   home expiry alerts include them.
7. Compliance stats, client due diligence group: "Third-party proof of ID valid",
   "Third-party proof of address valid", "Third-party PEP declaration signed",
   "Authority evidenced" (authorised parties), "Paying party source of funds signed". The
   snapshot loads `MatterThirdParty` rows for live matters; the document tiles reuse
   `_document_collector` with the new `subjects` argument.
8. Tests: `tests_matter_third_party.py` (sync from WIP fields, both-roles person, kinds
   backfill, company client rows, home card renders, saves and uploads, audit rows),
   additions to `tests_compliance_stats.py` and `tests_report_pages.py`.

Estimate: three days.

## Phase B: Portal, third-party invites and the signatory's name

**Portal brief** (paste into a session in `client_onboarding_portal`):

> Two changes. (1) Record who completes a company client's onboarding. (2) Invite
> third parties: people connected to a client's matter who are not the client: an
> *authorised party* (acts or gives instructions for the client), a *paying party*
> (provides money for the matter), or both. A company's own director is not a third
> party; they complete the company's onboarding in its capacity, as now.
>
> 1. `CapacityIn` / `CapacityOut`: add `signatory_name` (required when
>    `acting_for == "company"`, max 200) and optional `signatory_dob` (date). Ask for them
>    on the capacity step ("Your full name, as on your ID"). Echo both in
>    `SubmissionOut.capacity`. Include them in declaration PDF metadata and the terms
>    acceptance certificate.
> 2. `InviteCreate` gains `party_kind: Literal['client','third_party'] = 'client'`,
>    `roles: list[Literal['authorised','paying']] = []` (required, non-empty, when
>    `party_kind == 'third_party'`), `for_client_name: str | None` (the client the person
>    relates to, display only) and `relationship: str | None`. Store them on `Submission`;
>    echo them in `SubmissionOut` and `SubmissionState`.
> 3. Required items for third parties: reject `terms_of_engagement` (422); "omitted"
>    means the role default: `proof_id, proof_address, selfie_id, pep`, plus
>    `source_of_funds` when `paying` is among the roles. Extend `parse_required_items` and
>    the `RequiredItem` tests.
> 4. Frontend copy keyed on kind and roles. Landing and checklist for third parties:
>    "ANP Solicitors act for {for_client_name}. They have named you as the person paying
>    for the matter / as authorised to deal with the matter on their behalf." The PEP intro
>    becomes "We have to ask everyone involved in a matter this". No terms step; the selfie
>    step shows on its own when required (already supported). The capacity step still
>    applies to third parties: a company can be the payer.
> 5. Source of funds for paying third parties: a payer preamble before the existing
>    source options: what you are providing (our fees only / a deposit / the purchase
>    price / other, with the amount), whether it is a gift or repayable, and your
>    relationship to the client. Hide the "A friend or relative is providing funds" and
>    "A company or business is paying" options for payers (they are the payer). Keep
>    `backend/app/forms.py` and `frontend/components/declarations.tsx` in step as now.
> 6. Declaration PDFs: title "Source of Funds Declaration (paying party)" / "PEP
>    Declaration" and include `party_kind`, `roles`, `for_client_name` and `relationship`
>    in the server-captured metadata block.
> 7. No change to SharePoint paths (keyed by `client_ref`, which is per person), audit
>    events or the office authentication. Pydantic ignores unknown fields, so the office
>    can send the new invite fields before this is deployed; they are simply dropped.
> 8. Tests: schema validation (terms rejected for third parties; role defaults; signatory
>    name required for companies), submission echo, PDF metadata, frontend copy for each
>    kind and role.

Estimate: two days. Deploy before Phase C goes live.

## Phase C: office onboarding of third parties and representatives

1. Start form and "Add another person" form: a person-type toggle (Client / Third
   party). Third-party rows take name, email, role checkboxes (authorised, paying),
   relationship, or an existing person picked by search (`party_search_json`, sibling of
   `client_search_json`). `_add_existing_party_member()` mirrors
   `_add_existing_client_member()`, skipping identity documents still valid on file.
2. `portal.create_invite()` sends `party_kind`, `roles`, `for_client_name` (the case's
   lead client name) and `relationship`. `onboarding_email.send_invite_email()` gets a
   third-party body: "ANP Solicitors act for {client}. You have been named as …; please
   upload …".
3. Detail page: member cards carry kind and role pills and "for {client}"; the counts
   line says "2 clients · 1 third party". For a company member, the capacity block now
   shows the signatory's name and a "will be recorded as {name}, {role}, representative
   of {company}" note. Conflict check: runs per member as today (the name search already
   covers `AuthorisedParties`); for a company member it is also run on the signatory's
   name. The address gate applies to third parties too.
4. Convert:
   - third-party members create or reuse an `AuthorisedParties(kind=third_party)` row
     (contact fields, `relationship_to_client`, `id_check` and `date_of_id_check` when
     proof of ID was provided; `date_of_last_aml` untouched) and key documents with
     `third_party` set (proof of ID, proof of address, selfie);
   - company members whose submission capacity is `company` create or reuse an
     `AuthorisedParties(kind=representative, represents=the company client,
     name=signatory_name, relationship_to_client=signatory_role)`, and the identity
     documents provided in that submission are recorded against the representative (not
     the company); the company's own identity is its UK business check;
   - the session prefill adds `authorised_party_ids` (representatives first) and
     `paying_party_id`; `open_file.html` pre-selects the pickers. A case needing more than
     two authorised parties is refused with a message until Phase D.
5. `link_group_to_matter`: `ensure_matter_third_parties(matter)`, then
   `apply_third_party_declarations()` for each third-party member (and the representative,
   whose PEP declaration is the one in the company's submission) from the portal items;
   `attach_matter` as for clients.
6. Tests: additions to `tests_onboarding_portal.py` (member types, invite payload, email
   wording, convert creates the third party and the representative, documents land on
   the person, prefill, declarations applied) and `tests_open_file.py` (prefilled pickers).

Estimate: three days.

## Phase D: later

- **Requests after the file is open.** A "Request documents" action on a client, third
  party or representative card creates an `OnboardingGroup(matter=wip)` member with the
  matter reference passed to the portal; completion applies straight to the matter (no
  Open File hop). This also serves re-collection when a proof of ID expires.
- **Roles table replaces the WIP fields.** `MatterThirdParty` becomes the source of
  roles (any number of authorised parties); the three FKs are migrated into rows and
  `THIRD_PARTY_FIELDS` consumers (home, logs, AML export, key dates, conflicts, stats)
  read the table.
- **Risk assessment cross-check.** When a matter has a paying party but its latest risk
  assessment answers "receiving funds from third parties: No", or has an authorised party
  but "third-party authority: N/A", show a notice on the flags panel and in the sign-off
  queue.

## Contract summary

| Field / behaviour | Office sends or reads | Portal |
|---|---|---|
| `signatory_name`, `signatory_dob` in capacity | Phase C reads at convert | Phase B captures, echoes |
| `party_kind`, `roles`, `for_client_name`, `relationship` on `POST /invites` | Phase C sends | Phase B stores, echoes |
| `required_documents` defaults and `terms_of_engagement` rule by kind and roles | Phase C computes `required_item_types()` | Phase B validates |
| `GET /submissions/{id}` extra fields | Phase C reads `party_kind` / `roles` to double-check the member | Phase B |
| Declaration PDF metadata | unchanged read | Phase B adds kind, roles, signatory |
| SharePoint paths, audit, `X-Internal-Api-Key` | unchanged | unchanged |

## Rollout

1. Merge the current branch (paying party, archive dates, sign-off queue).
2. Phase A on a new branch off main (`feature/third-party-compliance`), migrations
   numbered after 0088; deploy the office app. Review the `kind` backfill on prod data
   (the relationship text decides it) before deploying.
3. Phase B in the portal repo; deploy the portal (Vercel + droplet per its
   `docs/DEPLOYMENT.md`).
4. Phase C on `feature/third-party-onboarding`; mock portal mode works throughout, so it
   can be built before Phase B is live.

## Open questions

1. Is collecting from a third party *after* the file is open (Phase D) needed in the
   first release, or is pre-matter onboarding plus staff uploads enough to start?
2. For company clients, the director's identity documents will be recorded against the
   director (representative) rather than the company, and the company's identity row
   becomes its UK business check. Existing company clients keep whatever documents they
   already hold. Agreed?
3. Convert currently stamps a client's `date_of_last_aml` from a portal proof-of-ID
   upload, which the compliance stats read as the Veriphy check date. Keep that for
   clients, or make it Veriphy-only for everyone as proposed for representatives and
   third parties?
4. Confirm the payer source-of-funds questions with the firm (what is provided, amount,
   gift or loan, relationship, then the money's origin). Is a separate gifted-deposit
   letter still needed on conveyancing files?
5. Include representatives and third parties in the existing Proof of ID / Proof of
   address issues reports (proposed, with a "Who" column) or keep separate reports?
