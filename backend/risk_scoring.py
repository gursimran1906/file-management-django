"""Scores a client/matter risk assessment from the answers given.

Staff used to pick the client and matter risk levels themselves, which made the
rating a matter of opinion and left nothing on the file explaining how it was
reached. The SRA's 2025-26 AML annual report found client and matter risk
assessments to be the single largest cause of referrals: 16% of files reviewed
had no assessment or an incomplete one, and a further 39% did not effectively
evaluate the money laundering risk. This module derives the rating from the
answers so the reasoning is on the file by construction.

The design follows LSAG AML Guidance 5.13 ("Risk Weightings"), which is where
the shape of this comes from and which also sets the traps to avoid:

* Factors are weighted, not counted. LSAG's own example is that a client's
  personal links to a higher-risk jurisdiction might add 7 points where the
  high-risk nature of the service sought adds only 5, "so the final score takes
  account of both factors in proportion".
* There are automatic high-risk triggers that make a matter high risk
  "regardless of whether they meet a score threshold or not" — see
  ``auto_high`` on a factor. These are the answers where a score is beside the
  point: sanctions, a non-domestic PEP, proliferation financing, a transaction
  with no apparent economic or legal purpose.
* Serious risks are not allowed to be diluted by a pile of clean answers.
  LSAG's worked example of *inappropriate* scoring is an assessment where
  geographic and client risk both score 20/20 but the total of 40 falls under a
  threshold of 50 and so comes out "low". Each category here therefore carries
  its own ``medium_at``/``high_at`` floors: a category that is serious on its
  own sets the level on its own, whatever the total says.
* Weighting must not be "unduly influenced by one factor", so a category's
  contribution is capped, and facts the form asks about twice (cash intensity,
  high-risk sector) are scored once via ``any_of``.
* It must remain possible for a matter to come out high risk — hence the
  category floors and the automatic triggers rather than a single high total.

The rating is a starting point, not the answer. LSAG requires that a practice
can "override any automatically generated risk scores where necessary with the
rationale for the decision to override such scores being documented": the form
pre-fills what this module computes and demands a written reason if a human
records something different. ``docs/risk-scoring-methodology.md`` is the
firm-facing write-up of all of the above, for the firm-wide risk assessment.

Changing any weight here means changing ``SCORING_VERSION``: the version and
the full breakdown are stored on each assessment so an old rating can still be
explained with the weights that produced it.
"""

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

# Bump on any change to weights, caps, floors, bands or triggers below.
SCORING_VERSION = '2026.1'

LOW = 'Low'
MEDIUM = 'Medium'
HIGH = 'High'

#: Rank used to compare levels (``max`` of two levels, floors, etc.).
LEVEL_ORDER = {LOW: 0, MEDIUM: 1, HIGH: 2}

#: Bands applied to a side's total score. A side is also lifted by the category
#: floors below, so these bands are a floor on the whole picture, never a cap on
#: a single serious category.
MEDIUM_BAND = 12
HIGH_BAND = 30

#: Inherent risk of the type of work, scored as the matter's starting point.
#: LSAG 5.12 endorses exactly this category-based approach ("conveyancing
#: matters of value £1,000,000 or more are high risk"), and the SRA's sectoral
#: risk assessment keeps conveyancing as the highest inherent risk area of law.
#: Per-type values live on ``MatterType.inherent_risk`` so the firm can retune
#: them in admin without a code change.
MATTER_TYPE_POINTS = {HIGH: 15, MEDIUM: 8, LOW: 0}

#: Transaction value bands, in pounds. The £1m step is LSAG's own example.
VALUE_BANDS = [
    (Decimal('1000000'), 12, 'Transaction value £1m or more'),
    (Decimal('500000'), 6, 'Transaction value £500k or more'),
]


@dataclass(frozen=True)
class Factor:
    """One scored answer.

    ``field``/``answer`` is the answer that scores; ``any_of`` scores once if
    any of several fields carries that answer, so that a fact the form asks
    about in two places is not counted twice.
    """

    label: str
    points: int
    field: str = ''
    answer: str = 'Yes'
    any_of: tuple = ()
    auto_high: bool = False

    def fields(self):
        return self.any_of or (self.field,)

    def applies(self, ra):
        return any(getattr(ra, name, None) == self.answer for name in self.fields())


