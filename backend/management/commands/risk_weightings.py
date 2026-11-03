"""Print the risk assessment weightings as markdown.

LSAG AML Guidance 5.13 expects a practice's weightings, and any departure from
the national or sectoral risk assessments, to be documented in the firm-wide
risk assessment. Rather than keep a second copy of the numbers by hand, this
prints them from the code that applies them:

    python manage.py risk_weightings > docs/risk-weightings.md

Run it again after changing anything in backend/risk_scoring.py.
"""

from django.core.management.base import BaseCommand
from django.db import DatabaseError

from ...models import MatterType
from ... import risk_scoring as rs


class Command(BaseCommand):
    help = 'Print the client and matter risk assessment weightings as markdown.'

    def handle(self, *args, **options):
        out = []
        out.append(f'# Risk assessment weightings (version {rs.SCORING_VERSION})')
        out.append('')
        out.append('Generated from `backend/risk_scoring.py` by '
                   '`python manage.py risk_weightings`. Do not edit by hand.')
        out.append('')
        out.append('Each weight is given with the reason it is set where it is. '
                   'LSAG 5.13 expects a practice to be able to explain its '
                   'weightings, and suggests short notes on the rationale for '
                   'each as a useful addition to the risk assessment.')
        out.append('')
        out.append('A side scores the sum of its sections, each section capped. '
                   f'A total under {rs.MEDIUM_BAND} is low, '
                   f'{rs.MEDIUM_BAND} to {rs.HIGH_BAND - 1} medium, '
                   f'{rs.HIGH_BAND} or more high. A section that reaches its own '
                   'medium or high point sets the rating on its own, whatever '
                   'the total comes to.')
        out.append('')

        for title, categories in (('Client risk', rs.CLIENT_CATEGORIES),
                                  ('Matter risk', rs.MATTER_CATEGORIES)):
            out.append(f'## {title}')
            out.append('')
            for category in categories:
                out.append(f'### {category.label}')
                out.append('')
                out.append(f'Capped at {category.cap}. '
                           f'Alone makes the rating medium at {category.medium_at} '
                           f'and high at {category.high_at}.')
                out.append('')
                if category.why:
                    out.append(f'*{category.why}*')
                    out.append('')
                if not category.factors:
                    out.extend(self._type_and_value_rows())
                    continue
                for factor in category.factors:
                    fields = ', '.join(factor.fields())
                    weight = ('**high risk outright**' if factor.auto_high
                              else f'**adds {factor.points}**')
                    out.append(f'- {factor.label} &mdash; `{fields}` = '
                               f'{factor.answer}, {weight}')
                    if factor.why:
                        out.append(f'  - {factor.why}')
                out.append('')

        out.append('## Automatic enhanced due diligence')
        out.append('')
        out.append('These answers require enhanced due diligence whatever the '
                   'score, and cannot be reduced on the form.')
        out.append('')
        for field_name, answer, why in rs.MANDATORY_EDD_RULES:
            out.append(f'- {why} (`{field_name}` = {answer})')
        out.append('')

        self.stdout.write('\n'.join(out))

    def _type_and_value_rows(self):
        rows = []
        for level, points in rs.MATTER_TYPE_POINTS.items():
            rows.append(f'- {level} inherent risk work &mdash; **adds {points}**')
        rows.append(f'  - {rs.MATTER_TYPE_WHY}')
        for threshold, points, label in rs.VALUE_BANDS:
            rows.append(f'- {label} &mdash; **adds {points}**')
        rows.append(f'  - {rs.VALUE_BAND_WHY}')
        rows.append('')
        rows.append('Inherent risk is set per matter type in admin. Currently:')
        rows.append('')
        try:
            for matter_type in MatterType.objects.all().order_by('type'):
                rows.append(f'- {matter_type.type}: {matter_type.inherent_risk}')
        except DatabaseError:
            # The weightings themselves are in code, so the command is still
            # useful without a database to read the matter types from.
            rows.append('- (not available: no database)')
        rows.append('')
        return rows
