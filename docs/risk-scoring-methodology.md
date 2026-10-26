# How client and matter risk is rated

This note describes how the practice management system arrives at a client and
matter risk rating, and why it does it that way. It is written so that it can be
referred to from, or appended to, the firm-wide risk assessment: LSAG AML
Guidance 5.13 expects a practice's weightings, and any departure from the
national or sectoral risk assessments, to be documented.

The weightings themselves are in
[`risk-weightings.md`](risk-weightings.md), which is generated from the code
that applies them (`python manage.py risk_weightings`) so the two cannot drift
apart. Every weight there is given with the reason it is set where it is, as
LSAG 5.13 suggests ("short complementary notes explaining the rationale for
each weighting may be a useful addition to the risk assessment"), and the same
reasons appear in the assessment form itself under "why each question carries
the weight it does" — so a fee earner can see why an answer counts for what it
does at the moment they give it.

## What changed, and why

Until now a fee earner answered the questions on the risk assessment and then
chose the client and matter risk levels. Nothing on the file connected the
answers to the rating.

The SRA's AML annual report for 2025-26 found client and matter risk
assessments to be the single largest cause of its referrals: 16% of the files
it reviewed had no assessment or an incomplete one, and a further **39% did not
effectively evaluate the money laundering risk**. A rating chosen by hand, with
no recorded reasoning, is exactly what that finding describes.

The system now scores the answers and pre-fills the rating, and shows the
working beside the questions, on the matter page and in the PDF. The rating can
still be changed — but only with a written reason, which is kept with the
assessment and reported on.

## The shape of the assessment

Two scores are produced, from the risk factor headings LSAG sets out:

- **Client risk** — the client and the parties, geographic risk, delivery
  channel, structure and ownership, PEP and sanctions, and whether the due
  diligence itself is complete.
- **Matter risk** — the type of work and its value, the nature of the
  instruction, sector risk, the movement of funds, and transaction red flags.

The **overall risk** is the higher of the two. LSAG 5.13: "Where either, or
both, the customer and the service are considered to carry a higher risk of
money laundering or terrorist financing, it may be appropriate to consider the
overall risk of the matter as high risk."

## How the scoring works

**Answers are weighted, not counted.** Each answer that indicates risk carries
points in proportion to how much it tells you. LSAG's own illustration is that
a client's personal links to a higher-risk jurisdiction might add 7 points
where the high-risk nature of the service sought adds 5. The weight is printed
beside each question on the form, and the panel alongside sets out the section
ceilings and the points at which a section sets the rating on its own — both
read from the scoring itself, so what the form shows is what it applies.

**Each section is capped.** No single section can dominate the total, so the
weighting is not "unduly influenced by one factor".

**A serious section sets the rating on its own.** This is the important one.
LSAG's worked example of *inappropriate* scoring is an assessment where
geographic risk and client risk each score 20 out of 20, the total of 40 falls
below a threshold of 50, and the matter is therefore rated low. Here, each
section has its own medium and high points: when a section reaches its high
point, the rating is high whatever the total comes to. A client who will not be
met in person and whose identity was never verified from a reliable source is
high client risk even though almost every other answer is clean.

**Some answers do not wait for a score.** These make the matter high risk
outright: a designated person or entity, financial sanctions concerns, a party
in a high-risk third country, a country subject to sanctions, a non-domestic
PEP, proliferation financing, and a transaction with no apparent economic or
legal purpose.

**A fact is counted once.** The form used to ask about cash intensity, high-risk
sectors and whether the instruction makes sense for the client in two places
each. It now asks once, and the scoring reads both the old and the new field so
that assessments completed before the change still score on what they answered.

**Totals.** Under 12 is low, 12 to 29 medium, 30 or more high. These are per
side, after each section's cap.

## The type of work

The matter score starts from the inherent risk of the type of work, before
anything about the particular client or matter:

| Matter type | Inherent risk | Starting points |
| --- | --- | --- |
| Conveyancing | High | 15 |
| Probate | Medium | 8 |
| Family | Low | 0 |

This follows the SRA's sectoral risk assessment, which keeps conveyancing as
the highest inherent risk area of law and notes that its MLRO's reports
consistently show conveyancing generating the most reports. Most family work
falls outside the regulated sector unless it moves property or funds. These
values are set per matter type in the Django admin and can be retuned without a
code change — if the firm takes on a new area of work, set its inherent risk
when the matter type is created.

Transaction value adds 6 points at £500,000 and 12 at £1,000,000. The £1m step
is LSAG's own example of a category-based rating ("conveyancing matters of value
£1,000,000 or more are high risk"), and in combination with conveyancing's
starting points it produces a high matter rating, as intended.

## Due diligence level

Enhanced due diligence is applied where the overall rating is high, and
separately where the Money Laundering Regulations require it whatever the
score: a high-risk third country (reg 33(1)(b)), a PEP (reg 35), sanctions or a
designated person, an unusually complex or large transaction or an unusual
pattern of transactions (reg 33(1)(f)), a transaction with no apparent economic
or legal purpose, or proliferation financing.

A **risk rating** is a judgement and can be overridden. A **mandatory enhanced
due diligence requirement is not**, and the form will not accept standard due
diligence where one of the triggers above is present. If an answer is wrong,
the answer should be changed.

Simplified due diligence is deliberately not offered. LSAG 6.20 notes that,
depending on a practice's own risk assessment, it may not be appropriate for a
practice to use SDD at all; the firm's position is that it does not. If that
position changes, it needs to be recorded in the firm-wide risk assessment
before the option is enabled.

### PEPs

A domestic (UK) PEP and a non-domestic PEP are recorded separately, because
since 10 January 2024 the Regulations (reg 35(3A)) require a domestic PEP to be
treated as presenting a lower level of risk than a non-domestic one, with
enhanced measures applied to a lesser extent. A non-domestic PEP is high risk
outright; a domestic PEP scores into medium. Either way enhanced due diligence
applies and senior management approval is required (reg 35(1)).

## Enhanced due diligence is now recorded, not just decided

The questions that decide whether enhanced due diligence applies are asked on
every file — that is how you find out whether it applies. What was previously
missing was the other half: what was actually done about it.

Where enhanced due diligence applies, the assessment now requires the
additional measures taken, how the matter will be monitored more closely, source
of wealth evidence, and — for a PEP — who approved it and when. A new compliance
report, "Enhanced due diligence completed", lists live matters where enhanced
due diligence was decided on but the measures were never recorded. The SRA found
that a quarter of the files it reviewed lacked adequate source of funds
evidence; this is the gap behind that figure.

## Overriding the rating

LSAG 5.13 requires that a practice can "override any automatically generated
risk scores where necessary with the rationale for the decision to override
such scores being documented appropriately".

The rating dropdowns are therefore still editable. If what is recorded differs
from what the answers scored, the form demands a reason, and that reason is
stored with the assessment, shown on the matter page, printed in the PDF and
recorded in the audit trail. A new compliance report, "Risk rating as scored",
lists live matters rated *below* their score — rating down is what a supervisor
and the regulator will want to look at; rating up is caution and needs no
explanation beyond the one given.

## Questions added for the 2026 sectoral risk assessment

The SRA substantially rewrote its sectoral risk assessment on 6 August 2026 and
firms must take the new headings into account under reg 18(2)(a). Four
questions were added to the assessment to cover them:

- **Passporting** — whether we are relying on due diligence from an earlier
  matter or another office rather than carrying out fresh checks.
- **Companies House** — whether a corporate client has been checked as still
  live, with the filed details matching what we have been told. Criminals use
  original documentation from dissolved companies to establish false
  credentials.
- **Nominee or unconnected directors** — part of the new cash-intensive
  business heading, which links nominee and "ghost director" arrangements to
  organised crime and modern slavery.
- **Remote identity verification quality** — whether identity was verified from
  a certified or verified electronic source rather than from images the client
  supplied. Technology risk in the 2026 assessment is AI-enabled fraud and
  deepfakes.

## Limits of this, and review

The scoring rates what it is told. It cannot tell whether an answer is honest
or well judged, which is what fee earner sign-off and file review are for. It
does not search external sources: sanctions, PEP and adverse media screening
remain separate checks whose outcome is recorded as an answer here.

Assessments completed before this change keep the rating they were given and
are marked as rated by hand; they are scored the next time they are edited. The
questions added in 2026 were never put to the fee earner on those files, so
re-scoring them automatically would have been misleading.

The weighting version is stored on every assessment, along with the full
breakdown as it stood when the assessment was saved, so an old rating can still
be explained with the weights that produced it rather than with today's.

**This note and the weightings should be reviewed at least annually, alongside
the firm-wide risk assessment, and whenever the SRA updates its sectoral risk
assessment.** Changing a weight means bumping `SCORING_VERSION` in
`backend/risk_scoring.py` and regenerating `risk-weightings.md`.

## Sources

- Legal Sector Affinity Group, *Anti-Money Laundering Guidance for the Legal
  Sector* — 5.12 (undertaking client/matter risk assessments), 5.13 (risk
  weightings, including the inappropriate scoring example), 5.14 (recording),
  6.20 (simplified due diligence)
- SRA, *Sectoral risk assessment* (rewritten 6 August 2026)
- SRA, *AML annual report 2025-26*
- SRA, *Client and matter risk assessment template*
- Money Laundering, Terrorist Financing and Transfer of Funds (Information on
  the Payer) Regulations 2017 — regs 18, 28, 33, 35, 37
