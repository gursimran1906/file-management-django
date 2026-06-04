from decimal import Decimal

from django.test import TestCase

from backend.completion_statement import (
    calculate_apportionment,
    calculate_mortgage_redemption,
)
from backend.money_split import split_amount_with_penny_adjustment


class MoneySplitTests(TestCase):
    def test_thirds_split_odd_penny(self):
        results = split_amount_with_penny_adjustment(
            Decimal('1000.00'),
            [
                {'mode': 'fraction', 'value': '1/3', 'sort_order': 1},
                {'mode': 'fraction', 'value': '1/3', 'sort_order': 2},
                {'mode': 'fraction', 'value': '1/3', 'sort_order': 3},
            ],
        )
        amounts = [r['projected_amount'] for r in results]
        self.assertEqual(sum(amounts), Decimal('1000.00'))
        self.assertEqual(sorted(amounts), [Decimal('333.33'), Decimal('333.33'), Decimal('333.34')])

    def test_fixed_plus_remainder(self):
        results = split_amount_with_penny_adjustment(
            Decimal('1000.00'),
            [
                {'mode': 'fixed', 'value': '600', 'sort_order': 1},
                {'mode': 'remainder', 'value': '', 'sort_order': 2},
            ],
        )
        self.assertEqual(results[0]['projected_amount'], Decimal('600.00'))
        self.assertEqual(results[1]['projected_amount'], Decimal('400.00'))


class MortgageCalculatorTests(TestCase):
    def test_zero_days_same_day_completion(self):
        from datetime import date
        result = calculate_mortgage_redemption(
            redemption_figure='185000',
            redemption_statement_date=date(2024, 6, 28),
            daily_interest_amount='12.50',
            completion_date=date(2024, 6, 28),
        )
        self.assertEqual(result['calculated_days'], 0)
        self.assertEqual(result['calculated_interest'], Decimal('0.00'))
        self.assertEqual(result['total_amount'], Decimal('185000.00'))

    def test_daily_accrual(self):
        from datetime import date
        result = calculate_mortgage_redemption(
            redemption_figure='100000',
            redemption_statement_date=date(2024, 6, 1),
            daily_interest_amount='10.00',
            completion_date=date(2024, 6, 11),
        )
        self.assertEqual(result['calculated_days'], 10)
        self.assertEqual(result['calculated_interest'], Decimal('100.00'))
        self.assertEqual(result['total_amount'], Decimal('100100.00'))


class ApportionmentCalculatorTests(TestCase):
    def test_purchase_paid_in_advance(self):
        from datetime import date
        result = calculate_apportionment(
            annual_amount='3650',
            period_start=date(2024, 1, 1),
            period_end=date(2024, 12, 31),
            completion_date=date(2024, 7, 1),
            paid_in_advance=True,
            transaction_type='purchase',
        )
        self.assertEqual(result['direction'], 'add')
        self.assertGreater(result['calculated_amount'], Decimal('0'))
