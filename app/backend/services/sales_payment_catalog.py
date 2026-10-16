"""Owner-approved new-sale Stripe links, verified 2026-10-16.

Public URLs only; no API credential. Match the complete catalog identity, never a
name/substring/price alone. Changes require a separately reviewed new mapping.
"""
from decimal import Decimal, InvalidOperation

STRIPE_ACCOUNT_ID = "acct_1QxFjbIdE9Gt7xxR"
CADENCES = {"monthly": "每月", "quarterly": "每3个月", "annual": "每年"}
APPROVED_LINKS = ({'plan_code': 't24-managed-basic-stripe-auto-monthly-202610',
  'amount_minor': 19800,
  'currency': 'USD',
  'billing_cycle': 'monthly',
  'url': 'https://buy.stripe.com/aFabJ1h030Pnh0WePK5gc0E',
  'payment_link_id': 'plink_1UQyQ3IdE9Gt7xxRsrHI9ZD2'},
 {'plan_code': 't24-managed-basic-stripe-auto-quarterly-202610',
  'amount_minor': 53460,
  'currency': 'USD',
  'billing_cycle': 'quarterly',
  'url': 'https://buy.stripe.com/6oUcN5h03eGd9yu4b65gc0F',
  'payment_link_id': 'plink_1UQyS1IdE9Gt7xxRWgExJIJB'},
 {'plan_code': 't24-managed-basic-stripe-auto-annual-202610',
  'amount_minor': 190080,
  'currency': 'USD',
  'billing_cycle': 'annual',
  'url': 'https://buy.stripe.com/3cIdR9dNReGddOKbDy5gc0G',
  'payment_link_id': 'plink_1UQyShIdE9Gt7xxRzFxB1Q0S'},
 {'plan_code': 't24-managed-advanced-stripe-auto-monthly-202610',
  'amount_minor': 24900,
  'currency': 'USD',
  'billing_cycle': 'monthly',
  'url': 'https://buy.stripe.com/3cI14n7pt9lTh0W7ni5gc0H',
  'payment_link_id': 'plink_1UQyTCIdE9Gt7xxRIoHLoZ3D'},
 {'plan_code': 't24-managed-advanced-stripe-auto-quarterly-202610',
  'amount_minor': 67230,
  'currency': 'USD',
  'billing_cycle': 'quarterly',
  'url': 'https://buy.stripe.com/aFa6oH2598hP11Y9vq5gc0I',
  'payment_link_id': 'plink_1UQyUaIdE9Gt7xxRAhvkK7dg'},
 {'plan_code': 't24-managed-professional-stripe-auto-monthly-202610',
  'amount_minor': 32900,
  'currency': 'USD',
  'billing_cycle': 'monthly',
  'url': 'https://buy.stripe.com/5kQ8wP4dh69Hh0WbDy5gc0J',
  'payment_link_id': 'plink_1UQyUrIdE9Gt7xxRtxqrSE25'},
 {'plan_code': 't24-managed-advanced-stripe-auto-annual-202610',
  'amount_minor': 239040,
  'currency': 'USD',
  'billing_cycle': 'annual',
  'url': 'https://buy.stripe.com/9B67sLeRV8hPeSO22Y5gc0K',
  'payment_link_id': 'plink_1UQyV8IdE9Gt7xxRhpyAmVF7'},
 {'plan_code': 't24-managed-professional-stripe-auto-quarterly-202610',
  'amount_minor': 88830,
  'currency': 'USD',
  'billing_cycle': 'quarterly',
  'url': 'https://buy.stripe.com/28E00jh03bu16mi5fa5gc0L',
  'payment_link_id': 'plink_1UQyVlIdE9Gt7xxR0x8kj1Sh'},
 {'plan_code': 't24-managed-flagship-stripe-auto-monthly-202610',
  'amount_minor': 49900,
  'currency': 'USD',
  'billing_cycle': 'monthly',
  'url': 'https://buy.stripe.com/14A28r9xBapXcKGazu5gc0M',
  'payment_link_id': 'plink_1UQyW1IdE9Gt7xxRZgPuZKpA'},
 {'plan_code': 't24-managed-professional-stripe-auto-annual-202610',
  'amount_minor': 315840,
  'currency': 'USD',
  'billing_cycle': 'annual',
  'url': 'https://buy.stripe.com/6oUbJ1dNRbu1eSO9vq5gc0N',
  'payment_link_id': 'plink_1UQyWBIdE9Gt7xxRLRfEmTXP'},
 {'plan_code': 't24-managed-flagship-stripe-auto-quarterly-202610',
  'amount_minor': 134730,
  'currency': 'USD',
  'billing_cycle': 'quarterly',
  'url': 'https://buy.stripe.com/14A5kD6lp69HbGC5fa5gc0O',
  'payment_link_id': 'plink_1UQyWXIdE9Gt7xxRzyAp7ZwG'},
 {'plan_code': 't24-managed-flagship-stripe-auto-annual-202610',
  'amount_minor': 479040,
  'currency': 'USD',
  'billing_cycle': 'annual',
  'url': 'https://buy.stripe.com/00w8wP2590PndOKgXS5gc0P',
  'payment_link_id': 'plink_1UQyWiIdE9Gt7xxRYimQXBN0'})


def approved_link(plan):
    if plan.get("required_collection_method") != "stripe_auto":
        return None
    try:
        amount = Decimal(str(plan.get("standard_price")))
        if not amount.is_finite() or amount != amount.quantize(Decimal("0.01")):
            return None
        minor = int(amount * 100)
    except (InvalidOperation, TypeError, ValueError):
        return None
    for item in APPROVED_LINKS:
        if (item["plan_code"] == plan.get("plan_code")
                and item["amount_minor"] == minor
                and item["currency"] == plan.get("default_currency")
                and item["billing_cycle"] == plan.get("default_billing_cycle")):
            return dict(item)
    return None


def catalog_link(plan):
    item = approved_link(plan)
    if not item:
        return None
    return {"url": item["url"], "amount": item["amount_minor"] / 100,
        "currency": item["currency"], "billing_cycle": item["billing_cycle"],
        "cadence_label": CADENCES[item["billing_cycle"]],
        "tax_mode": "exclusive", "automatic_renewal": True,
        "binding_required": True}
