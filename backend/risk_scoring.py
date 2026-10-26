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

MATTER_TYPE_WHY = (
    'Every matter starts from the inherent risk of the work, before anything '
    'about this client is known. 15 points puts high-risk work at medium '
    'before any answer is given, which is what the SRA means by conveyancing '
    'carrying the highest inherent risk; low-risk work starts at nothing so '
    'the rating is driven entirely by the answers.'
)

#: Transaction value bands, in pounds. The £1m step is LSAG's own example.
VALUE_BANDS = [
    (Decimal('1000000'), 12, 'Transaction value £1m or more'),
    (Decimal('500000'), 6, 'Transaction value £500k or more'),
]

VALUE_BAND_WHY = (
    'Value is a proxy for how much can be moved through the firm in one '
    'transaction. The £1m step is LSAG 5.12\u2019s own example of a category-based '
    'rating, and 12 points is set so that high-risk work at £1m reaches the '
    'section ceiling and so high risk, as that example intends. £500k scores '
    'half, reaching medium on high-risk work without claiming the transaction '
    'is itself exceptional.'
)


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
    #: Why this answer is worth this much. LSAG 5.13: "Short complementary
    #: notes explaining the rationale for each weighting may be a useful
    #: addition to the risk assessment." Shown on the form and printed in
    #: docs/risk-weightings.md, so the weighting can be defended as given.
    why: str = ''

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
    #: Why the ceiling and the two floors sit where they do.
    why: str = ''


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
        why='The ceiling is 30 because one answer here - a designated person - '
            'is decisive on its own. High at 24 means two substantial concerns '
            'about the client reach high risk without a third.',
        factors=(
            Factor('Client or a party is a designated person/entity',
                   30, field='designated_person_entity', auto_high=True,
                   why='Acting for a designated person risks breaching financial '
                       'sanctions, which carries criminal liability and does not '
                       'depend on what we knew. No score threshold is appropriate.'),
            Factor('Adverse media about the client or a beneficial owner',
                   12, field='adverse_media',
                   why='Information about the client from outside our own file, '
                       'which usually points at something they have not told us. '
                       'The heaviest of the judgement-based client factors.'),
            Factor('Concerns about the client, agent or third parties',
                   10, field='concerns_about_parties',
                   why='A fee earner\u2019s concern about anyone involved. Just below '
                       'adverse media: a professional impression rather than an '
                       'independent source, but it reaches medium on its own.'),
            Factor('Concerns about the client', 8, field='client_concerns',
                   why='Capacity, undue influence or vulnerability. A real risk to '
                       'the retainer, and sometimes a sign the client is fronting '
                       'for someone, but not by itself a laundering indicator.'),
            Factor('Unusual client for this type of work', 8, field='unusual_client',
                   why='Our own baseline being broken. The SRA\u2019s sectoral risk '
                       'assessment treats work outside a firm\u2019s normal profile as '
                       'a warning sign, which matters more at a local firm with a '
                       'narrow client base.'),
            Factor('No evidence of a third party\u2019s authority to act',
                   8, field='third_party_authority', answer='No',
                   why='Acting on an instruction we cannot show was authorised. '
                       'Weighted with the other 8s because it is a gap in our own '
                       'evidence rather than a fact about the client.'),
        ),
    ),
    Category(
        key='geographic',
        label='Geographic risk',
        cap=25, medium_at=8, high_at=20,
        why='Medium at 8 so a single overseas element registers, because for a '
            'local firm that is already outside the normal pattern. High at 20 '
            'is reachable only by the mandatory triggers or by both judgement '
            'answers together.',
        factors=(
            Factor('A party is established in a high-risk third country or jurisdiction',
                   25, field='high_risk_third_country_or_jurisdiction', auto_high=True,
                   why='MLRs reg 33(1)(b) makes enhanced due diligence mandatory. '
                       'The listing is an external determination, not our judgement, '
                       'so it does not wait on a score.'),
            Factor('Matter involves a country subject to sanctions',
                   25, field='country_subject_to_sanctions', auto_high=True,
                   why='Sanctions exposure is a criminal-liability question rather '
                       'than a risk-appetite one, so it is treated like a '
                       'designated person.'),
            Factor('Concerns about the client\u2019s location',
                   10, field='location_of_instruction_concerns',
                   why='Weighted to reach medium on its own: an unexplained '
                       'location is one of the oldest laundering signals.'),
            Factor('Location of the instruction does not make sense',
                   10, field='make_sense_location_of_instructions', answer='No',
                   why='The other side of the same judgement - why is a client '
                       'there instructing a high-street firm here - so it carries '
                       'the same weight.'),
            Factor('Overseas elements involved', 8, field='overseas_elements',
                   why='Below the two concerns above, because an overseas '
                       'beneficiary or asset is common in probate and conveyancing '
                       'without being suspicious. It still scores: this firm sees '
                       'few of them.'),
        ),
    ),
    Category(
        key='delivery_channel',
        label='Delivery channel',
        cap=15, medium_at=10, high_at=15,
        why='The ceiling is low because remote working is normal. High at 15 '
            'needs both answers, which is deliberate: a client never met, whose '
            'identity was never properly verified, has not really been '
            'identified at all.',
        factors=(
            Factor('Client will not be met in person', 8, field='meeting_in_person', answer='No',
                   why='MLRs reg 33(2) lists non-face-to-face among the factors to '
                       'consider. On its own it is routine now, so it scores below '
                       'medium.'),
            Factor('Identity not verified from a certified or verified electronic source',
                   10, field='id_verified_reliable_source', answer='No',
                   why='Heavier than not meeting the client, because it is a '
                       'failure of verification rather than of channel. The SRA\u2019s '
                       'August 2026 sectoral risk assessment makes AI-generated '
                       'documents and deepfakes the technology risk, so images the '
                       'client supplies are no longer evidence.'),
        ),
    ),
    Category(
        key='structure',
        label='Structure and ownership',
        cap=20, medium_at=10, high_at=20,
        why='Only relevant to entity clients, so the ceiling is moderate; high '
            'needs two of these together, which would describe an entity whose '
            'ownership we cannot actually see.',
        factors=(
            Factor('Owners or directors appear unconnected to the business, or to be nominees',
                   12, field='nominee_or_unconnected_directors',
                   why='The heaviest here because it goes to who is really behind '
                       'the client. New in the SRA\u2019s August 2026 assessment, which '
                       'links nominee and "ghost director" arrangements to '
                       'organised crime and modern slavery.'),
            Factor('Complex or unusual structure', 10, field='complex_structure_or_unusual',
                   why='Complexity is not wrongdoing, but it is the usual means of '
                       'obscuring ownership, so it reaches medium alone.'),
            Factor('Reportable discrepancies identified', 8, field='reportable_discrepancies',
                   why='A discrepancy is a fact rather than a judgement, but it is '
                       'often administrative, so it is weighted below the two '
                       'above.'),
            Factor('Companies House not checked, or filed details do not match',
                   8, field='companies_house_checked', answer='No',
                   why='New in August 2026: original documentation from dissolved '
                       'companies is used to establish false credentials. Weighted '
                       'as a gap in our checking rather than as evidence of risk.'),
        ),
    ),
    Category(
        key='pep_sanctions',
        label='PEP and sanctions',
        cap=30, medium_at=15, high_at=28,
        why='High at 28 is reachable only by the two automatic triggers, so a '
            'domestic PEP lands at medium as the Regulations intend rather than '
            'being pushed to high by this section alone.',
        factors=(
            Factor('Financial sanctions concerns', 30, field='financial_sanctions', auto_high=True,
                   why='Same reasoning as a designated person: criminal liability, '
                       'not risk appetite.'),
            Factor('Non-domestic PEP, family member or close associate',
                   30, field='pep_type', answer='Non-domestic', auto_high=True,
                   why='Reg 35 makes enhanced due diligence and senior management '
                       'approval mandatory, and the foreign-official risk is what '
                       'the PEP regime was written for.'),
            Factor('Domestic (UK) PEP, family member or close associate',
                   20, field='pep_type', answer='Domestic',
                   why='Since 10 January 2024 reg 35(3A) requires a domestic PEP to '
                       'start from a lower level of risk than a non-domestic one, '
                       'with enhanced measures applied to a lesser extent. 20 puts '
                       'it in medium while still requiring enhanced due diligence.'),
        ),
    ),
    Category(
        key='cdd_completeness',
        label='Due diligence completeness',
        cap=20, medium_at=8, high_at=20,
        why='These are things we have not done rather than facts about the '
            'client, so each reaches medium but it takes all three to reach '
            'high - at which point the file has no real due diligence on it.',
        factors=(
            Factor('Source of funds questionnaire not completed',
                   8, field='is_source_of_funds_questionnaire_completed', answer='No',
                   why='The SRA found a quarter of the files it reviewed in 2025-26 '
                       'lacked adequate source of funds evidence, and nine per cent '
                       'of files needing checks had none. Weighted to reach medium '
                       'on its own for that reason.'),
            Factor('Relying on due diligence from an earlier matter or another office',
                   8, field='relying_on_previous_due_diligence',
                   why='"Passporting", new in August 2026: checks carried over '
                       'without asking whether they are still appropriate for this '
                       'matter. Same weight as missing source of funds, because the '
                       'effect is the same - no current due diligence.'),
            Factor('PEP questionnaire not completed',
                   6, field='is_pep_questionnaire_completed', answer='No',
                   why='Below source of funds: PEP status is also screened '
                       'elsewhere, so the questionnaire is corroboration rather '
                       'than the only evidence.'),
        ),
    ),
)


