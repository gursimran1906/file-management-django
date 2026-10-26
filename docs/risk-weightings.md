# Risk assessment weightings (version 2026.1)

Generated from `backend/risk_scoring.py` by `python manage.py risk_weightings`. Do not edit by hand.

Each weight is given with the reason it is set where it is. LSAG 5.13 expects a practice to be able to explain its weightings, and suggests short notes on the rationale for each as a useful addition to the risk assessment.

A side scores the sum of its sections, each section capped. A total under 12 is low, 12 to 29 medium, 30 or more high. A section that reaches its own medium or high point sets the rating on its own, whatever the total comes to.

## Client risk

### Client and parties

Capped at 30. Alone makes the rating medium at 10 and high at 24.

*The ceiling is 30 because one answer here - a designated person - is decisive on its own. High at 24 means two substantial concerns about the client reach high risk without a third.*

- Client or a party is a designated person/entity &mdash; `designated_person_entity` = Yes, **high risk outright**
  - Acting for a designated person risks breaching financial sanctions, which carries criminal liability and does not depend on what we knew. No score threshold is appropriate.
- Adverse media about the client or a beneficial owner &mdash; `adverse_media` = Yes, **adds 12**
  - Information about the client from outside our own file, which usually points at something they have not told us. The heaviest of the judgement-based client factors.
- Concerns about the client, agent or third parties &mdash; `concerns_about_parties` = Yes, **adds 10**
  - A fee earner’s concern about anyone involved. Just below adverse media: a professional impression rather than an independent source, but it reaches medium on its own.
- Concerns about the client &mdash; `client_concerns` = Yes, **adds 8**
  - Capacity, undue influence or vulnerability. A real risk to the retainer, and sometimes a sign the client is fronting for someone, but not by itself a laundering indicator.
- Unusual client for this type of work &mdash; `unusual_client` = Yes, **adds 8**
  - Our own baseline being broken. The SRA’s sectoral risk assessment treats work outside a firm’s normal profile as a warning sign, which matters more at a local firm with a narrow client base.
- No evidence of a third party’s authority to act &mdash; `third_party_authority` = No, **adds 8**
  - Acting on an instruction we cannot show was authorised. Weighted with the other 8s because it is a gap in our own evidence rather than a fact about the client.

### Geographic risk

Capped at 25. Alone makes the rating medium at 8 and high at 20.

*Medium at 8 so a single overseas element registers, because for a local firm that is already outside the normal pattern. High at 20 is reachable only by the mandatory triggers or by both judgement answers together.*

- A party is established in a high-risk third country or jurisdiction &mdash; `high_risk_third_country_or_jurisdiction` = Yes, **high risk outright**
  - MLRs reg 33(1)(b) makes enhanced due diligence mandatory. The listing is an external determination, not our judgement, so it does not wait on a score.
- Matter involves a country subject to sanctions &mdash; `country_subject_to_sanctions` = Yes, **high risk outright**
  - Sanctions exposure is a criminal-liability question rather than a risk-appetite one, so it is treated like a designated person.
- Concerns about the client’s location &mdash; `location_of_instruction_concerns` = Yes, **adds 10**
  - Weighted to reach medium on its own: an unexplained location is one of the oldest laundering signals.
- Location of the instruction does not make sense &mdash; `make_sense_location_of_instructions` = No, **adds 10**
  - The other side of the same judgement - why is a client there instructing a high-street firm here - so it carries the same weight.
- Overseas elements involved &mdash; `overseas_elements` = Yes, **adds 8**
  - Below the two concerns above, because an overseas beneficiary or asset is common in probate and conveyancing without being suspicious. It still scores: this firm sees few of them.

### Delivery channel

Capped at 15. Alone makes the rating medium at 10 and high at 15.

*The ceiling is low because remote working is normal. High at 15 needs both answers, which is deliberate: a client never met, whose identity was never properly verified, has not really been identified at all.*

- Client will not be met in person &mdash; `meeting_in_person` = No, **adds 8**
  - MLRs reg 33(2) lists non-face-to-face among the factors to consider. On its own it is routine now, so it scores below medium.
- Identity not verified from a certified or verified electronic source &mdash; `id_verified_reliable_source` = No, **adds 10**
  - Heavier than not meeting the client, because it is a failure of verification rather than of channel. The SRA’s August 2026 sectoral risk assessment makes AI-generated documents and deepfakes the technology risk, so images the client supplies are no longer evidence.

### Structure and ownership

Capped at 20. Alone makes the rating medium at 10 and high at 20.

*Only relevant to entity clients, so the ceiling is moderate; high needs two of these together, which would describe an entity whose ownership we cannot actually see.*

