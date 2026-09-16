# Matter AI — Decision Brief

**Bringing Claude to the matter, and the matter to Copilot.**

Internal planning document · AI strategy · for decision
Prepared for: ANP — partners, DPO & engineering · Scope: <10 fee-earners · 2026 pricing & product state

> This is an internal planning document, not legal or procurement advice. Confirm ZDR / abuse-monitoring eligibility, exact in-scope regions, and current pricing directly with each provider's account team before committing — they are contractual and move quickly.

---

## The one idea

Both goals — a **"Matter AI" inside the app** and the app as a **knowledgebase for Copilot** — are the *same backend* exposed twice. Build one secured matter-data layer over the existing Django models plus a search index, then plug it into:

- **(a)** an in-app chat panel via Claude (on AWS Bedrock), and
- **(b)** Microsoft 365 Copilot via an MCP server.

The LLM is the cheap part. The retrieval layer and the security posture are the real work.

---

## 1. What we're starting from

A pass over the codebase sets the honest baseline: this is **greenfield for AI**, which is mostly good news.

- **No AI code exists** anywhere in the repo, and **no REST/GraphQL API** — it's a session-authenticated, server-rendered Django monolith. Nothing to retrofit; both features get built as a new Django app reading the ORM directly.
- **The corpus an AI wants is already captured and keyed to `file_number`**: email bodies (`MatterEmails`), Quill attendance notes (`MatterAttendanceNotes`), full Granola meeting transcripts (`GranolaImportedNote`), letters, tasks, and free-text `key_information` / `comments` on `WIP`. Rich per-matter text, already in Postgres.
- **Documents live in SharePoint** (via Microsoft Graph) in production when `USE_SHAREPOINT=True`; only metadata is in Postgres. Reading document contents goes through the existing `backend/storage/sharepoint.py:read_storage_file_bytes`.
- **There is no search index** — search today is ORM `LIKE` / `icontains`. An "ask across the matter" feature means building the retrieval layer from scratch. The existing Postgres is the natural home (via `pgvector`).
- **Auth is the one real gap**: inbound access is session-cookie + CSRF only. Copilot needs a new Entra ID / OAuth path — a known, bounded piece of work.

---

## 2. The shared backend

One access layer, two consumers. Build the tools once; enforce matter-level permissions once, server-side, against the signed-in user.

```
  Consumer A: Copilot Studio agent  ─┐
  (Teams & Copilot Chat, via MCP)    │
                                     ├─▶  MATTER AI BACKEND (new Django app)  ─▶  Django ORM + SharePoint
  Consumer B: In-app chat panel     ─┘     • Tool / MCP layer                     (existing models & Graph)
  (on the matter page)                     • Read: get matter · search within  ─▶  Claude on AWS Bedrock (EU)
                                             matter · completion statement ·        (zero-retention, in-tenancy)
                                             ledger
                                           • Write: add note · create task
                                             (permission-checked per user)
                                           • Retrieval: pgvector index +
                                             local BGE-M3 embeddings
```

The confidential corpus is only ever exposed to the contractually-protected generation call — **indexing stays in-house** (local embeddings).

**New Django app** (e.g. `matter_ai`) provides:

- **Retrieval layer** — `pgvector` in the existing Postgres; local **BGE-M3** embeddings over emails, notes, transcripts, letters and WIP free-text, keyed by `file_number`.
- **Tool layer** — read tools (`get_matter`, `list_matters_for_client`, `search_within_matter`, `get_completion_statement`, `get_ledger`) and write tools (`add_attendance_note`, `create_task`), each permission-checked against the signed-in user. Reuse the existing `Modifications` audit pattern for writes.
- **Auth** — a new inbound Entra ID / OAuth2 (on-behalf-of) path for the MCP consumer. The in-app consumer reuses the existing Django session.

---

## 3. The two surfaces

### Surface 1 — Copilot as the front door (GA today)

Exactly the "custom agent with MCP to here" idea, and it's supported now. **MCP in Copilot Studio has been generally available since May 2025.**