MATTER_CATEGORIES = (
    Category(
        key='type_and_value',
        label='Type of work and value',
        cap=25, medium_at=12, high_at=25,
        why='High at 25 is exactly high-risk work at £1m or more, which is '
            'LSAG 5.12\u2019s own worked example of a category-based rating. Medium '
            'at 12 means high-risk work is at least medium before anything '
            'else is known about it, which is what "inherent" means.',
        # Scored from the matter type and transaction value, not from Yes/No
        # answers - see _score_type_and_value.
    ),
    Category(
        key='nature_of_work',
        label='Nature of the instruction',
        cap=25, medium_at=12, high_at=15,
        why='High at 15 is the lowest floor anywhere here, so the single '
            'answer below reaches it alone. An instruction that does not fit '
            'the client is the classic laundering pattern, and it should be '
            'considered for a report rather than averaged into a total.',
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
            Factor('Transaction inconsistent with the client\u2019s profile or does not make sense',
                   15, field='consistent_with_client_profile', answer='No',
                   why='The heaviest single matter answer, and enough for high risk '
                       'by itself. LSAG 5.11 lists a matter that does not fit the '
                       'client\u2019s profile among the higher-risk factors; a fee '
                       'earner answering No here is describing the thing the '
                       'regime exists to catch.'),
            Factor('Not our usual type of work', 12, field='usual_work', answer='No',
                   why='Work we do not normally take is work we are least able to '
                       'judge, and the firm\u2019s own controls are built around its '
                       'usual files. Reaches medium alone.'),
            Factor('Matter involves a complex structure', 8, field='complex_structure',
                   why='Weighted below the client\u2019s own structure being complex: '
                       'building a structure is ordinary transactional work, where '
                       'an already-opaque client is a question about who we are '
                       'acting for.'),
        ),
    ),
    Category(
        key='sector',
        label='Sector risk',
        cap=20, medium_at=10, high_at=20,
        why='Two factors of 12 against a ceiling of 20: either reaches medium, '
            'both reach high. A cash-intensive business in a high-risk sector '
            'is the combination the 2026 sectoral assessment describes.',
        factors=(
            # The form asks about high-risk sectors and cash intensity in both
            # the matter and the EDD sections. Each underlying fact scores
            # once, so answering the same thing twice cannot inflate the score.
            Factor('High-risk industry or sector', 12,
                   any_of=('high_risk_industry', 'higher_risk_sector'),
                   why='Sector is an inherent property of the work rather than a '
                       'judgement about this client, so it is weighted to reach '
                       'medium without tipping to high on its own.'),
            Factor('Cash-intensive industry or business activity', 12,
                   any_of=('cash_intensive_industry', 'cash_intensive_business_activity'),
                   why='Cash intensity is the classic placement route and is one of '
                       'the three headings the SRA added in August 2026. Weighted '
                       'level with sector risk because the two usually travel '
                       'together.'),
        ),
    ),
    Category(
        key='funds_flow',
        label='Movement of funds',
        cap=25, medium_at=10, high_at=25,
        why='Any one of these reaches medium; high needs all three, which '
            'describes money arriving from several directions at once with no '
            'clear reason - the pattern, rather than any single leg of it.',
        factors=(
            Factor('Receiving funds from overseas', 12, field='receiving_funds_from_overseas',
                   why='The heaviest of the three: it puts the origin of the money '
                       'beyond what we can check, and beyond UK supervision.'),
            Factor('Receiving funds from third parties',
                   10, field='receiving_funds_from_third_parties',
                   why='Money from someone who is not our client breaks the link '
                       'between the client\u2019s means and the transaction. Common and '
                       'often innocent - family gifts in conveyancing - so it sits '
                       'below overseas funds.'),
            Factor('Non-transactional matter that still moves funds or assets',
                   10, field='movement_of_funds_assets',
                   why='Advisory work that nonetheless moves money is outside the '
                       'pattern the file appears to be, which is why it is asked '
                       'at all.'),
        ),
    ),
    Category(
        key='transaction_flags',
        label='Transaction red flags',
        cap=35, medium_at=10, high_at=28,
        why='The largest ceiling, because this is where the serious answers '
            'live. High at 28 takes two of the reg 33(1)(f) answers together, '
            'while the two automatic triggers do not wait for a total at all.',
        factors=(
            Factor('Proliferation financing risk', 35,
                   field='proliferation_financing', auto_high=True,
                   why='Proliferation financing is a national-security matter with '
                       'its own reporting expectations; a scored threshold would '
                       'be inappropriate.'),
            Factor('No apparent economic or legal purpose', 35,
                   field='lack_of_economic_or_legal_purpose', auto_high=True,
                   why='A transaction with no purpose we can identify is, on its '
                       'face, a transaction whose purpose is something else. This '
                       'is the point at which a report should be considered, so it '
                       'is high risk outright.'),
            # reg 33(1)(f): an unusually large transaction or an unusual
            # pattern of transactions requires enhanced due diligence.
            Factor('Unusually complex or large transaction', 15,
                   field='unusual_complex_transaction',
                   why='Reg 33(1)(f) already makes enhanced due diligence mandatory '
                       'here, so the weight only has to carry the rating: 15 '
                       'reaches medium, and with the pattern answer, high.'),
            Factor('Unusual pattern of transactions', 15,
                   field='unusual_pattern_of_transactions',
                   why='The other half of reg 33(1)(f) and weighted identically: a '
                       'single odd transaction and a pattern of them are the same '
                       'provision.'),
            Factor('Other AML/CTF risks', 10, field='other_risks',
                   why='A catch-all, weighted to reach medium so that a fee '
                       'earner\u2019s concern is never scored as nothing, but not '
                       'higher, because what it describes is unknown.'),
            Factor('Other high-risk factors', 10, field='other_high_risk_factors',
                   why='The same catch-all on the enhanced due diligence side, '
                       'weighted the same way and for the same reason.'),
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
                        'why': factor.why,
                        'side': side,
                        'category': category.label,
                        'cap': category.cap,
                        'high_at': category.high_at,
                    })
    return weights