- Owners or directors appear unconnected to the business, or to be nominees &mdash; `nominee_or_unconnected_directors` = Yes, **adds 12**
  - The heaviest here because it goes to who is really behind the client. New in the SRA’s August 2026 assessment, which links nominee and "ghost director" arrangements to organised crime and modern slavery.
- Complex or unusual structure &mdash; `complex_structure_or_unusual` = Yes, **adds 10**
  - Complexity is not wrongdoing, but it is the usual means of obscuring ownership, so it reaches medium alone.
- Reportable discrepancies identified &mdash; `reportable_discrepancies` = Yes, **adds 8**
  - A discrepancy is a fact rather than a judgement, but it is often administrative, so it is weighted below the two above.
- Companies House not checked, or filed details do not match &mdash; `companies_house_checked` = No, **adds 8**
  - New in August 2026: original documentation from dissolved companies is used to establish false credentials. Weighted as a gap in our checking rather than as evidence of risk.

### PEP and sanctions

Capped at 30. Alone makes the rating medium at 15 and high at 28.

*High at 28 is reachable only by the two automatic triggers, so a domestic PEP lands at medium as the Regulations intend rather than being pushed to high by this section alone.*

- Financial sanctions concerns &mdash; `financial_sanctions` = Yes, **high risk outright**
  - Same reasoning as a designated person: criminal liability, not risk appetite.
- Non-domestic PEP, family member or close associate &mdash; `pep_type` = Non-domestic, **high risk outright**
  - Reg 35 makes enhanced due diligence and senior management approval mandatory, and the foreign-official risk is what the PEP regime was written for.
- Domestic (UK) PEP, family member or close associate &mdash; `pep_type` = Domestic, **adds 20**
  - Since 10 January 2024 reg 35(3A) requires a domestic PEP to start from a lower level of risk than a non-domestic one, with enhanced measures applied to a lesser extent. 20 puts it in medium while still requiring enhanced due diligence.

### Due diligence completeness

Capped at 20. Alone makes the rating medium at 8 and high at 20.

*These are things we have not done rather than facts about the client, so each reaches medium but it takes all three to reach high - at which point the file has no real due diligence on it.*

- Source of funds questionnaire not completed &mdash; `is_source_of_funds_questionnaire_completed` = No, **adds 8**
  - The SRA found a quarter of the files it reviewed in 2025-26 lacked adequate source of funds evidence, and nine per cent of files needing checks had none. Weighted to reach medium on its own for that reason.
- Relying on due diligence from an earlier matter or another office &mdash; `relying_on_previous_due_diligence` = Yes, **adds 8**
  - "Passporting", new in August 2026: checks carried over without asking whether they are still appropriate for this matter. Same weight as missing source of funds, because the effect is the same - no current due diligence.
- PEP questionnaire not completed &mdash; `is_pep_questionnaire_completed` = No, **adds 6**
  - Below source of funds: PEP status is also screened elsewhere, so the questionnaire is corroboration rather than the only evidence.

## Matter risk

### Type of work and value

Capped at 25. Alone makes the rating medium at 12 and high at 25.

*High at 25 is exactly high-risk work at £1m or more, which is LSAG 5.12’s own worked example of a category-based rating. Medium at 12 means high-risk work is at least medium before anything else is known about it, which is what "inherent" means.*

- High inherent risk work &mdash; **adds 15**
- Medium inherent risk work &mdash; **adds 8**
- Low inherent risk work &mdash; **adds 0**
  - Every matter starts from the inherent risk of the work, before anything about this client is known. 15 points puts high-risk work at medium before any answer is given, which is what the SRA means by conveyancing carrying the highest inherent risk; low-risk work starts at nothing so the rating is driven entirely by the answers.
- Transaction value £1m or more &mdash; **adds 12**
- Transaction value £500k or more &mdash; **adds 6**
  - Value is a proxy for how much can be moved through the firm in one transaction. The £1m step is LSAG 5.12’s own example of a category-based rating, and 12 points is set so that high-risk work at £1m reaches the section ceiling and so high risk, as that example intends. £500k scores half, reaching medium on high-risk work without claiming the transaction is itself exceptional.

Inherent risk is set per matter type in admin. Currently:

- (not available: no database)

### Nature of the instruction

Capped at 25. Alone makes the rating medium at 12 and high at 15.

*High at 15 is the lowest floor anywhere here, so the single answer below reaches it alone. An instruction that does not fit the client is the classic laundering pattern, and it should be considered for a report rather than averaged into a total.*

- Transaction inconsistent with the client’s profile or does not make sense &mdash; `consistent_with_client_profile` = No, **adds 15**
  - The heaviest single matter answer, and enough for high risk by itself. LSAG 5.11 lists a matter that does not fit the client’s profile among the higher-risk factors; a fee earner answering No here is describing the thing the regime exists to catch.