| | |
|---|---|
| **Shape** | Streamable-HTTP MCP server in front of Django → declarative Copilot Studio agent → Teams & Copilot Chat |
| **Transport** | Streamable HTTP — **not** SSE (SSE deprecated after Aug 2025) |
| **Auth** | OAuth 2.0 / Entra ID, per-user (on-behalf-of) — the agent only sees what that solicitor may see |
| **Hosting** | Power Platform environment in **UK South**; DLP policies on the connector |
| **Data** | Fetched at runtime — **nothing copied** into Microsoft's index |

### Surface 2 — Matter AI inside the app (recommended core)

The same tools, in a chat panel on the matter page: summarise the file, answer questions over its emails/notes/transcripts, draft correspondence — with **every answer cited back to the source record** (Claude citations + RAG returning the email/note/document it used, so no unsourced answers).

| | |
|---|---|
| **Backend** | Claude on **AWS Bedrock, EU region** (see §4) |
| **Models** | Sonnet 5 default · Opus 4.8 for hard drafting · Haiku 4.5 for cheap summarise/classify |
| **References** | Citations link each claim to a matter document |
| **Retrieval** | pgvector + local embeddings; only the generation call leaves the building |

**Why build the in-app side first:** it needs no Microsoft licensing decision, no Entra OAuth server, and no Copilot Studio — it's a chat panel calling Bedrock. It proves the retrieval layer and the value on the cheapest, lowest-risk path. The MCP server for Copilot is then a second consumer of tools already built and secured.

---

## 4. Security & data retention — the crux

For privileged client data, this is the decision that matters.

> **"No retention" is a setting, not the default.** On every mainstream provider, "we don't train on your API data" is true by default. Zero retention is separate — you must explicitly turn it on (Bedrock mode `none`, Azure "modified abuse monitoring", or an Anthropic ZDR agreement), and on Azure/OpenAI it requires an approval step. Don't assume the out-of-the-box behaviour is zero-retention.

| Path | Trains on your data? | Default retention | Zero-retention | EU / UK residency |
|---|---|---|---|---|
| **AWS Bedrock (Claude)** ★ recommended | No | Mode-controlled; provider never receives it | **Yes** — mode `none`, SCP-enforceable | **EU** (Ireland / Frankfurt / Stockholm). UK-soil not confirmed |
| **Azure OpenAI** (M365-native) | No | Up to 30 days, incl. human review | Yes* — "modified abuse monitoring", by application | **UK South** — the route to true UK soil, but it's GPT not Claude |
| **OpenAI API** | No | 30 days abuse logs | Yes* — approved enterprise only | EU — new projects only, +~10% uplift |
| **Anthropic direct API** | No | 30 days | Yes — ZDR commercial agreement | **None** — US / "global" only. Usually disqualifying |
| **Self-hosted (open-weight)** | No — you run it | Whatever you set (can be zero) | Inherent | Total — data never leaves your walls |

### Why Bedrock (EU) wins on privilege

- No training on your data; under `default`/`none`, **nothing is shared with Anthropic**, and data stays inside **your AWS tenancy** (frontable with PrivateLink).
- The retention posture is **technically enforceable** — pin mode `none` org-wide with a Service Control Policy using the `bedrock-mantle:DataRetentionMode` condition key. That is an auditable control, not a promise.
- You get frontier-class drafting (Claude) without buying or operating GPUs.
- Keep zero-retention by simply **not enabling the newest models** (Fable 5 / Mythos 5) that require provider data-sharing — Sonnet 5 / Opus 4.8 / Haiku 4.5 run fine under `none`.

### The one caveat for the DPO: EU vs UK soil

Bedrock gives **EU** residency (Ireland / Frankfurt / Stockholm), not confirmed **UK-soil** — Claude in London `eu-west-2` isn't confirmed in-region. Post-Brexit, EU processing is generally fine for UK firms under UK-GDPR adequacy. But if firm policy or a client's engagement terms demand *"data never leaves the UK"*, the two routes are:

