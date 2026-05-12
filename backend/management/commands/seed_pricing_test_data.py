from decimal import Decimal

from django.core.management.base import BaseCommand

from backend.models import MatterType, PricingItem


class Command(BaseCommand):
    help = 'Load editable starter pricing test data from public pricing research.'

    def handle(self, *args, **options):
        matter_types = {}
        for matter_type in [
            'Residential Conveyancing',
            'Wills',
            'Lasting Power of Attorney',
            'Probate',
            'Divorce and Family',
        ]:
            matter_types[matter_type], _ = MatterType.objects.get_or_create(type=matter_type)

        source_note = 'Test data from public pricing research; review before client use.'
        items = [
            self.item('veriphy', 'Veriphy AML and anti-fraud check', 'range', min_price='6.00', max_price='10.00',
                      notes=f'{source_note} Veriphy public pricing lists AML checks from £6 and Veriphy 360 at £10 ex VAT.'),
            self.item('veriphy', 'Veriphy biometric check', 'range', min_price='3.50', max_price='5.00',
                      notes=f'{source_note} Veriphy public pricing lists standalone biometric checks at £3.50/£5.00 ex VAT.'),
            self.item('veriphy', 'Veriphy PEP and sanctions screen', 'fixed', price='1.50',
                      notes=f'{source_note} Veriphy public pricing lists standalone PEP/Sanctions screen at £1.50 ex VAT.'),
            self.item('veriphy', 'Veriphy bank account verification', 'fixed', price='1.00',
                      notes=f'{source_note} Veriphy public pricing lists bank account verification at £1.00 ex VAT.'),
            self.item('veriphy', 'Veriphy source of funds analysis', 'fixed', price='15.00',
                      notes=f'{source_note} Veriphy public pricing lists source of funds analysis at £15.00 ex VAT.'),
            self.item('veriphy', 'Veriphy lawyer bank account check', 'fixed', price='18.00',
                      notes=f'{source_note} Veriphy public pricing lists lawyer bank account check at £18.00 ex VAT.'),

            self.item('conveyancing', 'Freehold sale legal fee', 'range', matter_type='Residential Conveyancing',
                      min_price='1250.00', max_price='1750.00',
                      notes=f'{source_note} Public conveyancing tables show freehold sale legal fees rising by property value; VAT added.'),
            self.item('conveyancing', 'Freehold purchase legal fee', 'range', matter_type='Residential Conveyancing',
                      min_price='1450.00', max_price='1950.00',
                      notes=f'{source_note} Public conveyancing tables show freehold purchase legal fees rising by property value; VAT added.'),
            self.item('conveyancing', 'Leasehold sale legal fee', 'range', matter_type='Residential Conveyancing',
                      min_price='2000.00', max_price='2450.00',
                      notes=f'{source_note} Public conveyancing tables show leasehold sales priced higher than freehold sales; VAT added.'),
            self.item('conveyancing', 'Leasehold purchase legal fee', 'range', matter_type='Residential Conveyancing',
                      min_price='2350.00', max_price='3000.00',
                      notes=f'{source_note} Public conveyancing tables show leasehold purchases priced higher than freehold purchases; VAT added.'),
            self.item('conveyancing', 'New build supplement', 'fixed', matter_type='Residential Conveyancing',
                      price='600.00',
                      notes=f'{source_note} Public conveyancing examples list new build supplements at around £600 plus VAT.'),
            self.item('conveyancing', 'Bank transfer administration fee', 'fixed', matter_type='Residential Conveyancing',
                      price='30.00',
                      notes=f'{source_note} Public conveyancing examples list bank transfer administration fees around £30 plus VAT.'),
            self.item('searches', 'Purchase search pack', 'range', min_price='300.00', max_price='450.00',
                      notes=f'{source_note} Public conveyancing examples describe search packs around £300-£450 depending on location.'),
            self.item('disbursements', 'HM Land Registry fee', 'range', min_price='20.00', max_price='1105.00',
                      vat_treatment='none',
                      notes=f'{source_note} Public conveyancing examples show Land Registry fees vary by value and are not VAT charged.'),

            self.item('wills', 'Single will', 'range', matter_type='Wills', min_price='180.00', max_price='300.00',
                      notes=f'{source_note} Public Essex/UK examples list single wills from about £180-£300 plus VAT.'),
            self.item('wills', 'Mirror wills', 'range', matter_type='Wills', min_price='320.00', max_price='500.00',
                      notes=f'{source_note} Public examples list mirror wills around £320-£500 plus VAT.'),
            self.item('wills', 'Trust will', 'range', matter_type='Wills', min_price='500.00', max_price='700.00',
                      notes=f'{source_note} Public examples list trust will starting prices around £500-£700 plus VAT.'),

            self.item('lpa', 'One LPA for one person', 'range', matter_type='Lasting Power of Attorney',
                      min_price='350.00', max_price='600.00',
                      notes=f'{source_note} Public LPA examples list one-document LPA fees around £350-£600 plus VAT.'),
            self.item('lpa', 'Two LPAs for one person', 'range', matter_type='Lasting Power of Attorney',
                      min_price='500.00', max_price='900.00',
                      notes=f'{source_note} Public LPA examples list two-document LPA fees around £500-£900 plus VAT.'),
            self.item('lpa', 'OPG registration fee per LPA', 'fixed', matter_type='Lasting Power of Attorney',
                      price='82.00', vat_treatment='none',
                      notes=f'{source_note} Public LPA examples note Office of the Public Guardian registration fee of £82 per LPA.'),

            self.item('probate', 'Grant of probate application', 'range', matter_type='Probate',
                      min_price='800.00', max_price='895.00',
                      notes=f'{source_note} Public probate fixed-fee examples list grant applications around £800-£895 plus VAT.'),
            self.item('probate', 'Letters of administration application', 'fixed', matter_type='Probate',
                      price='995.00',
                      notes=f'{source_note} Public probate examples list letters of administration at around £995 plus VAT.'),

            self.item('divorce_family', 'Undefended divorce - applicant', 'range', matter_type='Divorce and Family',
                      min_price='385.00', max_price='550.00',
                      notes=f'{source_note} Public Essex fixed-fee divorce examples list applicant fees around £385-£550 plus VAT, court fee extra.'),
            self.item('divorce_family', 'Undefended divorce - respondent', 'range', matter_type='Divorce and Family',
                      min_price='200.00', max_price='395.00',
                      notes=f'{source_note} Public Essex fixed-fee divorce examples list respondent fees around £200-£395 plus VAT.'),
            self.item('divorce_family', 'Divorce court issue fee', 'fixed', matter_type='Divorce and Family',
                      price='593.00', vat_treatment='none',
                      notes=f'{source_note} Public family pricing examples list the divorce petition court issue fee at £593.'),
        ]

        created = 0
        updated = 0
        for item in items:
            matter_type_name = item.pop('matter_type_name', None)
            matter_type = matter_types.get(matter_type_name)
            defaults = {
                **item,
                'matter_type': matter_type,
                'manager_only': True,
                'is_active': True,
            }
            _, was_created = PricingItem.objects.update_or_create(
                category=item['category'],
                name=item['name'],
                defaults=defaults,
            )
            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(self.style.SUCCESS(
            f'Pricing test data loaded. Created {created}, updated {updated}.'
        ))

    def item(
        self,
        category,
        name,
        pricing_type,
        price=None,
        min_price=None,
        max_price=None,
        matter_type=None,
        vat_treatment='excluding',
        notes='',
    ):
        return {
            'category': category,
            'name': name,
            'pricing_type': pricing_type,
            'price': Decimal(price) if price is not None else None,
            'minimum_price': Decimal(min_price) if min_price is not None else None,
            'maximum_price': Decimal(max_price) if max_price is not None else None,
            'matter_type_name': matter_type,
            'vat_treatment': vat_treatment,
            'notes': notes,
        }