- Not our usual type of work &mdash; `usual_work` = No, **adds 12**
  - Work we do not normally take is work we are least able to judge, and the firm’s own controls are built around its usual files. Reaches medium alone.
- Matter involves a complex structure &mdash; `complex_structure` = Yes, **adds 8**
  - Weighted below the client’s own structure being complex: building a structure is ordinary transactional work, where an already-opaque client is a question about who we are acting for.

### Sector risk

Capped at 20. Alone makes the rating medium at 10 and high at 20.

*Two factors of 12 against a ceiling of 20: either reaches medium, both reach high. A cash-intensive business in a high-risk sector is the combination the 2026 sectoral assessment describes.*

- High-risk industry or sector &mdash; `high_risk_industry, higher_risk_sector` = Yes, **adds 12**
  - Sector is an inherent property of the work rather than a judgement about this client, so it is weighted to reach medium without tipping to high on its own.
- Cash-intensive industry or business activity &mdash; `cash_intensive_industry, cash_intensive_business_activity` = Yes, **adds 12**
  - Cash intensity is the classic placement route and is one of the three headings the SRA added in August 2026. Weighted level with sector risk because the two usually travel together.

### Movement of funds

Capped at 25. Alone makes the rating medium at 10 and high at 25.

*Any one of these reaches medium; high needs all three, which describes money arriving from several directions at once with no clear reason - the pattern, rather than any single leg of it.*

- Receiving funds from overseas &mdash; `receiving_funds_from_overseas` = Yes, **adds 12**
  - The heaviest of the three: it puts the origin of the money beyond what we can check, and beyond UK supervision.
- Receiving funds from third parties &mdash; `receiving_funds_from_third_parties` = Yes, **adds 10**
  - Money from someone who is not our client breaks the link between the client’s means and the transaction. Common and often innocent - family gifts in conveyancing - so it sits below overseas funds.
- Non-transactional matter that still moves funds or assets &mdash; `movement_of_funds_assets` = Yes, **adds 10**
  - Advisory work that nonetheless moves money is outside the pattern the file appears to be, which is why it is asked at all.

### Transaction red flags

Capped at 35. Alone makes the rating medium at 10 and high at 28.

*The largest ceiling, because this is where the serious answers live. High at 28 takes two of the reg 33(1)(f) answers together, while the two automatic triggers do not wait for a total at all.*

- Proliferation financing risk &mdash; `proliferation_financing` = Yes, **high risk outright**
  - Proliferation financing is a national-security matter with its own reporting expectations; a scored threshold would be inappropriate.
- No apparent economic or legal purpose &mdash; `lack_of_economic_or_legal_purpose` = Yes, **high risk outright**
  - A transaction with no purpose we can identify is, on its face, a transaction whose purpose is something else. This is the point at which a report should be considered, so it is high risk outright.
- Unusually complex or large transaction &mdash; `unusual_complex_transaction` = Yes, **adds 15**
  - Reg 33(1)(f) already makes enhanced due diligence mandatory here, so the weight only has to carry the rating: 15 reaches medium, and with the pattern answer, high.
- Unusual pattern of transactions &mdash; `unusual_pattern_of_transactions` = Yes, **adds 15**
  - The other half of reg 33(1)(f) and weighted identically: a single odd transaction and a pattern of them are the same provision.
- Other AML/CTF risks &mdash; `other_risks` = Yes, **adds 10**
  - A catch-all, weighted to reach medium so that a fee earner’s concern is never scored as nothing, but not higher, because what it describes is unknown.
- Other high-risk factors &mdash; `other_high_risk_factors` = Yes, **adds 10**
  - The same catch-all on the enhanced due diligence side, weighted the same way and for the same reason.

## Automatic enhanced due diligence

These answers require enhanced due diligence whatever the score, and cannot be reduced on the form.

- A party is established in a high-risk third country (reg 33(1)(b)) (`high_risk_third_country_or_jurisdiction` = Yes)
- Non-domestic PEP involved (reg 35) (`pep_type` = Non-domestic)
- Domestic PEP involved (reg 35, to a lesser extent) (`pep_type` = Domestic)
- Financial sanctions concerns (`financial_sanctions` = Yes)
- Client or a party is a designated person/entity (`designated_person_entity` = Yes)
- Matter involves a country subject to sanctions (`country_subject_to_sanctions` = Yes)
- Unusually complex or large transaction (reg 33(1)(f)) (`unusual_complex_transaction` = Yes)
- Unusual pattern of transactions (reg 33(1)(f)) (`unusual_pattern_of_transactions` = Yes)
- Transaction lacks an apparent economic or legal purpose (`lack_of_economic_or_legal_purpose` = Yes)
- Proliferation financing risk (`proliferation_financing` = Yes)