1. **Azure OpenAI in UK South** with modified abuse monitoring — UK soil + no-retention, and M365-native; downside is it's GPT not Claude, and you must qualify for the abuse-monitoring exception.
2. **Self-host** on the firm's own UK infrastructure — total control, cost/quality/ops trade-offs in §5.

**Note:** Claude on *Microsoft Foundry* is tempting because it bills through your Microsoft agreement — but its EU data residency is "coming 2026," not available today, so it fails the residency test for now. Use Bedrock EU for Claude-with-residency.

---

## 5. The local / self-hosted option

Worth it only under one condition: the firm's rule is genuinely *"no client data may ever leave our infrastructure."* Some SRA-cautious firms take exactly that line. Otherwise the economics don't favour it at this scale.

| | |
|---|---|
| **Models** | Qwen3-class / Llama 4 / Mistral Large 3. A 70B-class model is a solid RAG/Q&A engine and decent first-draft writer |
| **Quality** | **Below frontier** on high-stakes drafting — the gap still bites where legal register & low hallucination matter most |
| **Serving** | vLLM (production) · Ollama (prototyping). Not LM Studio |
| **Hardware** | 48 GB box (70B, Q4): **£6–12k** capex · H100 box: **£25–30k+** · cloud H100 rental ~$1.5–3/hr |
| **Your prod box** | 1.9 GB RAM — **cannot run any of this**; local means a separate GPU machine + real MLOps |

> **Do this bit locally regardless:** even if generation runs on Bedrock, **self-host the embedding model** (BGE-M3). Embedding models are tiny and cheap, and it keeps the confidential corpus in-house at indexing time — you only expose text to a third party on the protected generation call.

---

## 6. Costs — sized for <10 fee-earners

**Bedrock has no seats, no subscription, no minimum. It's pure metered usage — it scales from literally £0.** An idle month costs nothing.

**Unit economics (the number to hold onto):** a typical matter query is ~10k input tokens (system prompt + retrieved context + question) + ~800 output tokens. On Claude Sonnet 5 that's about **2–4p per question** (~2p with prompt caching). Drafting queries cost a bit more; quick lookups less.

For ~8 active fee-earners, Sonnet 5 **with prompt caching**:

| Usage per person | Queries/month | Monthly (approx) |
|---|---|---|
| Light (~10 AI actions/day) | ~1,760 | **£35–60** |
| Moderate (~25/day) | ~4,400 | **£90–130** |
| Heavy (~50/day) | ~8,800 | **£180–260** |

