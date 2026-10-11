"""Independent money/calendar reference, never the generated workflow's helpers."""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP


def money(value):
    amount = Decimal(str(value))
    if not amount.is_finite() or amount != amount.quantize(Decimal(".01")):
        raise ValueError("Expected a finite amount in cents")
    return amount


def business_day(policy, day):
    return day.weekday() in policy.weekdays and day not in policy.holidays


def next_business(policy, day):
    for _ in range(370):
        if business_day(policy, day):
            return day
        day += timedelta(days=1)
    raise ValueError("No business day in the calendar horizon")


def band_for(policy, product):
    for band in policy.bands:
        if band.first <= product.days_late <= band.last:
            return band
    raise ValueError("Product is outside the supported delinquency bands")


def deadline(policy, product, now):
    remaining = band_for(policy, product).deadline_days
    day = now.date() if policy.count_today else now.date() + timedelta(days=1)
    for _ in range(370):
        if business_day(policy, day):
            remaining -= 1
            if not remaining:
                return day
        day += timedelta(days=1)
    raise ValueError("Deadline exceeds the calendar horizon")


def floor(policy, product):
    if policy.floor_mode == "account_field":
        return product.minimum
    return (product.balance * policy.floor_fraction).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)


def legal_promise(policy, product, amount, day, now):
    return (floor(policy, product) <= money(amount) <= product.balance
            and now.date() <= day <= deadline(policy, product, now) and business_day(policy, day))


def proposed_day(policy, product, requested, now):
    limit = deadline(policy, product, now)
    requested = max(requested or now.date(), now.date())
    return min(next_business(policy, requested), limit)