@dataclass(frozen=True)
class Category:
    """A group of factors with its own ceiling and its own level floors.

    ``cap`` stops one category dominating the total; ``medium_at`` and
    ``high_at`` are the point at which this category alone sets the side's
    level, which is what stops a serious risk being averaged away.
    """

    key: str
    label: str
    cap: int
    medium_at: int
    high_at: int
    factors: tuple = field(default_factory=tuple)


# --------------------------------------------------------------------------
# Client risk
# --------------------------------------------------------------------------
# LSAG 5.9-5.11 risk factor headings: client, geographic, delivery channel,
# plus the structure/ownership and CDD questions the SRA template asks.

CLIENT_CATEGORIES = (
    Category(
        key='client_party',
        label='Client and parties',
        cap=30, medium_at=10, high_at=24,
        factors=(
            Factor('Client or a party is a designated person/entity',
                   30, field='designated_person_entity', auto_high=True),
            Factor('Adverse media about the client or a beneficial owner',
                   12, field='adverse_media'),
            Factor('Concerns about the client, agent or third parties',
                   10, field='concerns_about_parties'),
            Factor('Concerns about the client', 8, field='client_concerns'),
            Factor('Unusual client for this type of work', 8, field='unusual_client'),
            Factor('No evidence of a third party’s authority to act',
                   8, field='third_party_authority', answer='No'),
        ),
    ),
    Category(
        key='geographic',
        label='Geographic risk',
        cap=25, medium_at=8, high_at=20,
        factors=(
            # Both of these make enhanced due diligence mandatory (MLRs
            # reg 33(1)(b) for a high-risk third country), so neither waits on
            # a score threshold.
            Factor('A party is established in a high-risk third country or jurisdiction',
                   25, field='high_risk_third_country_or_jurisdiction', auto_high=True),
            Factor('Matter involves a country subject to sanctions',
                   25, field='country_subject_to_sanctions', auto_high=True),
            Factor('Concerns about the client’s location',
                   10, field='location_of_instruction_concerns'),
            Factor('Location of the instruction does not make sense',
                   10, field='make_sense_location_of_instructions', answer='No'),
            # A local high-street firm sees few overseas elements, so when one
            # appears it is further outside the firm's normal pattern of work
            # than it would be at a national firm.
            Factor('Overseas elements involved', 8, field='overseas_elements'),
        ),
    ),
    Category(
        key='delivery_channel',
        label='Delivery channel',
        cap=15, medium_at=10, high_at=15,
        factors=(
            Factor('Client will not be met in person', 8, field='meeting_in_person', answer='No'),
            # The SRA's August 2026 sectoral risk assessment recast technology
            # risk around AI-enabled fraud and deepfakes: images a client sends
            # in are no longer a safe basis for remote verification.
            Factor('Identity not verified from a certified or verified electronic source',
                   10, field='id_verified_reliable_source', answer='No'),
        ),
    ),
    Category(
        key='structure',
        label='Structure and ownership',
        cap=20, medium_at=10, high_at=20,
        factors=(
            # Cash-intensive businesses fronted by nominee or "ghost"
            # directors is a new August 2026 sectoral heading, tied to
            # organised crime and modern slavery.
            Factor('Owners or directors appear unconnected to the business, or to be nominees',
                   12, field='nominee_or_unconnected_directors'),
            Factor('Complex or unusual structure', 10, field='complex_structure_or_unusual'),
            Factor('Reportable discrepancies identified', 8, field='reportable_discrepancies'),
            # Also new in August 2026: paperwork from a dissolved company used
            # to establish false credentials.
            Factor('Companies House not checked, or filed details do not match',
                   8, field='companies_house_checked', answer='No'),
        ),
    ),
    Category(
        key='pep_sanctions',
        label='PEP and sanctions',
        cap=30, medium_at=15, high_at=28,
        factors=(
            Factor('Financial sanctions concerns', 30, field='financial_sanctions', auto_high=True),
            # Since 10 January 2024 the MLRs (reg 35(3A)) require a domestic
            # PEP to be treated as presenting a lower level of risk than a
            # non-domestic PEP, with enhanced measures applied to a lesser
            # extent. So a non-domestic PEP triggers high risk outright, while
            # a domestic PEP scores into Medium and still requires EDD.
            Factor('Non-domestic PEP, family member or close associate',
                   30, field='pep_type', answer='Non-domestic', auto_high=True),
            Factor('Domestic (UK) PEP, family member or close associate',
                   20, field='pep_type', answer='Domestic'),
        ),
    ),
    Category(
        key='cdd_completeness',
        label='Due diligence completeness',
        cap=20, medium_at=8, high_at=20,
        factors=(
            # A quarter of the files the SRA reviewed in 2025-26 lacked
            # adequate source of funds evidence.
            Factor('Source of funds questionnaire not completed',
                   8, field='is_source_of_funds_questionnaire_completed', answer='No'),
            # "Passporting", new in August 2026: leaning on due diligence done
            # for another office or an earlier instruction without asking
            # whether it is still appropriate for this matter.
            Factor('Relying on due diligence from an earlier matter or another office',
                   8, field='relying_on_previous_due_diligence'),
            Factor('PEP questionnaire not completed',
                   6, field='is_pep_questionnaire_completed', answer='No'),
        ),
    ),
)