Three levers push these *down* further (so you'd realistically land at the low end):

- **Sonnet 5 intro pricing** ($2/$10 per M-token vs $3/$15) through Aug 2026 — knocks ~⅓ off.
- **Model routing** — quick Q&A to Haiku 4.5 ($1/$5), only hard drafting to Sonnet/Opus. Easily halves the Q&A portion.
- **Prompt caching** — RAG re-sends the same system prompt and overlapping context; cached input bills at ~10%.

**Headline for <10 people: ~£40–150/month, scaling from £0, with power-users maybe touching £200.**

### Full cost stack (nothing hidden)

| Component | Cost |
|---|---|
| Bedrock generation | **£40–150/mo** (usage — the table above) |
| Embeddings (self-hosted BGE-M3) | **~£0** — runs on your box; one-off index is free |
| Vector store (pgvector in existing Postgres) | **£0** |
| Infra (runs inside existing Django app) | **£0** incremental |
| Optional: PrivateLink for private networking | ~£6/mo |
| One-off build | Engineering time — the real investment |

Reference pricing (per million tokens): Sonnet 5 $3 / $15 ($2 / $10 intro to Aug 2026) · Opus 4.8 $5 / $25 · Haiku 4.5 $1 / $5. Bedrock's Claude rates track Anthropic list closely but AWS sets them — confirm on the AWS Bedrock pricing page before budgeting to the pound.

### Copilot licensing — the "one master account" question

This splits into two different things:

1. **Copilot inside Word / Outlook / Excel / Teams** is a **per-user add-on** and **cannot be shared off one master account.** It's assigned to a named person, tied to their identity, and Microsoft's terms don't permit sharing a seat — technically it wouldn't work either, because Copilot acts *as that user* and only sees that user's own mailbox and files. Buy seats **only for the few who want it** (e.g. 2–3 partners): ~£15–24/user/month depending on SKU (newer Copilot Business ~$18–21, classic add-on $30) → roughly **£45–70/month for 3 people**.

2. **The custom Matter agent** (the MCP-to-your-app piece) needs **no seats at all.** It runs on **pay-as-you-go consumption**, and all <10 staff access it through **free Microsoft 365 Copilot Chat**. You pay only metered Copilot Credits per agent interaction (~7–12 credits ≈ 7–12p each) — for <10 users at moderate use, maybe **£100–250/month of credits**, which is notably *more per interaction* than calling Bedrock directly in your own app.

> **Strategic implication:** the in-app Matter AI on Bedrock already delivers the "Matter AI" value to everyone at ~2–4p/query with zero Microsoft licensing. The Copilot integration is only about *where* staff reach it (Teams/Office vs your app) — a "meet them where they work" layer, not a second AI.

---

## 7. Recommended roadmap

Sequenced so value and de-risking come before any licensing commitment. Each phase is usable on its own.

**Phase 0 — Prove it.** Build the pgvector index with local BGE-M3 over emails, notes and transcripts. Ship a read-only "ask this matter" panel on Bedrock EU (Sonnet 5), with citations back to source records. Lowest risk, cheapest (£40–150/mo), no Microsoft decision.
*Needs:* Bedrock EU account + retention mode `none` (SCP) · new Django app.

**Phase 1 — Make it act.** Add write tools ("add attendance note", "create task") behind explicit human confirmation. Harden the tool layer and permission checks. This is the reusable core the Copilot side will consume.
*Needs:* tool layer + audit trail (reuse existing `Modifications` pattern).

**Phase 2 — Open the front door.** Wrap the tool layer in a Streamable-HTTP MCP server with Entra OAuth (OBO). Author a declarative Copilot Studio agent in UK South, add the MCP server as a tool, publish to Teams & Copilot Chat. Decide seats vs consumption here.
*Needs:* new inbound Entra OAuth path · Copilot Studio · DLP policy.

**Phase 3 — Optional reach.** Only if wanted: a Graph connector for firm-wide semantic search in base Copilot (requires DPO sign-off, since it copies data into Microsoft's index). Or, if UK-soil becomes mandatory, swap generation to Azure UK South or self-host.
*Needs:* DPO sign-off · governance review.

---

## 8. Decisions for partners & the DPO

Four calls unblock everything else. Recommended answer in each:

1. **EU residency, or strictly UK soil?** — **Recommend EU (Bedrock)** unless a client's terms or firm policy mandate UK-only (then Azure UK South / self-host). This single choice picks the generation backend.
2. **May client data enter Microsoft's semantic index?** — **Recommend no** — keep everything runtime via MCP (data fetched per request, permission-trimmed). Revisit a synced Graph connector only with explicit sign-off.
3. **Zero-retention, or default, on Bedrock?** — **Recommend mode `none`, SCP-enforced**, and skip the newest Claude models that require provider data-sharing.
4. **Copilot: seats or consumption?** — **Recommend buying seats only for the few who want Copilot in Office (~£45–70/mo for 3), and running the matter agent seat-free on consumption for everyone** via free Copilot Chat. Do the in-app Bedrock assistant first regardless — it delivers matter AI to all staff with no Microsoft licensing.

---

*Sources: Microsoft Learn (Copilot Studio MCP GA, licensing, data locations), AWS Bedrock data-retention docs, provider data-handling pages, and Anthropic's current model pricing reference. Current as of mid-2026.*