#: Built once: the categories are constants.
QUESTION_WEIGHTS = question_weights()


def weighting_reference():
    """Every weight with the reasoning behind it, grouped as it is scored.

    This is the whole weighting as a readable structure: the form prints it
    under the questions, and ``manage.py risk_weightings`` prints it into the
    note the firm keeps with its firm-wide risk assessment. LSAG 5.13 expects a
    practice to be able to explain its weightings; keeping the reasons beside
    the numbers is how they stay explainable after the person who chose them
    has moved on.
    """
    sides = []
    for key, label, categories in (('client', 'Client risk', CLIENT_CATEGORIES),
                                   ('matter', 'Matter risk', MATTER_CATEGORIES)):
        rows = []
        for category in categories:
            factors = [{
                'label': factor.label,
                'points': factor.points,
                'answer': factor.answer,
                'auto_high': factor.auto_high,
                'why': factor.why,
            } for factor in category.factors]
            if category.key == 'type_and_value':
                factors = _type_and_value_reference()
            rows.append({
                'key': category.key,
                'label': category.label,
                'cap': category.cap,
                'medium_at': category.medium_at,
                'high_at': category.high_at,
                'why': category.why,
                'factors': factors,
            })
        sides.append({'key': key, 'label': label, 'categories': rows})
    return sides


def _type_and_value_reference():
    """The type-of-work and value steps, in the same shape as a factor."""
    rows = [{
        'label': f'{level} inherent risk work',
        'points': points,
        'answer': 'Matter type',
        'auto_high': False,
        'why': MATTER_TYPE_WHY,
    } for level, points in MATTER_TYPE_POINTS.items() if points]
    rows += [{
        'label': label,
        'points': points,
        'answer': 'Transaction value',
        'auto_high': False,
        'why': VALUE_BAND_WHY,
    } for threshold, points, label in VALUE_BANDS]
    return rows


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