# --------------------------------------------------------------------------
# Matter risk
# --------------------------------------------------------------------------
# LSAG product/service and transaction risk headings, plus the inherent risk of
# the work type and the value of the transaction.

MATTER_CATEGORIES = (
    Category(
        key='type_and_value',
        label='Type of work and value',
        cap=25, medium_at=12, high_at=25,
        # Scored from the matter type and transaction value, not from Yes/No
        # answers — see _score_type_and_value.
    ),
    Category(
        key='nature_of_work',
        label='Nature of the instruction',
        cap=25, medium_at=12, high_at=15,
        factors=(
            # LSAG 5.11 lists a matter that does not fit the client's profile
            # among the higher-risk matter factors. If a fee earner has
            # answered that this instruction does not make sense for this
            # client, that is a high-risk matter on its own and should be
            # considered for a report, so high_at is set at a single answer.
            #
            # The form used to ask this twice, as this question and as
            # ``makes_sense_for_client``. Only this one is scored: the other
            # field's default is 'No', which is also its risky answer, so on an
            # assessment completed before the two were merged there is no way to
            # tell a deliberate 'No' from a question nobody answered. It is
            # still shown on those assessments where it was answered 'No'.
            Factor('Transaction inconsistent with the client’s profile or does not make sense',
                   15, field='consistent_with_client_profile', answer='No'),
            Factor('Not our usual type of work', 12, field='usual_work', answer='No'),
            Factor('Matter involves a complex structure', 8, field='complex_structure'),
        ),
    ),
    Category(
        key='sector',
        label='Sector risk',
        cap=20, medium_at=10, high_at=20,
        factors=(
            # The form asks about high-risk sectors and cash intensity in both
            # the matter and the EDD sections. Each underlying fact scores
            # once, so answering the same thing twice cannot inflate the score.
            Factor('High-risk industry or sector', 12,
                   any_of=('high_risk_industry', 'higher_risk_sector')),
            Factor('Cash-intensive industry or business activity', 12,
                   any_of=('cash_intensive_industry', 'cash_intensive_business_activity')),
        ),
    ),
    Category(
        key='funds_flow',
        label='Movement of funds',
        cap=25, medium_at=10, high_at=25,
        factors=(
            Factor('Receiving funds from overseas', 12, field='receiving_funds_from_overseas'),
            Factor('Receiving funds from third parties',
                   10, field='receiving_funds_from_third_parties'),
            Factor('Non-transactional matter that still moves funds or assets',
                   10, field='movement_of_funds_assets'),
        ),
    ),
    Category(
        key='transaction_flags',
        label='Transaction red flags',
        cap=35, medium_at=10, high_at=28,
        factors=(
            Factor('Proliferation financing risk', 35,
                   field='proliferation_financing', auto_high=True),
            Factor('No apparent economic or legal purpose', 35,
                   field='lack_of_economic_or_legal_purpose', auto_high=True),
            # reg 33(1)(f): an unusually large transaction or an unusual
            # pattern of transactions requires enhanced due diligence.
            Factor('Unusually complex or large transaction', 15,
                   field='unusual_complex_transaction'),
            Factor('Unusual pattern of transactions', 15,
                   field='unusual_pattern_of_transactions'),
            Factor('Other AML/CTF risks', 10, field='other_risks'),
            Factor('Other high-risk factors', 10, field='other_high_risk_factors'),
        ),
    ),
)


