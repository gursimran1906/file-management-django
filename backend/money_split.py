from decimal import Decimal, ROUND_DOWN
from fractions import Fraction


def _parse_fraction(value):
    value = (value or '').strip()
    if not value:
        return None
    if '/' in value:
        parts = value.split('/', 1)
        try:
            return Fraction(int(parts[0].strip()), int(parts[1].strip()))
        except (ValueError, ZeroDivisionError):
            return None
    try:
        return Fraction(Decimal(value))
    except Exception:
        return None


def split_amount_with_penny_adjustment(total, shares):
    """
    Split total across shares using largest-remainder penny rounding.

    shares: list of dicts with keys:
      - mode: fraction | percent | fixed | remainder
      - value: str (e.g. '1/3', '50', '600.00')
      - sort_order: int (tie-break)

    Returns list of dicts: projected_amount, penny_adjustment, ideal_amount
    """
    total = Decimal(str(total or 0)).quantize(Decimal('0.01'))
    if total <= 0 or not shares:
        return []

    ordered = sorted(shares, key=lambda s: s.get('sort_order', 0))
    fixed_total = Decimal('0.00')
    ideal_amounts = []
    remainder_indices = []

    for index, share in enumerate(ordered):
        mode = share.get('mode', 'fraction')
        value = share.get('value', '')
        ideal = Decimal('0.00')

        if mode == 'fixed':
            ideal = Decimal(str(value or 0)).quantize(Decimal('0.01'))
            fixed_total += ideal
        elif mode == 'remainder':
            remainder_indices.append(index)
        elif mode == 'percent':
            try:
                pct = Decimal(str(value or 0))
                ideal = (total * pct / Decimal('100')).quantize(Decimal('0.0001'))
            except Exception:
                ideal = Decimal('0.00')
        else:
            frac = _parse_fraction(value)
            if frac is not None:
                ideal = (total * Decimal(frac.numerator) / Decimal(frac.denominator)).quantize(
                    Decimal('0.0001')
                )

        ideal_amounts.append(ideal)

    pool_after_fixed = total - fixed_total
    if pool_after_fixed < 0:
        pool_after_fixed = Decimal('0.00')

    non_fixed_indices = [
        i for i, share in enumerate(ordered)
        if share.get('mode') not in ('fixed', 'remainder')
    ]
    non_fixed_ideal_sum = sum(ideal_amounts[i] for i in non_fixed_indices) or Decimal('0')

    for index in non_fixed_indices:
        if non_fixed_ideal_sum > 0:
            ideal_amounts[index] = (
                pool_after_fixed * ideal_amounts[index] / non_fixed_ideal_sum
            ).quantize(Decimal('0.0001'))

    for index in remainder_indices:
        assigned = sum(ideal_amounts[i] for i in range(len(ordered)) if i != index)
        ideal_amounts[index] = (total - assigned).quantize(Decimal('0.0001'))

    floored = []
    remainders = []
    running = Decimal('0.00')
    for index, ideal in enumerate(ideal_amounts):
        floor_val = ideal.quantize(Decimal('0.01'), rounding=ROUND_DOWN)
        floored.append(floor_val)
        running += floor_val
        remainders.append((ideal - floor_val, index))

    pennies_left = int(((total - running) * 100).quantize(Decimal('1')))
    remainders.sort(key=lambda item: (-item[0], item[1]))
    penny_adjustments = [Decimal('0.00')] * len(ordered)
    for i in range(pennies_left):
        idx = remainders[i % len(remainders)][1]
        floored[idx] += Decimal('0.01')
        penny_adjustments[idx] += Decimal('0.01')

    results = []
    for index, share in enumerate(ordered):
        results.append({
            'sort_order': share.get('sort_order', index),
            'projected_amount': floored[index],
            'penny_adjustment': penny_adjustments[index],
            'ideal_amount': ideal_amounts[index],
        })
    return results
