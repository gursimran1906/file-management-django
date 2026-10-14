# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Staff of ANP Solicitors, a UK law firm: fee earners, cashiers and managers, using the system at their desks through the working day. The primary user is a fee earner working one matter at a time, moving between its home page, correspondence, finances and compliance sections. Managers additionally review reports, sign-offs and compliance statistics. *(Inferred from the codebase and CLAUDE.md; not interviewed.)*

## Product Purpose

An internal practice-management system that tracks a matter (case) end to end: client and AML onboarding, risk assessment, time and finance ledgers, invoices, estate accounts and completion statements, correspondence, court bundles and staff HR. It also files incoming email and meeting notes against matters automatically. Success is a complete, auditable file for every matter with as little re-keying as possible.

## Positioning

Built around the firm's own file numbers, mailboxes and workflows rather than a generic practice-management product, and integrated with the firm's Microsoft 365 tenant (shared mailboxes, SharePoint document libraries) so documents and email live where the firm already keeps them. *(Inferred.)*

## Operating Context

- Every matter is identified by a file number (three letters and seven digits) that staff put in email subjects; the system files email by it.
- Six shared department mailboxes (main office, conveyancing, dispute resolution, private client, family, risk management) plus personal staff mailboxes.
- Documents are stored in SharePoint document libraries; court bundles and now correspondence exports are built there and shared through Microsoft links.
- Regulated environment: SRA rules, anti-money-laundering checks, file reviews, sign-offs and a full audit trail of changes.
- Used on office desktops and laptops; phones are secondary.

## Capabilities and Constraints

- Matters, clients (one primary plus additional), other side, fee earners with aliases, matter types.
- Correspondence: emails ingested from Microsoft Graph every 15 minutes, letters recorded by hand, attendance notes.
- Correspondence export (this feature): a fee earner picks client addresses and mailboxes, the system finds the matter's emails, the user reviews the list, and the system builds Outlook memo-style PDFs with enclosures, an index and the original messages into the matter's SharePoint folder, with a share link and a file-transfer record.
- Long-running jobs run outside the web request (cron worker in production) and report progress to the page.
- Production runs on a small server: memory and disk are constrained, so builds stream files rather than holding an export in memory.
- Login required for every page; brute-force lockout by username.

## Brand Commitments

The incumbent interface: Tailwind with Flowbite, a quiet grey and blue system, Inter-like sans, cards (`div-container`), blue primary buttons, pill status badges. New surfaces inherit it. *(Observed in code, not a stated brand decision.)*

## Evidence on Hand

Real matters, clients and emails exist only in production. Development uses seeded demo data (`seed_*` management commands). No testimonials, benchmarks or marketing claims exist and none should be invented.

## Product Principles

- The file is the unit of work: everything hangs off a matter and its file number.
- Nothing silent: every mutation is audited; exports list what was left out as well as what went in.
- Familiar over novel: staff should recognise every control at a glance.
- Long jobs stay out of the request and keep the user informed.
- Strict about client data: an email belongs to a matter because the system filed it or a listed address is on it, never by a name search.

## Accessibility & Inclusion

Best effort: keyboard-operable controls, visible focus, readable contrast. No formal standard has been set.