#: Answers that make enhanced due diligence mandatory under the MLRs whatever
#: the score comes to. (field, answer, why).
MANDATORY_EDD_RULES = (
    ('high_risk_third_country_or_jurisdiction', 'Yes',
     'A party is established in a high-risk third country (reg 33(1)(b))'),
    ('pep_type', 'Non-domestic', 'Non-domestic PEP involved (reg 35)'),
    ('pep_type', 'Domestic', 'Domestic PEP involved (reg 35, to a lesser extent)'),
    ('financial_sanctions', 'Yes', 'Financial sanctions concerns'),
    ('designated_person_entity', 'Yes', 'Client or a party is a designated person/entity'),
    ('country_subject_to_sanctions', 'Yes', 'Matter involves a country subject to sanctions'),
    ('unusual_complex_transaction', 'Yes',
     'Unusually complex or large transaction (reg 33(1)(f))'),
    ('unusual_pattern_of_transactions', 'Yes',
     'Unusual pattern of transactions (reg 33(1)(f))'),
    ('lack_of_economic_or_legal_purpose', 'Yes',
     'Transaction lacks an apparent economic or legal purpose'),
    ('proliferation_financing', 'Yes', 'Proliferation financing risk'),
)


def question_weights():
    """What each question is worth, keyed by field name.

    The form shows this beside the question it asks, so that "how is this
    scored" is answerable at the point of answering rather than only from the
    methodology note. Built from the categories above, so it cannot drift from
    what actually scores.

    A field can appear more than once (a domestic and a non-domestic PEP are
    weighted differently), so each entry is a list.
    """
    weights = {}
    for side, categories in (('client', CLIENT_CATEGORIES),
                             ('matter', MATTER_CATEGORIES)):
        for category in categories:
            for factor in category.factors:
                for name in factor.fields():
                    weights.setdefault(name, []).append({
                        'points': factor.points,
                        'answer': factor.answer,
                        'auto_high': factor.auto_high,
                        'label': factor.label,
                        'side': side,
                        'category': category.label,
                        'cap': category.cap,
                        'high_at': category.high_at,
                    })
    return weights


#: Built once: the categories are constants.
QUESTION_WEIGHTS = question_weights()


def value_band_weights():
    """The transaction value steps, for the form to show beside the field."""
    return [{'points': points, 'label': label, 'threshold': str(threshold)}
            for threshold, points, label in VALUE_BANDS]


def _band(score):
    if score >= HIGH_BAND:
        return HIGH
    if score >= MEDIUM_BAND:
        return MEDIUM
    return LOW


def _higher(*levels):
    return max(levels, key=lambda level: LEVEL_ORDER[level])


def _matter_type_points(matter):
    """Starting points for the type of work, from ``MatterType.inherent_risk``."""
    matter_type = getattr(matter, 'matter_type', None)
    if matter_type is None:
        return 0, []
    inherent = getattr(matter_type, 'inherent_risk', LOW) or LOW
    points = MATTER_TYPE_POINTS.get(inherent, 0)
    if not points:
        return 0, []
    return points, [{'label': f'{matter_type} is {inherent.lower()} inherent risk work',
                     'points': points}]


def _value_points(value):
    try:
        amount = Decimal(value or 0)
    except (TypeError, InvalidOperation):
        return 0, []
    for threshold, points, label in VALUE_BANDS:
        if amount >= threshold:
            return points, [{'label': label, 'points': points}]
    return 0, []


def _score_type_and_value(ra, category):
    """Score the type-of-work-and-value category from the matter, not answers."""
    type_points, type_hits = _matter_type_points(getattr(ra, 'matter', None))
    value_points, value_hits = _value_points(getattr(ra, 'matter_transaction_value', None))
    return type_points + value_points, type_hits + value_hits, []


def _score_category(ra, category):
    """Return (raw score, hit factors, auto-high labels) for one category."""
    if category.key == 'type_and_value':
        return _score_type_and_value(ra, category)
    raw, hits, auto_high = 0, [], []
    for factor in category.factors:
        if not factor.applies(ra):
            continue
        raw += factor.points
        hits.append({'label': factor.label, 'points': factor.points})
        if factor.auto_high:
            auto_high.append(factor.label)
    return raw, hits, auto_high


