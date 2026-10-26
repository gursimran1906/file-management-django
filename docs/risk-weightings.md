# Risk assessment weightings (version 2026.1)

Generated from `backend/risk_scoring.py` by `python manage.py risk_weightings`. Do not edit by hand.

A side scores the sum of its sections, each section capped. A total under 12 is low, 12 to 29 medium, 30 or more high. A section that reaches its own medium or high point sets the rating on its own, whatever the total comes to.

## Client risk

### Client and parties

Capped at 30. Alone makes the rating medium at 10 and high at 24.

| Answer | Points | Automatic high risk |
| --- | --- | --- |
| Client or a party is a designated person/entity (designated_person_entity = Yes) | 30 | Yes |
| Adverse media about the client or a beneficial owner (adverse_media = Yes) | 12 |  |
| Concerns about the client, agent or third parties (concerns_about_parties = Yes) | 10 |  |
| Concerns about the client (client_concerns = Yes) | 8 |  |
| Unusual client for this type of work (unusual_client = Yes) | 8 |  |
| No evidence of a third party’s authority to act (third_party_authority = No) | 8 |  |

### Geographic risk

Capped at 25. Alone makes the rating medium at 8 and high at 20.

| Answer | Points | Automatic high risk |
| --- | --- | --- |
| A party is established in a high-risk third country or jurisdiction (high_risk_third_country_or_jurisdiction = Yes) | 25 | Yes |
| Matter involves a country subject to sanctions (country_subject_to_sanctions = Yes) | 25 | Yes |
| Concerns about the client’s location (location_of_instruction_concerns = Yes) | 10 |  |
| Location of the instruction does not make sense (make_sense_location_of_instructions = No) | 10 |  |
| Overseas elements involved (overseas_elements = Yes) | 8 |  |

### Delivery channel

Capped at 15. Alone makes the rating medium at 10 and high at 15.

| Answer | Points | Automatic high risk |
| --- | --- | --- |
| Client will not be met in person (meeting_in_person = No) | 8 |  |
| Identity not verified from a certified or verified electronic source (id_verified_reliable_source = No) | 10 |  |

### Structure and ownership

Capped at 20. Alone makes the rating medium at 10 and high at 20.

| Answer | Points | Automatic high risk |
| --- | --- | --- |
| Owners or directors appear unconnected to the business, or to be nominees (nominee_or_unconnected_directors = Yes) | 12 |  |
| Complex or unusual structure (complex_structure_or_unusual = Yes) | 10 |  |
| Reportable discrepancies identified (reportable_discrepancies = Yes) | 8 |  |
| Companies House not checked, or filed details do not match (companies_house_checked = No) | 8 |  |

### PEP and sanctions

Capped at 30. Alone makes the rating medium at 15 and high at 28.

| Answer | Points | Automatic high risk |
| --- | --- | --- |
| Financial sanctions concerns (financial_sanctions = Yes) | 30 | Yes |
| Non-domestic PEP, family member or close associate (pep_type = Non-domestic) | 30 | Yes |
| Domestic (UK) PEP, family member or close associate (pep_type = Domestic) | 20 |  |

### Due diligence completeness

Capped at 20. Alone makes the rating medium at 8 and high at 20.

| Answer | Points | Automatic high risk |
| --- | --- | --- |
| Source of funds questionnaire not completed (is_source_of_funds_questionnaire_completed = No) | 8 |  |
| Relying on due diligence from an earlier matter or another office (relying_on_previous_due_diligence = Yes) | 8 |  |
| PEP questionnaire not completed (is_pep_questionnaire_completed = No) | 6 |  |

## Matter risk

### Type of work and value

Capped at 25. Alone makes the rating medium at 12 and high at 25.

| Starting point | Points |
| --- | --- |
| High inherent risk work | 15 |
| Medium inherent risk work | 8 |
| Low inherent risk work | 0 |
| Transaction value £1m or more | 12 |
| Transaction value £500k or more | 6 |

Inherent risk is set per matter type in admin. Currently:

- (not available: no database)

### Nature of the instruction

Capped at 25. Alone makes the rating medium at 12 and high at 15.

| Answer | Points | Automatic high risk |
| --- | --- | --- |
| Transaction inconsistent with the client’s profile or does not make sense (consistent_with_client_profile = No) | 15 |  |
| Not our usual type of work (usual_work = No) | 12 |  |
| Matter involves a complex structure (complex_structure = Yes) | 8 |  |

### Sector risk

Capped at 20. Alone makes the rating medium at 10 and high at 20.

| Answer | Points | Automatic high risk |
| --- | --- | --- |
| High-risk industry or sector (high_risk_industry, higher_risk_sector = Yes) | 12 |  |
| Cash-intensive industry or business activity (cash_intensive_industry, cash_intensive_business_activity = Yes) | 12 |  |

### Movement of funds

Capped at 25. Alone makes the rating medium at 10 and high at 25.

| Answer | Points | Automatic high risk |
| --- | --- | --- |
| Receiving funds from overseas (receiving_funds_from_overseas = Yes) | 12 |  |
| Receiving funds from third parties (receiving_funds_from_third_parties = Yes) | 10 |  |
| Non-transactional matter that still moves funds or assets (movement_of_funds_assets = Yes) | 10 |  |

### Transaction red flags

Capped at 35. Alone makes the rating medium at 10 and high at 28.

| Answer | Points | Automatic high risk |
| --- | --- | --- |
| Proliferation financing risk (proliferation_financing = Yes) | 35 | Yes |
| No apparent economic or legal purpose (lack_of_economic_or_legal_purpose = Yes) | 35 | Yes |
| Unusually complex or large transaction (unusual_complex_transaction = Yes) | 15 |  |
| Unusual pattern of transactions (unusual_pattern_of_transactions = Yes) | 15 |  |
| Other AML/CTF risks (other_risks = Yes) | 10 |  |
| Other high-risk factors (other_high_risk_factors = Yes) | 10 |  |

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
