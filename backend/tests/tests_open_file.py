from django.test import TestCase
from django.urls import reverse

from users.models import CustomUser

from ..models import (
    AuthorisedParties,
    ClientContactDetails,
    FileLocation,
    FileStatus,
    MatterType,
    OthersideDetails,
    WIP,
)


class OpenNewFileTests(TestCase):
    """Covers the open-file POST flow, which creates the client / authorised
    party / other side records alongside the matter itself."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='ofp', email='ofp@example.com', first_name='Open',
            last_name='File', password='password', max_holidays_in_year=20,
            is_matter_fee_earner=True,
        )
        self.client.force_login(self.user)
        self.file_status = FileStatus.objects.create(status='Open')
        self.matter_type = MatterType.objects.create(type='Conveyancing')
        self.file_location = FileLocation.objects.create(location='Cabinet A')

    def _payload(self, **overrides):
        payload = {
            'file_number': 'LIN0020001',
            'fee_earner': str(self.user.id),
            'file_status': str(self.file_status.id),
            'matter_type': str(self.matter_type.id),
            'funding': 'PF',
            'file_location': str(self.file_location.id),
            'zdrive_location': 'Z:/matters/LIN0020001',
            'matter_description': 'Sale of 1 Test Street',
            # New client, entered inline via the "+ New Client" picker.
            'client1': '-1',
            'ClientName1': 'Xia Lin',
            'Client1DOB': '',
            'Client1Occupation': 'Chef',
            'Client1AddressLine1': '1 Test Street',
            'Client1AddressLine2': '',
            'Client1County': 'Essex',
            'Client1Postcode': 'SS7 1QT',
            'Client1Email': 'xia@example.com',
            'Client1ContactNumber': '01702 123456',
            'Client1AMLCheckDate': '',
            'authorised_party1': '0',
            'authorised_party2': '0',
            'other_side': '0',
            'date_of_client_care_sent': '',
            'date_of_toe_sent': '',
            'date_of_toe_rcvd': '',
            'date_of_ncba_sent': '',
            'date_of_ncba_rcvd': '',
            'key_information': '',
            'comments': '',
        }
        payload.update(overrides)
        return payload

    def _new_otherside(self, contact_number):
        return {
            'other_side': '-1',
            'OSName': 'Bob Buyer',
            'OSAddressLine1': '2 Other Road',
            'OSAddressLine2': '',
            'OSCounty': 'Essex',
            'OSPostcode': 'SS7 2AB',
            'OSEmail': 'bob@example.com',
            'OSContactNumber': contact_number,
            'OSSolicitors': 'Some & Co',
            'OSSolicitorsEmail': 'sols@example.com',
        }

    def test_opens_file_and_creates_new_client(self):
        resp = self.client.post(reverse('new_file'), self._payload())

        self.assertRedirects(resp, reverse('index'))
        matter = WIP.objects.get(file_number='LIN0020001')
        self.assertEqual(matter.client1.name, 'Xia Lin')
        self.assertEqual(matter.created_by, self.user)

    def test_long_otherside_contact_number_is_accepted(self):
        """Staff qualify numbers with a contact name, e.g.
        "07877 260701 (Daniel Edwards)" — comfortably over the old 20-char
        column, which made the whole submission fail."""
        contact_number = '07877 260701 (Daniel Edwards)'
        self.assertGreater(len(contact_number), 20)
        # Asserted against the column directly as well: SQLite (used by the
        # local test fallback) ignores varchar limits, so only Postgres would
        # otherwise fail if this column were narrowed again.
        self.assertGreaterEqual(
            OthersideDetails._meta.get_field('contact_number').max_length,
            len(contact_number),
        )

        resp = self.client.post(
            reverse('new_file'),
            self._payload(**self._new_otherside(contact_number)),
        )

        self.assertRedirects(resp, reverse('index'))
        matter = WIP.objects.get(file_number='LIN0020001')
        self.assertEqual(matter.other_side.contact_number, contact_number)

    def test_failed_open_leaves_no_orphan_contacts(self):
        """A failure part-way through must roll back the contact records too,
        otherwise each retry leaves another duplicate client behind."""
        existing_client = ClientContactDetails.objects.create(
            name='Already Here', occupation='Retired', address_line1='9 St',
            address_line2='', county='Essex', postcode='SS7 9ZZ',
            email='a@example.com', contact_number='0123456789',
        )
        WIP.objects.create(
            file_number='LIN0020001', client1=existing_client,
            matter_description='Existing', matter_type=self.matter_type,
            file_status=self.file_status, funding='PF',
        )
        clients_before = ClientContactDetails.objects.count()
        othersides_before = OthersideDetails.objects.count()

        # Same file number as the matter above — unique, so the form rejects it.
        resp = self.client.post(
            reverse('new_file'),
            self._payload(**self._new_otherside('01702 999888')),
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(WIP.objects.filter(file_number='LIN0020001').count(), 1)
        self.assertEqual(ClientContactDetails.objects.count(), clients_before)
        self.assertEqual(OthersideDetails.objects.count(), othersides_before)
        self.assertFalse(
            ClientContactDetails.objects.filter(name='Xia Lin').exists())

    def test_failed_open_redisplays_what_was_typed(self):
        existing_client = ClientContactDetails.objects.create(
            name='Already Here', occupation='Retired', address_line1='9 St',
            address_line2='', county='Essex', postcode='SS7 9ZZ',
            email='a@example.com', contact_number='0123456789',
        )
        WIP.objects.create(
            file_number='LIN0020001', client1=existing_client,
            matter_description='Existing', matter_type=self.matter_type,
            file_status=self.file_status, funding='PF',
        )

        resp = self.client.post(reverse('new_file'), self._payload())

        self.assertEqual(resp.status_code, 200)
        # The matter details the user typed survive the failed submission.
        self.assertContains(resp, 'LIN0020001')
        self.assertContains(resp, 'Sale of 1 Test Street')

    def test_new_authorised_party_is_attached(self):
        resp = self.client.post(reverse('new_file'), self._payload(**{
            'authorised_party1': '-1',
            'APName1': 'Ann Agent',
            'AP1RelationshipToC': 'Attorney',
            'AP1AddressLine1': '3 Agent Way',
            'AP1AddressLine2': '',
            'AP1County': 'Essex',
            'AP1Postcode': 'SS7 3CD',
            'AP1Email': 'ann@example.com',
            'AP1ContactNumber': '01702 555444',
            'AP1IDCheckDate': '',
            'AP1AMLCheckDate': '',
        }))

        self.assertRedirects(resp, reverse('index'))
        matter = WIP.objects.get(file_number='LIN0020001')
        self.assertEqual(matter.authorised_party1.name, 'Ann Agent')
        self.assertEqual(AuthorisedParties.objects.count(), 1)