def _score_side(ra, categories):
    """Score one side (client or matter) across its categories."""
    rows, total, auto_high = [], 0, []
    floor = LOW
    for category in categories:
        raw, hits, category_auto_high = _score_category(ra, category)
        score = min(raw, category.cap)
        total += score
        auto_high.extend(category_auto_high)
        category_floor = LOW
        if score >= category.high_at:
            category_floor = HIGH
        elif score >= category.medium_at:
            category_floor = MEDIUM
        floor = _higher(floor, category_floor)
        rows.append({
            'key': category.key,
            'label': category.label,
            'score': score,
            'raw': raw,
            'cap': category.cap,
            'medium_at': category.medium_at,
            'high_at': category.high_at,
            'floor': category_floor,
            'factors': hits,
            # Bar widths for the panel beside the form, worked out here so the
            # template has no arithmetic to do.
            'pct': round(score * 100 / category.cap) if category.cap else 0,
        })
    level = _higher(_band(total), floor)
    if auto_high:
        level = HIGH
    return {
        'score': total,
        'level': level,
        'pct': min(100, round(total * 100 / HIGH_BAND)),
        'band_level': _band(total),
        'floor_level': floor,
        'categories': rows,
        'auto_high': auto_high,
    }


def mandatory_edd_reasons(ra):
    """Why the MLRs require enhanced due diligence on this matter, if they do."""
    return [why for field_name, answer, why in MANDATORY_EDD_RULES
            if getattr(ra, field_name, None) == answer]


def score_risk_assessment(ra):
    """Score an assessment and return the rating plus the full reasoning.

    ``ra`` is a ``RiskAssessment`` (saved or not). The returned dict is stored
    on the assessment as ``risk_score_breakdown`` so the rating can still be
    explained after the weights change, and is rendered on the form, the matter
    page and the PDF.
    """
    client = _score_side(ra, CLIENT_CATEGORIES)
    matter = _score_side(ra, MATTER_CATEGORIES)

    # LSAG 5.13: "Where either, or both, the customer and the service are
    # considered to carry a higher risk [...] it may be appropriate to consider
    # the overall risk of the matter as high risk."
    overall = _higher(client['level'], matter['level'])

    edd_reasons = mandatory_edd_reasons(ra)
    due_diligence = 'Enhanced' if overall == HIGH or edd_reasons else 'Standard'

    notes = []
    if getattr(ra, 'pep_type', None) == 'Domestic':
        notes.append(
            'Domestic PEP: the starting point is a lower level of risk than a '
            'non-domestic PEP and enhanced measures may be applied to a lesser '
            'extent (MLRs reg 35(3A)).')
    if overall == HIGH:
        notes.append(
            'High risk: enhanced due diligence applies and the matter should be '
            'escalated to the nominated officer, with source of funds and source '
            'of wealth evidenced on the file.')

    return {
        'version': SCORING_VERSION,
        'client': client,
        'matter': matter,
        'overall_level': overall,
        'due_diligence_level': due_diligence,
        'auto_high': client['auto_high'] + matter['auto_high'],
        'edd_reasons': edd_reasons,
        'notes': notes,
        'bands': {'medium_at': MEDIUM_BAND, 'high_at': HIGH_BAND},
    }


def apply_scores(ra):
    """Score ``ra`` and write the computed fields onto it.

    The recorded levels are only filled in from the computed ones where a human
    has not deliberately recorded something else: once an override reason is
    on the assessment, the recorded levels are left alone (LSAG 5.13 requires
    that an automatic score can be overridden with a documented rationale).
    Returns the breakdown.
    """
    breakdown = score_risk_assessment(ra)
    ra.client_risk_score = breakdown['client']['score']
    ra.matter_risk_score = breakdown['matter']['score']
    ra.computed_client_risk_level = breakdown['client']['level']
    ra.computed_matter_risk_level = breakdown['matter']['level']
    ra.computed_due_diligence_level = breakdown['due_diligence_level']
    ra.overall_risk_level = breakdown['overall_level']
    ra.risk_score_breakdown = breakdown
    ra.scoring_version = breakdown['version']

    if not (ra.risk_override_reason or '').strip():
        ra.client_risk_level = breakdown['client']['level']
        ra.matter_risk_level = breakdown['matter']['level']
        ra.customer_due_diligence_level = breakdown['due_diligence_level']
        return breakdown

    # An overridden assessment keeps what the firm recorded, and the overall
    # level follows the recorded ratings so the compliance reports count what
    # is actually on the file.
    recorded = (ra.client_risk_level, ra.matter_risk_level,
                ra.customer_due_diligence_level)
    computed = (breakdown['client']['level'], breakdown['matter']['level'],
                breakdown['due_diligence_level'])
    if recorded == computed:
        # The answers have since caught up with the rating, so there is no
        # longer an override for the reason to explain.
        ra.risk_override_reason = ''
    else:
        ra.overall_risk_level = _higher(ra.client_risk_level or LOW,
                                        ra.matter_risk_level or LOW)
    return breakdown
