# Central complaints register

Plan written 28 Oct 2026; phases 1-3 built the same day on `feature/complaints-register`
(models, register, detail, matter home, dashboard and management cards, correspondence
tagging, compliance stats group, annual return). Not yet built: email auto-tagging by
complaint reference, digest/sign-off-queue hooks, a hint on the file review question. The regulatory section is sourced from the SRA, Legal Ombudsman and Law
Society pages fetched on the same day; links are in the appendix.

## The question asked

"Do we move a matter into complaints mode, open a new matter for the complaint, or
allocate correspondence to a complaint?" Short answer: **none of those on their own**.
A complaint is its own record, in a central register, that *points at* a matter
(and can point at none). The matter carries on being the matter. Correspondence stays
on the matter and is *tagged* to the complaint. Reasons below.

## What the regulators actually require

Everything here was checked against the SRA, Legal Ombudsman (LeO), Legal Services
Board (LSB), legislation.gov.uk and ICO pages on 28 Oct 2026. Items marked
*unconfirmed* could not be read from a primary source (the Law Society practice note
returned 403; Lexcel was read from an assessor's mirror).

### Must do (in force now)

| Requirement | Source | What the register must hold |
|---|---|---|
| Have and maintain a complaints procedure; deal with complaints "promptly, fairly, and free of charge" | SRA Code for Solicitors 8.2, 8.5; Code for Firms 7.1(c) | A record per complaint; never a charge |
| Tell clients in writing at engagement how to complain and about LeO | Code 8.3 | Already covered by client care letter (`date_of_client_care_sent`); not a register field |
| If not resolved within **8 weeks** of the complaint being made, tell the client in writing about LeO, the time limit and contact details, plus ADR body details once the procedure is exhausted | Code 8.4; LeO Scheme Rules 4.1–4.2 | `received_on`, computed `eight_week_deadline`, `final_response_sent_on`, `leo_signposted_on` |
| The **six-month** LeO clock only starts if the final response says prominently that LeO is available, gives full LeO contact details, and warns of the six-month limit | LeO Scheme Rules 4.4 | Three checklist booleans on the final response, so a vague letter is caught before it goes out |
| Complainant has **one year** from the act/omission or from when they should have known | Scheme Rules 4.5 | `act_or_omission_on` so the handler can see the LeO exposure |
| Who can complain to LeO: individuals, micro-enterprises, small charities/clubs/trusts, personal representatives and **beneficiaries** of an estate, and **prospective clients** who were offered or refused a service | Scheme Rules 2.1, 2.8 | `complainant_type` must cover non-clients; the register must work with no matter attached |
| Definition of a complaint: "an oral or written expression of dissatisfaction" alleging loss, distress, inconvenience or other detriment; prospective and former clients count | LSB s.112 Requirements (May 2024) para on definitions; LSA 2007 s.112 | Log verbal grumbles too; a "not a formal complaint" outcome rather than not logging |
| On first notification: prompt acknowledgement, procedure and contact details, **a timeline for resolution**; then **regular updates** | LSB s.112 Requirements paras 14–15 | `acknowledged_on`, `timeline_given_on`, update events in the chronology |
| Identify and address systemic issues; train staff | LSB s.112 Requirements paras 17–18 | `root_cause`, `lessons_learned`, trend report |
| Records to demonstrate compliance; COLP ensures compliance and reports serious breaches | Code for Firms 2.1, 2.2, 2.5, 3.9, 9.1 | Audit trail (`Modifications`), COLP sign-off, SRA-report fields |
| Publish the complaints procedure, and how/when to complain to LeO and the SRA, on the website | SRA Transparency Rules 2.1 | Not a register field; record which procedure version was sent |
| **Annual SRA return** (year to 31 Aug) asks: number received, resolved (client satisfied), referred to LeO, by category | SRA bulk renewal guidance | `reporting_year` derived Sep–Aug; `status` distinguishes resolved-satisfied from closed-not-satisfied; categories use the SRA list verbatim |
| SRA will start collecting **timeliness data** in 2026: date received, date closed/resolved/escalated | SRA Update 152 | Those dates as proper date fields, exportable |
| Reasonable adjustments for disabled complainants, free of charge; accept complaints through family with consent | Equality Act 2010 s.20; SRA thematic review Oct 2025 | `reasonable_adjustments`, `on_behalf_of` |
| A complaint alleging negligence or loss is usually a "circumstance" that must be notified to the PII insurer in the policy year; late notification can cost the firm | SRA Indemnity Insurance Rules, Minimum Terms 1.1, 7.2 | `potential_claim` flag, `pii_notified_on` |
| Keep personal data no longer than needed, but may retain to defend future claims; no fixed period in law | UK GDPR Art 5(1)(e), ICO storage limitation guidance | `destruction_due_on` from a firm policy (recommend 6 years after closure or LeO decision, the Limitation Act anchor). No primary source for a specific period, so this is the firm's call |

### Good practice the SRA and LeO look for

- Acknowledge within **two working days** (LeO best practice guide).
- Record **all** complaints including minor and verbal ones; "if it is not clear whether a client is complaining, firms ought to be cautious and record it" (SRA thematic review, Oct 2025, which found 30% of files breached 8 weeks).
- Diarise response dates, feed outcomes back to the fee earner and head of department, analyse root causes, monthly leadership reporting, look for trends. "Not looking out for trends or themes" is listed as poor practice.
- If the firm declines to deal with a beneficiary's complaint, keep a note of the reasons.
- Lexcel 6.5 (*unconfirmed* mirror): named person with overall responsibility; record and report all complaints centrally; tell the complainant in writing how it will be handled and when they will get a response; identify the cause and correct procedures. Lexcel 5.18: at least annual analysis of complaint trends alongside PII claims and file-review data.
- SRA complaint categories (use as the lookup seed): Conduct; Costs information deficient; Costs excessive; Criminal activity; Data protection / breach of confidentiality; Delay; Discrimination; Failure to advise; Failure to comply with agreed remedy; Failure to follow instructions; Failure to investigate complaint internally; Failure to keep informed; Failure to keep papers safe; Failure to progress; Other.

### Coming, not yet in force

- **LeO**: consultation closed 2 Sep 2026, expected 1 Apr 2027: an **extra £400 case fee** where the firm failed to issue a final response within 8 weeks, a detriment threshold, a 12-year long-stop. The 8-week clock becomes a direct cost.
- **SRA**: consultation closed 1 Sep 2026 proposing a timeline at first contact, regular progress updates, a "Complaints Handling Requirements Statement", and the 8.3 information also on conclusion of a matter and on request. An earlier Oct 2025 application to the LSB appears to have been withdrawn in Jan 2026 (*unconfirmed*, seen only in a search snippet).

The design below already captures the timeline and update dates so nothing changes if
these land.

## Why not the three obvious models

**1. Put the matter into a "complaint" status.** `WIP.file_status` is a single FK
(`Open`, `To Be Closed`, `Archived`). A complaint is not a matter state: the matter may
still be live and progressing, may already be archived (most complaints arrive after
the bill), may be complained about twice, and one complaint can span several matters
(the same client, two files). Overloading file status would also break every
`LIVE_STATUSES` filter in `backend/compliance_stats.py`, dashboards and reports. What we
*do* want is a visible banner on the matter home while a complaint is open.

**2. Open a new matter for the complaint.** Tempting because it gives a file number
for the email sync, a ledger and the usual correspondence tabs. But it would create a
fake `WIP` with the complainant as `client1`, pollute conflict checks, AML/risk-review
metrics ("risk assessment due" on a non-matter), time recording and the fee-earner
dashboards, and it could never be "closed" like a real file. It also fails for
complaints that have no matter at all (a prospective client, a beneficiary, the other
side), which the Legal Ombudsman can accept.

**3. Allocate correspondence to a "complaint".** Correspondence is already allocated
to a matter by file number in the subject (`email_sorting.utils.extract_key_and_feeearner`)
or by hand on the unallocated-emails page. The complaint-relevant emails are a subset of
the matter's mail; the register needs to *link* to them, not own them. A complaint
without a matter still needs somewhere to attach its letters.

**So:** a `Complaint` model with an optional link to one or more matters, its own
chronology, its own documents, and a `complaint` tag on existing correspondence rows.
This is the same shape as `Undertaking` (central register, per-matter list on the
matter home) and the call register branch (note-first capture).

## Data model

All new tables live in `backend/models.py` next to `Undertaking`. Choices are
lookup tables, not hard-coded, because the firm will want to add categories.

### `Complaint`

| Field | Type | Why |
|---|---|---|
| `reference` | char, unique, `C-2026-0007` style, auto | Quoted in letters and to the Legal Ombudsman (LeO); never reuse a matter number |
| `matters` | M2M to `WIP`, blank | Zero, one or many; the register is central, not per matter |
| `complainant_name`, `complainant_email`, `complainant_phone`, `complainant_address` | char/text | Not an FK to `ClientContactDetails`: the complainant may be a non-client |
| `complainant_client` | FK `ClientContactDetails`, null | Set when the complainant *is* a client on our books, so their matters list pre-fills |
| `complainant_type` | choice: client, former client, prospective client, beneficiary/estate, third party, other side, other | LeO accepts several of these; SRA wants to see non-client complaints too |
| `on_behalf_of` | char, blank | Representative complaining for the client (attorney, relative) |
| `reasonable_adjustments` | text, blank | Equality Act: record what was asked for / offered |
| `received_on` | date | Starts the 8-week clock |
| `received_via` | choice: letter, email, phone, in person, web form, via LeO, via SRA | |
| `received_by` | FK user | Who took it |
| `about_fee_earner` | FK user, null | Whose work; the complaints officer is usually not this person |
| `handled_by` | FK user | Complaints handling officer for this one (default: the firm's designated complaints handler, a settings value like `RESPONSIBLE_FEE_EARNER_ALIASES`) |
| `summary` | text | Complainant's own words, short |
| `categories` | M2M `ComplaintCategory` | Seeded with the SRA annual-return list (15 categories, see above) so the return is a count, not a translation. One complaint can be several |
| `is_informal` | bool | The LSB definition is wide (any expression of dissatisfaction alleging detriment); staff log a grumble and decide later whether it is formal. The SRA says record it if in doubt. Counts in the register, shown separately |
| `act_or_omission_on` | date, null | Start of LeO's one-year limit (Scheme Rules 4.5) |
| `status` | choice: `received`, `acknowledged`, `investigating`, `final_response_sent`, `resolved` (client satisfied), `closed_unresolved`, `escalated_leo`, `escalated_sra` | The SRA return separates "resolved" (client satisfied) from merely closed, so the two are distinct statuses; SRA timeliness data wants the date each of these happened |
| `acknowledged_on` | date, null | LeO best practice: two working days; the firm's procedure sets its own target |
| `timeline_given_on` | date, null | LSB para 14: a timeline for resolution at first contact |
| `last_update_sent_on` | date, null | LSB para 15: regular updates; the register flags silence over N days |
| `complaints_procedure_sent_on` | date, null | Copy of the procedure sent at the point of complaint |
| `leo_signposted_on` | date, null | Date we told them about LeO (needed both at complaint and in the final response) |
| `final_response_sent_on` | date, null | Ends the 8-week clock; from April 2027 LeO expects to charge £400 extra when this is late |
| `fr_states_leo_available`, `fr_has_leo_contact_details`, `fr_has_six_month_warning` | bool x3 | Scheme Rules 4.4: without all three in the letter, the six-month limit never starts. Shown as a checklist before the status can move to final response |
| `procedure_version_sent` | FK `PolicyVersion`, null | Which version of the complaints procedure went to the complainant |
| `eight_week_deadline` | date, computed, stored | `received_on + 56 days`; stored so reports can sort/filter |
| `outcome` | choice: upheld, partially upheld, not upheld, withdrawn, resolved informally, not a complaint, declined (with reason) | The SRA suggests keeping a note when a beneficiary's complaint is declined, hence `declined_reason` text |
| `outcome_summary` | text | What we found and why |
| `redress_type` | choice/multi: apology, fee reduction, fee waiver, compensation, work redone, other | |
| `redress_amount` | decimal, null | £ value of any reduction/compensation; LeO and insurers ask |
| `redress_credit_note` | FK `CreditNote`, null | When the redress was a credit note on the matter, link it so the ledger and register agree |
| `root_cause` | text | What went wrong internally |
| `lessons_learned` | text | Action taken (training, template change, process change) |
| `potential_claim`, `pii_notified_on` | bool, date null | A complaint alleging negligence or loss is a "circumstance" under the PII minimum terms; late notification can leave the firm paying. Auto-suggest the flag when a category is failure to advise / failure to progress / costs excessive |
| `leo_reference`, `leo_outcome`, `leo_decision_on` | char/choice/date, null | If it goes to the ombudsman |
| `sra_reported`, `sra_reference` | bool/char | If reported to the SRA |
| `closed_on`, `closed_by` | date / FK | |
| `review_signoff_status`, `signed_off_by`, `signed_off_at`, `signoff_comments` | same shape as `RiskAssessment` | COLP/manager sign-off before closing; feeds the existing sign-off queue |
| `reporting_year` | int, derived | SRA year runs 1 Sep to 31 Aug |
| `destruction_due_on` | date, computed | Closure or LeO decision plus the firm's retention period (recommend 6 years) |
| `created_by`, `timestamp` | | |

### `ComplaintCategory`

`name`, `is_active`, `created_by` — mirrors `MatterType`/`FileStatus`.

### `ComplaintEvent` (the chronology)

| Field | Notes |
|---|---|
| `complaint` FK | |
| `kind` | choice: received, acknowledged, call, meeting, letter sent, letter received, email, internal note, investigation step, final response, LeO contact, SRA contact, redress given, closed, reopened |
| `occurred_on` | datetime |
| `by` | FK user |
| `note` | Quill (as attendance notes) |
| `email` FK `MatterEmails` null, `letter` FK `MatterLetters` null, `attendance_note` FK `MatterAttendanceNotes` null | Link to the existing correspondence row rather than copying it |
| `document` | FileField, optional, private storage (same pattern as `MatterClientDocument`) |

A complaint's "file" is this chronology plus the linked correspondence. It is enough
for LeO, who ask for "the complaint file" when they take a case on.

### Tagging existing correspondence

Add `complaint = FK(Complaint, null)` to `MatterEmails`, `MatterLetters` and
`MatterAttendanceNotes`. The correspondence page gets a "Mark as complaint
correspondence" action (one click, chooses from open complaints on that matter) and the
complaint page shows everything tagged. Email sync stays unchanged; no new mailbox
rules. A later nicety: if the subject contains a `C-2026-0007` reference, the sync
tags the email automatically, the way it already matches `ANP9000004`.

### What *not* to add

- No new `FileStatus`. The matter keeps its real status.
- No new `WIP`. A complaint without a matter is a `Complaint` with an empty `matters` set.
- No separate "complaint ledger". Fee reductions are credit notes on the matter, linked from the complaint.

## Screens

Following the "embed on existing pages" rule, there is one new standalone page (the
register itself, like Undertakings) and everything else is a card or banner on pages
that already exist.

1. **Complaints register** (`/complaints/`, navbar next to Undertakings; manager-only
   list of everything, fee earners see complaints about them and ones they handle).
   Table: reference, complainant, matter(s), fee earner, received, 8-week deadline
   with a red/amber badge, status, handler, outcome. Filters: status, year, fee earner,
   category. CSV export through the existing `render_report` helper.
2. **Log a complaint** (`/complaints/add/`): note-first form. Minimum to save:
   complainant name, how it arrived, date received, summary. Everything else can
   follow. Picking a client pre-fills their matters; picking a matter pre-fills the
   fee earner.
3. **Complaint detail** (`/complaints/<ref>/`): header with the clock
   ("Day 23 of 56"), status stepper (received → acknowledged → investigating → final
   response → closed), chronology with "add event", linked correspondence, documents,
   outcome/redress/root-cause panel, sign-off panel. Audit trail via `Modifications`.
4. **Matter home banner + card**: red banner "Open complaint C-2026-0007 (day 23)" when
   any linked complaint is open; a "Complaints" card next to Undertakings listing all
   complaints on the file, open or closed. Also surface on the **file review** form:
   the existing "Have any complaints been raised…" question pre-answers Yes with links.
5. **Dashboard card** (staff): "Complaints I am handling" with the clock.
   **Management reports card** (managers): open complaints, overdue, awaiting sign-off.
6. **Compliance stats**: a new group "Complaints" with metrics acknowledged within
   two working days, timeline given at first contact, final response within 8 weeks,
   final response letter checklist complete, closed with root cause recorded, PII
   notified where a claim is alleged. Remove "Complaints log and response times" from
   `NOT_TRACKED`.
7. **Reports hub**: "Complaints register" (year filter, CSV) and an **annual
   complaints review** report: counts by category, outcome, fee earner, average days to
   final response, LeO referrals and their outcomes, total redress. Also an **SRA
   annual return** view: received / resolved / referred to LeO for the year to 31 Aug,
   by category, which is exactly what the renewal form asks for, plus the received and
   closed dates the SRA's 2026 timeliness collection wants.
8. **Morning digest / sign-off queue** (on `feature/compliance-stats-refresh`): add
   complaints at day 42+ with no final response, and complaints awaiting sign-off.

## Permissions

- Anyone can log a complaint (the SRA expects any member of staff to recognise one).
- Only the handler, managers and the designated complaints officer can edit the
  investigation, outcome and redress.
- The fee earner complained about can read and add chronology notes but cannot sign
  off or close. Enforce in the view; use `is_manager` plus a new
  `COMPLAINTS_OFFICER` setting (staff code) rather than a new role field, matching how
  `RESPONSIBLE_FEE_EARNER_ALIASES` is done.

## Phasing

| Phase | Scope | Rough size |
|---|---|---|
| 1 | Models + migration, register list, log form, detail with chronology, matter home card and banner, audit | 2–3 days |
| 2 | Correspondence tagging, documents, credit-note link, sign-off, dashboard and management cards | 1–2 days |
| 3 | Compliance stats group, reports hub entries, annual review report, digest/queue hooks | 1 day |
| 4 | Email auto-tag by complaint reference, LeO/SRA escalation panels, retention date | ½ day |

Phase 1 alone replaces whatever spreadsheet exists today and meets the record-keeping
requirement. Each phase is a separate worktree off `origin/main` per the usual workflow.

## Decisions needed from the firm before building

1. Who is the designated complaints handler, and who steps in when the complaint is
   about them?
2. The firm's own acknowledgement and response targets. The procedure is not in
   the app's policy table locally, so it must be read from the published one. Default
   to LeO's two working days for acknowledgement and 8 weeks for the final response.
3. Should an "expression of dissatisfaction" that is resolved on the spot be logged?
   (Recommended yes, flagged as informal, so trends are visible.)
4. Is there an existing complaints spreadsheet or paper log to import? If yes, a
   one-off management command.
5. Retention period for the complaint file after closure. No rule sets one; 6 years
   after closure or the LeO decision is the usual anchor.
6. Whether the complaints procedure should be loaded into the Policies section so the
   register can record which version was sent.

## Open questions for the code

- `backend/views.py` is 13k lines; the new views go in `backend/complaints_views.py`
  with logic in `backend/complaints.py`, mirroring `estate_account*.py`.
- The sign-off queue and digest live on an unmerged branch; phase 3 depends on that
  landing first or being rebased onto it.
- `Modifications` is a generic FK so audit works unchanged; use `log_created` and
  `build_form_field_changes` from `backend/audit.py`.

## Appendix: sources

- SRA Code of Conduct for Solicitors: https://www.sra.org.uk/solicitors/standards-regulations/code-conduct-solicitors/
- SRA Code of Conduct for Firms: https://www.sra.org.uk/solicitors/standards-regulations/code-conduct-firms/
- SRA Transparency Rules: https://www.sra.org.uk/solicitors/standards-regulations/transparency-rules/
- SRA thematic review of first-tier complaints handling (Oct 2025): https://www.sra.org.uk/sra/research-publications/first-tier-complaints-handling/ and PDF https://www.sra.org.uk/globalassets/documents/sra/research/thematic-review-of-first-tier-complaints-handling.pdf
- SRA bulk renewal guidance (annual complaints questions and categories): https://www.sra.org.uk/mysra/updates/bulk-renewal/
- SRA Update 152, complaints timeliness data collection: https://www.sra.org.uk/news/news/sra-update-152-complaints-data-collection
- SRA first-tier complaints consultation 2026: https://www.sra.org.uk/news/news/press/first-tier-complaints-consultation-2026
- SRA application to LSB, Oct 2025: https://legalservicesboard.org.uk/wp-content/uploads/2025/10/SRA-application-to-LSB-changes-to-first-tier-complaints-regulatory-arrangements-14-10-2025.pdf
- SRA Indemnity Insurance Rules and Minimum Terms: https://www.sra.org.uk/solicitors/standards-regulations/indemnity-insurance-rules/
- LeO Scheme Rules (April 2023): https://www.legalombudsman.org.uk/media/oughytel/scheme-rules-april-23-final.pdf
- LeO signposting guidance: https://www.legalombudsman.org.uk/for-legal-service-providers/learning-resources/signposting-consumers-to-the-legal-ombudsman/
- LeO best practice complaint handling guide: https://www.legalombudsman.org.uk/for-legal-service-providers/learning-resources/good-complaints-handling/best-practice-complaint-handling-guide/
- LeO scheme rules / case fee consultation (June 2026): https://www.legalombudsman.org.uk/media/j1sbcbvm/olc-scheme-rules-case-fee-and-publishing-decisions-consultation-june-2026-v10.pdf
- Legal Services Act 2007 s.112: https://www.legislation.gov.uk/ukpga/2007/29/section/112
- LSB s.112 Requirements (May 2024): https://legalservicesboard.org.uk/wp-content/uploads/2024/05/s112-Requirements.pdf
- Equality Act 2010 s.20: https://www.legislation.gov.uk/ukpga/2010/15/section/20
- ICO storage limitation: https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/data-protection-principles/a-guide-to-the-data-protection-principles/storage-limitation/
- Law Society, "Do we have to keep a record of complaints?": https://communities.lawsociety.org.uk/features/faq-do-we-have-to-keep-a-record-of-complaints/6003632.article
- Lexcel v6.1 standard (assessor mirror, unconfirmed): https://recognisingexcellence.co.uk/wp-content/uploads/2021/04/lexcel-standard-legal-practices-v61.pdf

Not verified: Law Society practice note "Handling complaints" (403 on every URL), CQS
complaints requirements, the outcome labels upheld / partially upheld / not upheld
(convention, not a rule).
