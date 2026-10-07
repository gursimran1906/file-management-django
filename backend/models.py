from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from users.models import CustomUser
from django_quill.fields import QuillField
from math import ceil
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from decimal import Decimal
import os
import secrets
import uuid
from django.conf import settings
from django.core.files.storage import FileSystemStorage

from backend.sharepoint.paths import (
    bundle_document_upload_path,
    bundle_final_pdf_upload_path,
    undertaking_file_upload_path,
)


CURRENT_VAT_RATE = Decimal('0.20')


def get_sentinel_user():
    return get_user_model().objects.get_or_create(username="deleted")[0]


class Modifications(models.Model):
    id = models.AutoField(primary_key=True)
    modified_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, related_name='modifications', null=True, blank=True)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    modified_obj = GenericForeignKey('content_type', 'object_id')
    changes = models.JSONField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['content_type', 'object_id'],
                         name='modifications_obj_idx'),
        ]


class ClientContactDetails(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255)
    is_business = models.BooleanField(default=False)
    dob = models.DateField(null=True, blank=True)
    occupation = models.CharField(max_length=255)
    address_line1 = models.CharField(max_length=255)
    address_line2 = models.CharField(max_length=255)
    county = models.CharField(max_length=255)
    postcode = models.CharField(max_length=10)
    email = models.CharField(max_length=50)
    contact_number = models.CharField(max_length=50)
    date_of_last_aml = models.DateField(null=True, blank=True)
    id_verified = models.BooleanField(null=True, blank=True)
    terms_of_engagement_signed = models.BooleanField(default=False)
    ncba_signed = models.BooleanField(default=False)
    pep_signed = models.BooleanField(default=False)
    source_of_funds_signed = models.BooleanField(default=False)
    timestamp = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, related_name='client_created_by', null=True, blank=True)

    def __str__(self):
        return f'{self.name}'


def client_key_doc_storage():
    """Private, auth-served storage for client key-document scans (proof of ID /
    address). Served only through the login-protected preview view."""
    return FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, 'client_key_docs'))


def client_key_document_upload_path(instance, filename):
    from backend.sharepoint.paths import sanitize_filename
    return f'{instance.client_id}/{instance.category}-{uuid.uuid4()}_{sanitize_filename(filename)}'


class ClientKeyDocument(models.Model):
    DOCUMENT_CATEGORY_CHOICES = [
        ('proof_of_id', 'Proof of ID'),
        ('proof_of_address', 'Proof of Address'),
        ('selfie_id', 'Selfie with ID'),
    ]

    id = models.AutoField(primary_key=True)
    client = models.ForeignKey(
        ClientContactDetails, on_delete=models.CASCADE, related_name='key_documents')
    category = models.CharField(max_length=50, choices=DOCUMENT_CATEGORY_CHOICES)
    document_type = models.CharField(max_length=100, blank=True)
    document_reference = models.CharField(max_length=100, blank=True)
    issue_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    verified_on = models.DateField(null=True, blank=True)
    verified_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, related_name='verified_client_key_documents', null=True, blank=True)
    # The actual scan of the document. Older records hold only the metadata above
    # (no file); staff can upload the file to those too.
    file = models.FileField(
        upload_to=client_key_document_upload_path,
        storage=client_key_doc_storage, null=True, blank=True)
    notes = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.client} - {self.get_category_display()} - {self.document_type}'


class ConflictCheck(models.Model):
    """Audit record of a conflict-of-interest check run before onboarding a
    client. Every check (whether clear or not) is logged for SRA compliance:
    who ran it, when, the name searched, what matches were found across
    clients/opposing parties/authorised parties, and whether the user
    acknowledged proceeding despite a potential conflict."""

    RESULT_CLEAR = 'clear'
    RESULT_POTENTIAL = 'potential_conflict'
    RESULT_CHOICES = [
        (RESULT_CLEAR, 'No conflict found'),
        (RESULT_POTENTIAL, 'Potential conflict found'),
    ]

    id = models.AutoField(primary_key=True)
    searched_name = models.CharField(max_length=255)
    searched_dob = models.DateField(null=True, blank=True)
    result = models.CharField(
        max_length=20, choices=RESULT_CHOICES, default=RESULT_CLEAR)
    # Snapshot of the matches found at the time of the check, so the audit
    # record stands alone even if the underlying records later change.
    matches = models.JSONField(default=list, blank=True)
    acknowledged = models.BooleanField(default=False)
    acknowledgement_note = models.TextField(blank=True)
    # The onboarding case the check was run for (the usual entry point).
    onboarding = models.ForeignKey(
        'Onboarding', on_delete=models.CASCADE,
        related_name='conflict_checks', null=True, blank=True)
    # Set once the checked person is actually onboarded as a client / linked
    # to the matter the check was run for.
    client = models.ForeignKey(
        ClientContactDetails, on_delete=models.SET_NULL,
        related_name='conflict_checks', null=True, blank=True)
    wip = models.ForeignKey(
        'WIP', on_delete=models.SET_NULL,
        related_name='conflict_checks', null=True, blank=True)
    performed_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL,
        related_name='conflict_checks_performed', null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f'Conflict check: {self.searched_name} ({self.get_result_display()})'


class AuthorisedParties(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=50)
    relationship_to_client = models.CharField(max_length=50)
    address_line1 = models.CharField(max_length=50)
    address_line2 = models.CharField(max_length=50)
    county = models.CharField(max_length=50)
    postcode = models.CharField(max_length=50)
    email = models.CharField(max_length=50)
    contact_number = models.CharField(max_length=50)
    id_check = models.BooleanField(null=True, blank=True)
    date_of_id_check = models.DateField(null=True, blank=True)
    date_of_last_aml = models.DateField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, related_name='ap_created_by', null=True, blank=True)

    def __str__(self):
        return f'ID: {self.id}, Name: {self.name}'


class OthersideDetails(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255, null=True, blank=True)
    is_business = models.BooleanField(default=False)
    # Date of birth applies to an individual other side; date of incorporation
    # applies when the other side is a business/company.
    dob = models.DateField(null=True, blank=True)
    date_of_incorporation = models.DateField(null=True, blank=True)
    address_line1 = models.CharField(max_length=255, null=True, blank=True)
    address_line2 = models.CharField(max_length=255, null=True, blank=True)
    county = models.CharField(max_length=255, null=True, blank=True)
    postcode = models.CharField(max_length=10, null=True, blank=True)
    email = models.CharField(max_length=255, null=True, blank=True)
    contact_number = models.CharField(max_length=20, null=True, blank=True)
    solicitors = models.CharField(max_length=255, null=True, blank=True)
    solicitors_email = models.CharField(max_length=255, null=True, blank=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, related_name='os_created_by', null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return str(self.name)


class FileLocation(models.Model):
    id = models.AutoField(primary_key=True)
    location = models.CharField(max_length=255)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL,
                                   related_name='file_location_created_by', null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return str(self.location)


class FileStatus(models.Model):
    id = models.AutoField(primary_key=True)
    status = models.CharField(max_length=255)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL,
                                   related_name='file_status_created_by', null=True, blank=True)

    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.status


class MatterType(models.Model):
    id = models.AutoField(primary_key=True)
    type = models.CharField(max_length=255)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL,
                                   related_name='matter_type_created_by', null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return str(self.type)


class PricingItem(models.Model):
    CATEGORY_CHOICES = [
        ('conveyancing', 'Conveyancing'),
        ('wills', 'Wills'),
        ('lpa', 'LPA'),
        ('probate', 'Probate'),
        ('divorce_family', 'Divorce and Family'),
        ('veriphy', 'Veriphy Checks'),
        ('searches', 'Searches'),
        ('disbursements', 'Disbursements'),
        ('general', 'General'),
        ('other', 'Other'),
    ]

    PRICING_TYPE_CHOICES = [
        ('fixed', 'Fixed price'),
        ('range', 'Range'),
    ]

    VAT_TREATMENT_CHOICES = [
        ('excluding', 'Excluding VAT'),
        ('including', 'Including VAT'),
        ('none', 'No VAT'),
    ]

    id = models.AutoField(primary_key=True)
    category = models.CharField(
        max_length=30, choices=CATEGORY_CHOICES, default='general'
    )
    matter_type = models.ForeignKey(
        MatterType, on_delete=models.SET_NULL, null=True, blank=True, related_name='pricing'
    )
    name = models.CharField(max_length=255)
    pricing_type = models.CharField(
        max_length=10, choices=PRICING_TYPE_CHOICES, default='fixed'
    )
    price = models.DecimalField(decimal_places=2, max_digits=10, null=True, blank=True)
    minimum_price = models.DecimalField(decimal_places=2, max_digits=10, null=True, blank=True)
    maximum_price = models.DecimalField(decimal_places=2, max_digits=10, null=True, blank=True)
    vat_treatment = models.CharField(
        max_length=10, choices=VAT_TREATMENT_CHOICES, default='excluding'
    )
    notes = models.TextField(null=True, blank=True)
    manager_only = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, related_name='pricing_item_created_by', null=True, blank=True
    )
    updated_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, related_name='pricing_item_updated_by', null=True, blank=True
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['category', 'matter_type__type', 'name']
        verbose_name = 'Pricing item'
        verbose_name_plural = 'Pricing items'

    def __str__(self):
        return f'{self.name} - {self.display_price}'

    @property
    def display_price(self):
        if self.pricing_type == 'range':
            if self.minimum_price is not None and self.maximum_price is not None:
                return f'£{self.minimum_price} - £{self.maximum_price}'
            return 'Range'
        if self.price is not None:
            return f'£{self.price}'
        return 'Price not set'

    def can_edit(self, user):
        return bool(getattr(user, 'is_manager', False) or (self.is_active and not self.manager_only))


class WIP(models.Model):
    def convert_on_to_bool(self, value):
        return value.lower() == 'on' if value else False

    id = models.AutoField(primary_key=True)
    file_number = models.CharField(
        max_length=10, unique=True, null=True, blank=True)
    fee_earner = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, related_name='fee_earner',
                                   null=True, blank=True, limit_choices_to={'is_matter_fee_earner': True})
    matter_description = models.CharField(
        max_length=500, null=True, blank=True)

    # client1 is the primary/lead client for the matter. It drives all
    # correspondence, invoicing, ledgers and report headers. Any further
    # clients on the matter are held in additional_clients (no fixed limit).
    client1 = models.ForeignKey(ClientContactDetails, on_delete=models.SET(
        get_sentinel_user), related_name='client1_wip', )
    additional_clients = models.ManyToManyField(
        ClientContactDetails, related_name='additional_client_wips', blank=True)

    matter_type = models.ForeignKey(
        MatterType, on_delete=models.SET_NULL, related_name='matter_type', null=True)
    file_status = models.ForeignKey(
        FileStatus, on_delete=models.SET_NULL, related_name='file_status', null=True)
    file_location = models.ForeignKey(
        FileLocation, on_delete=models.SET_NULL, related_name='file_location', null=True)

    other_side = models.ForeignKey(
        OthersideDetails, on_delete=models.SET_NULL, null=True, blank=True)
    date_of_client_care_sent = models.DateField(null=True, blank=True)
    date_of_toe_sent = models.DateField(null=True, blank=True)
    date_of_toe_rcvd = models.DateField(null=True, blank=True)
    date_of_ncba_sent = models.DateField(null=True, blank=True)
    date_of_ncba_rcvd = models.DateField(null=True, blank=True)
    # Non-contentious business agreement is a matter-level fact: when the matter
    # is under one, every client on it signs the NCBA for this file (tracked on
    # MatterClient). Off by default — most files have none.
    ncba_required = models.BooleanField(default=False)
    zdrive_location = models.CharField(max_length=500, null=True, blank=True)

    funding = models.CharField(max_length=3)
    authorised_party1 = models.ForeignKey(
        AuthorisedParties, on_delete=models.SET_NULL, related_name='auth_party1_wip', null=True, blank=True)
    authorised_party2 = models.ForeignKey(
        AuthorisedParties, on_delete=models.SET_NULL, related_name='auth_party2_wip', null=True, blank=True)

    key_information = models.TextField(null=True, blank=True)

    comments = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, related_name='wip_created_by', null=True, blank=True)

    timestamp = models.DateTimeField(auto_now_add=True)

    @property
    def all_clients(self):
        """Every client on the matter (client1 first, then the additional
        clients). All clients are treated equally — use this wherever the full
        client list is needed: displays, AML/risk collection, search, and
        invoicing/correspondence (addresses, names, email recipients)."""
        clients = [self.client1] if self.client1_id else []
        clients.extend(self.additional_clients.all())
        return clients

    @property
    def all_client_names(self):
        """All client names joined for headers, filenames and statements."""
        return ' & '.join(client.name for client in self.all_clients)

    @property
    def all_client_emails(self):
        """Distinct, non-empty client emails for correspondence, in order."""
        emails = []
        for client in self.all_clients:
            if client.email and client.email not in emails:
                emails.append(client.email)
        return emails

    def __str__(self):
        return self.file_number


class MatterKeyDate(models.Model):
    DATE_TYPE_CHOICES = [
        ('hearing', 'Hearing'),
        ('meeting', 'Meeting'),
        ('conference', 'Conference'),
        ('mediation', 'Mediation'),
        ('deadline', 'Deadline'),
        ('appointment', 'Appointment'),
        ('other', 'Other'),
    ]

    id = models.AutoField(primary_key=True)
    matter = models.ForeignKey(
        WIP, on_delete=models.CASCADE, related_name='key_dates')
    date_type = models.CharField(
        max_length=50, choices=DATE_TYPE_CHOICES, default='other')
    title = models.CharField(max_length=255)
    date = models.DateField()
    time = models.TimeField(null=True, blank=True)
    location = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, related_name='matter_key_dates_created_by', null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date', 'time', 'title']

    def __str__(self):
        return f'{self.matter} - {self.get_date_type_display()} - {self.title}'


class NextWork(models.Model):
    STATUS_CHOICES = [
        ('to_do', 'To Do'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
    ]

    URGENCY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]

    id = models.AutoField(primary_key=True)
    file_number = models.ForeignKey(WIP, on_delete=models.SET_NULL, null=True)
    person = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True)
    task = models.TextField(null=True, blank=True)
    date = models.DateField(null=True, blank=True)
    completed = models.BooleanField(default=False, null=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='to_do')
    urgency = models.CharField(
        max_length=10, choices=URGENCY_CHOICES, default='medium')
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL,
                                   related_name='next_work_created_by', null=True, blank=True)
    is_admin_pool = models.BooleanField(default=False)
    timestamp = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        # Admin pool tasks are unassigned and always sit in the "to do" queue
        # until a staff member picks one up.
        if self.is_admin_pool:
            self.person = None
            self.status = 'to_do'

        # Sync completed field with status
        if self.status == 'completed':
            self.completed = True
        else:
            self.completed = False

        super().save(*args, **kwargs)

        # Create LastWork entry when task is completed
        if self.completed and self.status == 'completed':
            # Check if LastWork entry already exists to avoid duplicates
            if not LastWork.objects.filter(
                file_number=self.file_number,
                person=self.person,
                task=self.task,
                date=self.date
            ).exists():
                LastWork.objects.create(
                    file_number=self.file_number,
                    person=self.person,
                    task=self.task,
                    date=self.date,
                    created_by=self.created_by
                )


class LastWork(models.Model):
    id = models.AutoField(primary_key=True)
    file_number = models.ForeignKey(WIP, on_delete=models.SET_NULL, null=True)
    person = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True)
    task = models.TextField(null=True, blank=True)
    date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL,
                                   related_name='last_work_created_by', null=True, blank=True)

    timestamp = models.DateTimeField(auto_now_add=True)


class PmtsSlips(models.Model):
    LEDGER_ACCOUNT_CHOICES = [
        ('C', 'Client'),
        ('O', 'Office'),
    ]
    MODE_OF_PAYMENT_CHOICES = [
        ('BT', 'Bank Transfer'),
        ('CA', 'Cash'),
        ('CH', 'Cheque'),
        ('DC', 'Dr/Cr Card'),
    ]
    id = models.AutoField(primary_key=True)
    file_number = models.ForeignKey(WIP, on_delete=models.SET_NULL, null=True)
    ledger_account = models.CharField(
        max_length=1, choices=LEDGER_ACCOUNT_CHOICES)
    mode_of_pmt = models.CharField(
        max_length=20, choices=MODE_OF_PAYMENT_CHOICES)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    is_money_out = models.BooleanField(null=True, blank=True)
    pmt_person = models.CharField(max_length=50)
    description = models.CharField(max_length=255)
    date = models.DateField()
    amount_invoiced = models.JSONField(default=dict, null=True, blank=True)
    amount_allocated = models.JSONField(default=dict, null=True, blank=True)
    balance_left = models.DecimalField(max_digits=15, decimal_places=2)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL,
                                   related_name='pmt_slip_created_by', null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)


class LedgerAccountTransfers(models.Model):
    LEDGER_ACCOUNT_CHOICES = [
        ('C', 'Client'),
        ('O', 'Office'),
    ]
    id = models.AutoField(primary_key=True)
    file_number_from = models.ForeignKey(
        WIP, on_delete=models.SET_NULL, null=True, related_name='transfers_from')
    file_number_to = models.ForeignKey(
        WIP, on_delete=models.SET_NULL, null=True, related_name='transfers_to')
    from_ledger_account = models.CharField(
        max_length=1, choices=LEDGER_ACCOUNT_CHOICES)
    to_ledger_account = models.CharField(
        max_length=1, choices=LEDGER_ACCOUNT_CHOICES)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    date = models.DateField()
    description = models.CharField(max_length=100)
    amount_invoiced_from = models.JSONField(
        default=dict, null=True, blank=True)
    balance_left_from = models.DecimalField(max_digits=15, decimal_places=2)
    amount_invoiced_to = models.JSONField(default=dict, null=True, blank=True)
    balance_left_to = models.DecimalField(max_digits=15, decimal_places=2)
    is_cashier_co_transfer = models.BooleanField(default=False)
    is_bank_transfer_done = models.BooleanField(default=False)
    bank_transfer_done_on = models.DateField(null=True, blank=True)
    bank_transfer_done_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL,
        related_name='bank_transfer_done_by', null=True, blank=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL,
                                   related_name='green_slip_created_by', null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)


class TempSlips(models.Model):
    id = models.AutoField(primary_key=True)
    file_number = models.CharField(max_length=11)
    date = models.DateField()
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    description = models.CharField(max_length=999)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL,
                                   related_name='temp_slip_created_by', null=True, blank=True)

    timestamp = models.DateTimeField(auto_now_add=True)


class Invoices(models.Model):
    STATES = [
        ('F', 'Final'),
        ('D', 'Draft'),
    ]
    VAT_CALCULATION_MODES = [
        ('auto', 'Auto'),
        ('manual', 'Manual'),
    ]
    id = models.AutoField(primary_key=True)
    invoice_number = models.IntegerField(null=True, blank=True)
    state = models.CharField(max_length=1, choices=STATES)
    file_number = models.ForeignKey(WIP, on_delete=models.SET_NULL, null=True)
    date = models.DateField()
    payable_by = models.CharField(default='Client', max_length=255)
    by_email = models.BooleanField(null=True, blank=True)
    by_post = models.BooleanField(null=True, blank=True)
    is_matter_final_invoice = models.BooleanField(
        default=False,
        help_text='Marks this as the closing invoice for the matter (shown on printed invoices).',
    )
    description = models.TextField()
    our_costs_desc = models.JSONField(default=dict)
    our_costs = models.JSONField(default=dict)
    vat = models.DecimalField(
        decimal_places=2, max_digits=15, null=True, blank=True, default=0)
    vat_calculation_mode = models.CharField(
        max_length=10, choices=VAT_CALCULATION_MODES, default='auto', blank=True)
    disbs_ids = models.ManyToManyField(
        PmtsSlips, related_name='disbs_invoices', blank=True)
    moa_ids = models.ManyToManyField(
        PmtsSlips, related_name='moa_invoices', blank=True)
    cash_allocated_slips = models.ManyToManyField(
        PmtsSlips, related_name='cash_allocated_invoices', blank=True)
    green_slip_ids = models.ManyToManyField(
        LedgerAccountTransfers, related_name='green_slips_invoices', blank=True)
    total_due_left = models.DecimalField(
        decimal_places=2, max_digits=15, null=True, blank=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, related_name='invoice_created_by', null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)


class CreditNote(models.Model):
    STATUSES = [
        ('P', 'Pending Approval'),
        ('F', 'Final'),
        ('R', 'Rejected'),
    ]

    id = models.AutoField(primary_key=True)
    invoice = models.ForeignKey(
        Invoices, on_delete=models.CASCADE, related_name='credit_notes')
    file_number = models.ForeignKey(
        WIP, on_delete=models.CASCADE, related_name='credit_notes')
    date = models.DateField()
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    reason = models.TextField()
    status = models.CharField(max_length=1, choices=STATUSES, default='P')
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, related_name='credit_note_created_by', null=True, blank=True)
    approved_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, related_name='credit_note_approved_by', null=True, blank=True)
    approved_on = models.DateTimeField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)


class RiskAssessment(models.Model):
    RISK_LEVEL_CHOICES = [
        ('Low', 'Low'),
        ('Medium', 'Medium'),
        ('High', 'High'),
    ]

    DUE_DILIGENCE_LEVEL_CHOICES = [
        ('Enhanced', 'Enhanced'),
        ('Standard', 'Standard'),

    ]

    BOOLEAN_CHOICES_WITH_NA = [
        ('N/A', 'N/A'),
        ('Yes', 'Yes'),
        ('No', 'No'),
    ]

    BOOLEAN_CHOICES = [
        ('Yes', 'Yes'),
        ('No', 'No')
    ]

    matter = models.ForeignKey(WIP, on_delete=models.SET_NULL, null=True)
    """ We already have some of these fields in Client and can add few others like dob, occupation
    client_name = models.CharField(max_length=255)
    client_address = models.TextField()
    client_date_of_birth = models.DateField()
    client_occupation = models.CharField(max_length=100)
    """
    client_source_of_funds = models.CharField(max_length=255)

    unusual_client = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES, default="No")
    client_concerns = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES, default="No")
    third_party_authority = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES_WITH_NA, default="N/A")
    concerns_about_parties = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES, default="No")
    designated_person_entity = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES, default="No")
    issues_identified_client_risks_sec = models.TextField()

    '''
    Try google auto address for client_location
    '''
    client_location = models.CharField(max_length=100)
    location_of_instruction_concerns = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES, default="No")
    make_sense_location_of_instructions = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES, default="No")
    # Are there overseas elements? If yes, provide details below e.g. overseas beneficiary, contracts for overseas entities
    overseas_elements = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES, default="No")
    issues_identified_jurisdiction_risks_sec = models.TextField()

    # Will we meet the client in person?
    meeting_in_person = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES, default="No")
    who_they_are = models.TextField()

    due_diligence_review = models.TextField()
    adverse_media = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES, default="No")

    # Please provide details of beneficial owners, shareholders/ controllers including percentages of shareholdings
    beneficial_owners_details = models.TextField()
    # Please provide details of steps taken to identify and verify ultimate beneficial owners
    ultimate_beneficial_owners = models.TextField()
    # Have you identified any reportable discrepancies?
    reportable_discrepancies = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES, default="No")

    # Matter risks
    """
    Do we usually carry out this type of work?                                                                                                       
    Does the matter involve creating a complex structure?                                   
    Does it involve a cash-intensive industry?                                                       
    Does it involve a high-risk industry?                                                                   
    Does the matter involve a risk of proliferation financing?
    Are there any there any other AML or Counter Terrorist Financing risks?       
    Is the matter transactional?                                                                                                                               
    If no, does the transaction arrange for the movement of funds or assets?      
    Are we receiving funds from overseas?                                                           
    Are we receiving funds from third parties?                                                          
    Is this transaction consistent with your understanding of the client’s profile and   
    financial position? e.g. it makes sense for the client to instruct us on this transaction?

    """
    matter_description = models.TextField()  # Description of work and transaction value
    matter_transaction_value = models.DecimalField(
        max_digits=15, decimal_places=2)
    usual_work = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES, default="No")
    complex_structure = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES, default="No")
    cash_intensive_industry = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES, default="No")
    high_risk_industry = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES, default="No")
    proliferation_financing = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES, default="No")
    other_risks = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES, default="No")
    transactional_matter = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES, default="No")
    movement_of_funds_assets = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES_WITH_NA, default="N/A")
    receiving_funds_from_overseas = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES, default="No")
    receiving_funds_from_third_parties = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES, default="No")
    consistent_with_client_profile = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES, default="No")
    issues_identified_matter_risks_sec = models.TextField()

    """Questionnaires
    Have you/Client completed and signed our PEP questionnaire?
    Have you/Client completed and signed our source of funds of questionnaire?
    """
    is_pep_questionnaire_completed = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES, default="No")
    is_source_of_funds_questionnaire_completed = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES, default="No")
    """
    Product/ service risk 
    Based on the client’s profile, does it make sense for the client to instruct us             
    on this transaction? 	Yes ☐      No ☐


    If no, please provide details

    """
    # Product/ service risk
    makes_sense_for_client = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES, default="No")
    product_service_risk_details = models.TextField()

    """
    Enhanced due diligence

    If the client is not an individual, is the structure complex or unusual?                         
    Does the client own, manage or direct a business or activity that falls within a higher risk sector?                                   
    Does the matter involve a client, a beneficial owner or other party linked to the Transaction, manage or direct a business or activity that is cash intensive?                                                       
    Does the matter involve a client, a beneficial owner or any party established in a high-risk third country or high-risk or jurisdiction?
    Is the client, a beneficial owner or any party linked to the transaction a politically exposed person (PEP), family member or a close associate of a PEP?
    Do you have any concerns that the client, a beneficial owner or any parties linked to the transaction is subject to financial sanctions or has links to a country subject to sanctions?
    Will this matter involve a country subject to sanctions?                                                  
    Is the transaction unusually complex or large?                                                                 
    Does this transaction form part of an unusual pattern of transactions?
    Does the transaction lack an apparent economic or legal purpose?                             
    Are there any other factors that could indicate a higher risk of money laundering or terrorist financing?
    """
    complex_structure_or_unusual = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES, default="No")
    higher_risk_sector = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES, default="No")
    cash_intensive_business_activity = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES, default="No")
    high_risk_third_country_or_jurisdiction = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES, default="No")
    politically_exposed_person = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES, default="No")
    financial_sanctions = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES, default="No")
    country_subject_to_sanctions = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES, default="No")
    unusual_complex_transaction = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES, default="No")
    unusual_pattern_of_transactions = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES, default="No")
    lack_of_economic_or_legal_purpose = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES, default="No")
    other_high_risk_factors = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES, default="No")
    escalated_date = models.DateField(null=True, blank=True)
    issues_identified_enhanced_due_dilligence = models.TextField()

    # Risk level and justification
    client_risk_level = models.CharField(
        max_length=10, choices=RISK_LEVEL_CHOICES, default='Low')
    matter_risk_level = models.CharField(
        max_length=10, choices=RISK_LEVEL_CHOICES, default='Low')

    evidence_of_source_of_wealth = models.BooleanField(
        default=False, null=True, blank=True)
    source_of_wealth_correspondence = models.BooleanField(
        default=False,  null=True, blank=True)

    # Due Diligence
    customer_due_diligence_level = models.CharField(
        max_length=10, choices=DUE_DILIGENCE_LEVEL_CHOICES, default="Standard")
    due_diligence_date = models.DateField()
    due_diligence_signed_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True)

    timestamp = models.DateTimeField(auto_now_add=True)


class OngoingMonitoring(models.Model):
    RISK_LEVEL_CHOICES = [
        ('Low', 'Low'),
        ('Medium', 'Medium'),
        ('High', 'High'),
    ]
    BOOLEAN_CHOICES = [
        ('Yes', 'Yes'),
        ('No', 'No')
    ]

    id = models.AutoField(primary_key=True)
    file_number = models.ForeignKey(WIP, on_delete=models.SET_NULL, null=True)
    how_was_monitioring_of_risks_coducted = models.TextField()
    any_changes_discovered = models.CharField(
        max_length=10, choices=BOOLEAN_CHOICES, default='Yes')
    details_of_changes = models.TextField(null=True, blank=True)

    updated_risk_level_matter = models.CharField(
        max_length=10, choices=RISK_LEVEL_CHOICES, default='Low')
    updated_risk_level_client = models.CharField(
        max_length=10, choices=RISK_LEVEL_CHOICES, default='Low')
    how_it_will_be_monitored = models.TextField()
    date_due_diligence_conducted = models.DateField()
    signed_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True)
    created_by = models.ForeignKey(
        CustomUser, related_name='created_by', on_delete=models.SET_NULL, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)


class MatterFileReview(models.Model):
    YES_NO_CHOICES = [
        ('Yes', 'Yes'),
        ('No', 'No'),
    ]

    matter = models.ForeignKey(
        WIP, on_delete=models.CASCADE, related_name='matter_file_reviews')
    client_matter_reference = models.CharField(
        max_length=255, null=True, blank=True)
    supervisor = models.CharField(max_length=255, null=True, blank=True)
    file_reviewed_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='matter_file_reviews_reviewed_by'
    )
    date_reviewed = models.DateField(null=True, blank=True)

    file_opening_checklist_completed = models.CharField(
        max_length=3, choices=YES_NO_CHOICES, null=True, blank=True)
    file_opening_checklist_completed_comments = models.TextField(
        null=True, blank=True)
    engagement_documents_sent_and_filed = models.CharField(
        max_length=3, choices=YES_NO_CHOICES, null=True, blank=True)
    engagement_documents_sent_and_filed_comments = models.TextField(
        null=True, blank=True)
    charging_rates_and_basis_provided = models.CharField(
        max_length=3, choices=YES_NO_CHOICES, null=True, blank=True)
    charging_rates_and_basis_provided_comments = models.TextField(
        null=True, blank=True)
    initial_costs_estimate_provided = models.CharField(
        max_length=3, choices=YES_NO_CHOICES, null=True, blank=True)
    initial_costs_estimate_provided_comments = models.TextField(
        null=True, blank=True)
    letter_of_authority_obtained = models.CharField(
        max_length=3, choices=YES_NO_CHOICES, null=True, blank=True)
    letter_of_authority_obtained_comments = models.TextField(
        null=True, blank=True)
    initial_risk_assessment_completed = models.CharField(
        max_length=3, choices=YES_NO_CHOICES, null=True, blank=True)
    initial_risk_assessment_completed_comments = models.TextField(
        null=True, blank=True)

    key_dates_recorded_in_calendar_and_wip = models.CharField(
        max_length=3, choices=YES_NO_CHOICES, null=True, blank=True)
    key_dates_recorded_in_calendar_and_wip_comments = models.TextField(
        null=True, blank=True)
    key_information_and_advice_shared = models.CharField(
        max_length=3, choices=YES_NO_CHOICES, null=True, blank=True)
    key_information_and_advice_shared_comments = models.TextField(
        null=True, blank=True)
    costs_estimates_updated = models.CharField(
        max_length=3, choices=YES_NO_CHOICES, null=True, blank=True)
    costs_estimates_updated_comments = models.TextField(
        null=True, blank=True)
    matter_progressing_without_dormancy = models.CharField(
        max_length=3, choices=YES_NO_CHOICES, null=True, blank=True)
    matter_progressing_without_dormancy_comments = models.TextField(
        null=True, blank=True)
    file_maintained_in_good_order = models.CharField(
        max_length=3, choices=YES_NO_CHOICES, null=True, blank=True)
    file_maintained_in_good_order_comments = models.TextField(
        null=True, blank=True)

    ongoing_aml_sanctions_monitoring_carried_out = models.CharField(
        max_length=3, choices=YES_NO_CHOICES, null=True, blank=True)
    ongoing_aml_sanctions_monitoring_carried_out_comments = models.TextField(
        null=True, blank=True)
    ongoing_monitoring_documents_kept_and_filed = models.CharField(
        max_length=3, choices=YES_NO_CHOICES, null=True, blank=True)
    ongoing_monitoring_documents_kept_and_filed_comments = models.TextField(
        null=True, blank=True)
    further_conflict_checks_completed = models.CharField(
        max_length=3, choices=YES_NO_CHOICES, null=True, blank=True)
    further_conflict_checks_completed_comments = models.TextField(
        null=True, blank=True)

    money_on_account_requested_and_received = models.CharField(
        max_length=3, choices=YES_NO_CHOICES, null=True, blank=True)
    money_on_account_requested_and_received_comments = models.TextField(
        null=True, blank=True)
    disbursements_paid_timely = models.CharField(
        max_length=3, choices=YES_NO_CHOICES, null=True, blank=True)
    disbursements_paid_timely_comments = models.TextField(
        null=True, blank=True)
    costs_and_disbursements_billed_timely = models.CharField(
        max_length=3, choices=YES_NO_CHOICES, null=True, blank=True)
    costs_and_disbursements_billed_timely_comments = models.TextField(
        null=True, blank=True)
    overdue_invoices = models.CharField(
        max_length=3, choices=YES_NO_CHOICES, null=True, blank=True)
    overdue_invoices_comments = models.TextField(null=True, blank=True)

    appropriate_advice_given = models.CharField(
        max_length=3, choices=YES_NO_CHOICES, null=True, blank=True)
    appropriate_advice_given_comments = models.TextField(
        null=True, blank=True)
    matter_within_client_care_scope = models.CharField(
        max_length=3, choices=YES_NO_CHOICES, null=True, blank=True)
    matter_within_client_care_scope_comments = models.TextField(
        null=True, blank=True)

    undertakings_discharged_or_released = models.CharField(
        max_length=3, choices=YES_NO_CHOICES, null=True, blank=True)
    undertakings_discharged_or_released_comments = models.TextField(
        null=True, blank=True)
    complaints_raised_and_process_followed = models.CharField(
        max_length=3, choices=YES_NO_CHOICES, null=True, blank=True)
    complaints_raised_and_process_followed_comments = models.TextField(
        null=True, blank=True)
    internal_concerns_raised = models.CharField(
        max_length=3, choices=YES_NO_CHOICES, null=True, blank=True)
    internal_concerns_raised_comments = models.TextField(
        null=True, blank=True)
    economic_crime_or_sanctions_concerns = models.CharField(
        max_length=3, choices=YES_NO_CHOICES, null=True, blank=True)
    economic_crime_or_sanctions_concerns_comments = models.TextField(
        null=True, blank=True)

    recommendations_and_further_actions = models.TextField(
        null=True, blank=True)
    additional_notes_or_comments = models.TextField(null=True, blank=True)
    file_review_completed_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='matter_file_reviews_completed_by'
    )
    date_review_completed = models.DateField(null=True, blank=True)

    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='matter_file_reviews_created_by'
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date_review_completed', '-date_reviewed', '-timestamp']

    def __str__(self):
        completed_on = self.date_review_completed or self.date_reviewed
        if completed_on:
            return f"{self.matter.file_number} review ({completed_on})"
        return f"{self.matter.file_number} review ({self.id})"


class MatterEmails(models.Model):
    id = models.AutoField(primary_key=True)
    file_number = models.ForeignKey(WIP, on_delete=models.SET_NULL, null=True)
    sender = models.JSONField(default=dict, null=True, blank=True)
    receiver = models.JSONField(default=dict, null=True, blank=True)
    body = models.TextField(null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    subject = models.TextField(null=True, blank=True)
    is_sent = models.BooleanField(null=True)
    time = models.DateTimeField(null=True, blank=True)
    fee_earner = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True)
    units = models.IntegerField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    link = models.URLField(max_length=4096, null=True, blank=True)

    def __str__(self):
        return (f'ID: {str(self.id)}, File Number: {self.file_number}')


class MatterLetters(models.Model):
    id = models.AutoField(primary_key=True)
    file_number = models.ForeignKey(WIP, on_delete=models.SET_NULL, null=True)
    date = models.DateField()
    to_or_from = models.CharField(max_length=255)
    sent = models.BooleanField(null=True, default=True)
    subject_line = models.CharField(max_length=255)
    person_attended = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True)
    is_charged = models.BooleanField(default=True, null=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, related_name='letter_created_by', null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)


class MatterAttendanceNotes(models.Model):
    id = models.AutoField(primary_key=True)
    file_number = models.ForeignKey(WIP, on_delete=models.SET_NULL, null=True)
    start_time = models.TimeField()
    finish_time = models.TimeField()
    subject_line = models.CharField(max_length=255)
    content = QuillField()
    is_charged = models.BooleanField(default=True)
    person_attended = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True)
    date = models.DateField()
    unit = models.IntegerField(default=1, null=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL,
                                   related_name='attendance_note_created_by', null=True, blank=True)

    timestamp = models.DateTimeField(auto_now_add=True)


class Policy(models.Model):
    id = models.AutoField(primary_key=True)
    description = models.TextField()

    def latest_version(self):
        return self.versions.order_by('-version_number').first()

    def __str__(self):
        return self.description


class PolicyVersion(models.Model):
    id = models.AutoField(primary_key=True)
    policy = models.ForeignKey(
        Policy, on_delete=models.CASCADE, related_name='versions')
    content = QuillField()
    version_number = models.PositiveIntegerField()
    changes_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('policy', 'version_number')

    def __str__(self):
        return f"Version {self.version_number} of {self.policy.description}"


class PoliciesRead(models.Model):
    id = models.AutoField(primary_key=True)
    policy = models.ForeignKey(
        Policy, on_delete=models.SET_NULL, null=True, blank=True, related_name='policies')
    policy_version = models.ForeignKey(
        PolicyVersion, on_delete=models.SET_NULL, null=True, blank=True, related_name='read_versions')
    read_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, related_name='read_by', null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.read_by} read {self.policy} (Version {self.policy_version.version_number})"


class Memo(models.Model):
    id = models.AutoField(primary_key=True)
    content = QuillField()
    date = models.DateField()
    is_final = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)


class MemoRead(models.Model):
    id = models.AutoField(primary_key=True)
    memo = models.ForeignKey(
        Memo, on_delete=models.SET_NULL, null=True, blank=True, related_name='memo')
    read_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL,
                                related_name='memo_read_by', null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.read_by} read memo dated {self.memo.date}"


class Undertaking(models.Model):
    id = models.AutoField(primary_key=True)
    file_number = models.ForeignKey(WIP, on_delete=models.SET_NULL, null=True)
    date_given = models.DateField()
    given_to = models.TextField()
    description = models.TextField()
    given_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL,
                                 related_name='undertaking_given_by', null=True, blank=True)
    document_given_on = models.FileField(
        upload_to=undertaking_file_upload_path)
    date_discharged = models.DateField(null=True, blank=True)
    discharged_proof = models.FileField(
        upload_to=undertaking_file_upload_path, null=True, blank=True)
    discharged_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL,
                                   related_name='undertaking_created_by', null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)


class Free30MinsAttendees(models.Model):
    name = models.CharField(max_length=255)
    address_line1 = models.CharField(max_length=255, null=True, blank=True)
    address_line2 = models.CharField(max_length=255, null=True, blank=True)
    county = models.CharField(max_length=255, null=True, blank=True)
    postcode = models.CharField(max_length=10, null=True, blank=True)
    email = models.CharField(max_length=50)
    contact_number = models.CharField(max_length=50)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL,
                                   related_name='free30_mins_attendees_created_by', null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)


class Free30Mins(models.Model):
    id = models.AutoField(primary_key=True)
    matter_type = models.ForeignKey(
        MatterType, on_delete=models.SET_NULL, null=True, blank=True)
    notes = QuillField()
    date = models.DateField()
    start_time = models.TimeField()
    finish_time = models.TimeField()
    attendees = models.ManyToManyField(Free30MinsAttendees)
    fee_earner = models.ForeignKey(CustomUser, on_delete=models.SET_NULL,
                                   related_name='free30_mins_fee_earner', null=True, blank=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL,
                                   related_name='free30_mins_created_by', null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(
                fields=['-date', '-start_time', '-id'],
                name='free30mins_latest_idx',
            ),
        ]


class Bundle(models.Model):
    """Model to represent a document bundle"""
    id = models.AutoField(primary_key=True)
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    name = models.CharField(max_length=255)
    file_number = models.ForeignKey(
        WIP, on_delete=models.CASCADE, null=True, blank=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    pdf_generated_at = models.DateTimeField(null=True, blank=True)
    final_pdf = models.FileField(
        upload_to=bundle_final_pdf_upload_path, max_length=255, null=True, blank=True)
    share_code = models.CharField(
        max_length=32, unique=True, db_index=True, null=True, blank=True)
    is_court_bundle = models.BooleanField(default=False)
    court_name = models.CharField(max_length=255, blank=True, default='')
    CASE_NUMBER_CLAIM = 'claim'
    CASE_NUMBER_CASE = 'case'
    CASE_NUMBER_TYPE_CHOICES = (
        (CASE_NUMBER_CLAIM, 'Claim No.'),
        (CASE_NUMBER_CASE, 'Case No.'),
    )
    case_number_type = models.CharField(
        max_length=8,
        choices=CASE_NUMBER_TYPE_CHOICES,
        default=CASE_NUMBER_CLAIM,
        blank=True,
    )
    case_number = models.CharField(max_length=64, blank=True, default='')
    index_title = models.CharField(
        max_length=255, blank=True, default='Index to the Bundle')
    hearing_line = models.CharField(max_length=255, blank=True, default='')
    conference_line = models.CharField(max_length=255, blank=True, default='')
    court_parties = models.JSONField(default=list, blank=True)
    share_link_url = models.URLField(max_length=512, blank=True, default='')
    share_link_permission_id = models.CharField(
        max_length=255, blank=True, default='')
    share_link_password = models.CharField(max_length=128, blank=True, default='')
    share_link_expires_at = models.DateTimeField(null=True, blank=True)
    share_link_created_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.name} - {self.file_number}"

    def save(self, *args, **kwargs):
        if not self.share_code:
            while True:
                share_code = secrets.token_urlsafe(12)
                if not Bundle.objects.filter(share_code=share_code).exists():
                    self.share_code = share_code
                    break
        super().save(*args, **kwargs)

    def pdf_is_current(self):
        if not self.final_pdf or not self.pdf_generated_at:
            return False
        return self.pdf_generated_at >= self.updated_at

    def court_parties_by_side(self):
        parties = self.court_parties if isinstance(self.court_parties, list) else []
        claimants = [party for party in parties if party.get('side') == 'claimant']
        defendants = [party for party in parties if party.get('side') == 'defendant']
        return claimants, defendants

    class Meta:
        ordering = ['-created_at']


class BundleShareLink(models.Model):
    """Microsoft sharing link created for a bundle final PDF."""
    bundle = models.ForeignKey(
        Bundle, on_delete=models.CASCADE, related_name='share_links')
    url = models.URLField(max_length=512)
    permission_id = models.CharField(max_length=255)
    password = models.CharField(max_length=128, blank=True, default='')
    use_password = models.BooleanField(default=False)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    def is_active(self):
        if self.revoked_at:
            return False
        if self.expires_at and self.expires_at <= timezone.now():
            return False
        return True

    def status_label(self):
        if self.revoked_at:
            return 'revoked'
        if self.expires_at and self.expires_at <= timezone.now():
            return 'expired'
        return 'active'

    class Meta:
        ordering = ['-created_at']


class BundleSection(models.Model):
    """Model to represent sections within a bundle"""
    DATE_SORT_MANUAL = 'manual'
    DATE_SORT_ASC = 'date_asc'
    DATE_SORT_DESC = 'date_desc'
    DATE_SORT_CHOICES = (
        (DATE_SORT_MANUAL, 'Manual order'),
        (DATE_SORT_ASC, 'Date (oldest first)'),
        (DATE_SORT_DESC, 'Date (newest first)'),
    )

    id = models.AutoField(primary_key=True)
    bundle = models.ForeignKey(
        Bundle, on_delete=models.CASCADE, related_name='sections')
    heading = models.CharField(max_length=255)
    order = models.PositiveIntegerField()
    date_sort = models.CharField(
        max_length=16,
        choices=DATE_SORT_CHOICES,
        default=DATE_SORT_ASC,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.bundle.name} - {self.heading}"

    def ordered_documents(self):
        documents = list(self.documents.all())
        if self.date_sort == self.DATE_SORT_MANUAL:
            return sorted(documents, key=lambda document: (document.order, document.id))

        dated_documents = [document for document in documents if document.date]
        undated_documents = [document for document in documents if not document.date]
        reverse = self.date_sort == self.DATE_SORT_DESC
        dated_documents.sort(
            key=lambda document: (document.date, document.order, document.id),
            reverse=reverse,
        )
        undated_documents.sort(key=lambda document: (document.order, document.id))
        return dated_documents + undated_documents

    class Meta:
        ordering = ['order']
        unique_together = ('bundle', 'order')


class BundleDocument(models.Model):
    """Model to represent documents within bundle sections"""
    id = models.AutoField(primary_key=True)
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    section = models.ForeignKey(
        BundleSection, on_delete=models.CASCADE, related_name='documents')
    file = models.FileField(upload_to=bundle_document_upload_path, max_length=255)
    description = models.CharField(max_length=500)
    date = models.DateField(null=True, blank=True)
    order = models.PositiveIntegerField()
    page_order = models.JSONField(null=True, blank=True)
    page_start = models.PositiveIntegerField(null=True, blank=True)
    page_end = models.PositiveIntegerField(null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.description} - {self.section.heading}"

    class Meta:
        ordering = ['order']
        unique_together = ('section', 'order')


DEFAULT_PREPARED_BY_ADDRESS = (
    'ANP Solicitors\n290 Kiln Road\nBenfleet\nEssex\nSS7 1QT'
)

DEFAULT_ACKNOWLEDGEMENT_TEXT = (
    '1. That we have examined and approved the Estate Account and Distribution '
    'Accounts submitted to us by ANP Solicitors of 290 Kiln Road, Benfleet, '
    'Essex, SS7 1QT;\n'
    '2. That we accept the sums in the Estate and Distribution Account have been '
    'distributed in accordance with the terms of the Will;\n'
    '3. All sums set out in the Estate and Distribution Account is full and final '
    'satisfaction of the beneficiaries entitlement;\n'
    '4. That such payment to each beneficiary will be a complete discharge of my '
    'duties as the Executor;\n'
    '5. To the best of my knowledge and ability, we have discharged our duties to '
    'the Estate and the Beneficiaries in full.'
)


class EstateAccount(models.Model):
    STATUS_INTERIM = 'interim'
    STATUS_FINALISED = 'finalised'
    STATUS_CHOICES = (
        (STATUS_INTERIM, 'Interim'),
        (STATUS_FINALISED, 'Finalised'),
    )

    id = models.AutoField(primary_key=True)
    matter = models.OneToOneField(
        WIP, on_delete=models.CASCADE, related_name='estate_account')
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_INTERIM)
    deceased_name = models.CharField(max_length=255, blank=True)
    date_of_death = models.DateField(null=True, blank=True)
    account_date = models.DateField(null=True, blank=True)
    prepared_by_name = models.CharField(
        max_length=255, default='ANP Solicitors')
    prepared_by_address = models.TextField(default=DEFAULT_PREPARED_BY_ADDRESS)
    inheritance_tax = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'))
    will_clause_text = models.TextField(blank=True)
    distribution_notes = models.TextField(blank=True)
    acknowledgement_text = models.TextField(default=DEFAULT_ACKNOWLEDGEMENT_TEXT)
    use_manual_totals = models.BooleanField(default=False)
    manual_gross_estate = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True)
    manual_total_debts = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True)
    manual_net_estate = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True)
    manual_balance_for_distribution = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True)
    finance_snapshot = models.JSONField(null=True, blank=True)
    finalised_at = models.DateTimeField(null=True, blank=True)
    finalised_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='estate_accounts_finalised')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Estate Account - {self.matter.file_number}'


class EstateAccountFinanceLineOverride(models.Model):
    SOURCE_SLIP = 'slip'
    SOURCE_GREEN_SLIP = 'green_slip'
    SOURCE_INVOICE = 'invoice'
    SOURCE_CREDIT_NOTE = 'credit_note'
    SOURCE_TYPE_CHOICES = (
        (SOURCE_SLIP, 'Payment slip'),
        (SOURCE_GREEN_SLIP, 'Green slip'),
        (SOURCE_INVOICE, 'Invoice'),
        (SOURCE_CREDIT_NOTE, 'Credit note'),
    )
    SECTION_ASSET = 'asset'
    SECTION_DEBT = 'debt'
    SECTION_DISTRIBUTION = 'distribution'
    SECTION_CHOICES = (
        (SECTION_ASSET, 'Asset'),
        (SECTION_DEBT, 'Debt'),
        (SECTION_DISTRIBUTION, 'Distribution'),
    )

    id = models.AutoField(primary_key=True)
    estate_account = models.ForeignKey(
        EstateAccount, on_delete=models.CASCADE, related_name='finance_overrides')
    source_type = models.CharField(max_length=16, choices=SOURCE_TYPE_CHOICES)
    source_id = models.PositiveIntegerField()
    is_excluded = models.BooleanField(default=False)
    date_override = models.DateField(null=True, blank=True)
    description_override = models.CharField(max_length=500, blank=True)
    amount_override = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True)
    section_override = models.CharField(
        max_length=12, choices=SECTION_CHOICES, null=True, blank=True)
    sort_order = models.IntegerField(default=0)

    class Meta:
        unique_together = ('estate_account', 'source_type', 'source_id')

    def __str__(self):
        return f'{self.source_type}:{self.source_id}'


class EstateAccountManualEntry(models.Model):
    SECTION_ASSET = 'asset'
    SECTION_DEBT = 'debt'
    SECTION_CHOICES = (
        (SECTION_ASSET, 'Asset'),
        (SECTION_DEBT, 'Debt'),
    )

    id = models.AutoField(primary_key=True)
    estate_account = models.ForeignKey(
        EstateAccount, on_delete=models.CASCADE, related_name='manual_entries')
    section = models.CharField(max_length=8, choices=SECTION_CHOICES)
    date = models.DateField(null=True, blank=True)
    description = models.CharField(max_length=500)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    is_pending = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sort_order', 'date', 'id']

    def __str__(self):
        return f'{self.section}: {self.description}'


class EstateAccountDistribution(models.Model):
    id = models.AutoField(primary_key=True)
    estate_account = models.ForeignKey(
        EstateAccount, on_delete=models.CASCADE, related_name='distributions')
    beneficiary_name = models.CharField(max_length=255)
    share_fraction = models.CharField(max_length=32, blank=True)
    gross_amount = models.DecimalField(max_digits=12, decimal_places=2)
    adjustment_description = models.CharField(max_length=255, blank=True)
    adjustment_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True)
    net_amount = models.DecimalField(max_digits=12, decimal_places=2)
    sort_order = models.IntegerField(default=0)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sort_order', 'id']

    def save(self, *args, **kwargs):
        adjustment = self.adjustment_amount or Decimal('0')
        self.net_amount = self.gross_amount - adjustment
        super().save(*args, **kwargs)

    def __str__(self):
        return self.beneficiary_name


class EstateAccountSigner(models.Model):
    id = models.AutoField(primary_key=True)
    estate_account = models.ForeignKey(
        EstateAccount, on_delete=models.CASCADE, related_name='signers')
    signer_name = models.CharField(max_length=255)
    signer_address = models.TextField(blank=True)
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']

    def __str__(self):
        return self.signer_name


class CompletionStatement(models.Model):
    STATUS_DRAFT = 'draft'
    STATUS_FINALISED = 'finalised'
    STATUS_CHOICES = (
        (STATUS_DRAFT, 'Draft'),
        (STATUS_FINALISED, 'Finalised'),
    )
    TRANSACTION_SALE = 'sale'
    TRANSACTION_PURCHASE = 'purchase'
    TRANSACTION_TYPE_CHOICES = (
        (TRANSACTION_SALE, 'Sale'),
        (TRANSACTION_PURCHASE, 'Purchase'),
    )

    id = models.AutoField(primary_key=True)
    matter = models.OneToOneField(
        WIP, on_delete=models.CASCADE, related_name='completion_statement')
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    transaction_type = models.CharField(
        max_length=16, choices=TRANSACTION_TYPE_CHOICES, default=TRANSACTION_SALE)
    completion_monies = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'))
    is_leasehold = models.BooleanField(default=False)
    property_address = models.TextField(blank=True)
    completion_date = models.DateField(null=True, blank=True)
    contract_date = models.DateField(null=True, blank=True)
    prepared_by_name = models.CharField(
        max_length=255, default='ANP Solicitors')
    prepared_by_address = models.TextField(default=DEFAULT_PREPARED_BY_ADDRESS)
    notes = models.TextField(blank=True)
    finance_snapshot = models.JSONField(null=True, blank=True)
    finalised_at = models.DateTimeField(null=True, blank=True)
    finalised_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='completion_statements_finalised')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Completion Statement - {self.matter.file_number}'


class CompletionStatementFinanceLineOverride(models.Model):
    SOURCE_SLIP = 'slip'
    SOURCE_GREEN_SLIP = 'green_slip'
    SOURCE_INVOICE = 'invoice'
    SOURCE_CREDIT_NOTE = 'credit_note'
    SOURCE_TYPE_CHOICES = (
        (SOURCE_SLIP, 'Payment slip'),
        (SOURCE_GREEN_SLIP, 'Green slip'),
        (SOURCE_INVOICE, 'Invoice'),
        (SOURCE_CREDIT_NOTE, 'Credit note'),
    )
    DIRECTION_ADD = 'add'
    DIRECTION_LESS = 'less'
    DIRECTION_CHOICES = (
        (DIRECTION_ADD, 'Add'),
        (DIRECTION_LESS, 'Less'),
    )

    id = models.AutoField(primary_key=True)
    completion_statement = models.ForeignKey(
        CompletionStatement, on_delete=models.CASCADE,
        related_name='finance_overrides')
    source_type = models.CharField(max_length=16, choices=SOURCE_TYPE_CHOICES)
    source_id = models.PositiveIntegerField()
    is_excluded = models.BooleanField(default=False)
    date_override = models.DateField(null=True, blank=True)
    description_override = models.CharField(max_length=500, blank=True)
    amount_override = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True)
    direction_override = models.CharField(
        max_length=8, choices=DIRECTION_CHOICES, null=True, blank=True)
    sort_order = models.IntegerField(default=0)

    class Meta:
        unique_together = ('completion_statement', 'source_type', 'source_id')

    def __str__(self):
        return f'{self.source_type}:{self.source_id}'


class CompletionStatementManualEntry(models.Model):
    DIRECTION_ADD = 'add'
    DIRECTION_LESS = 'less'
    DIRECTION_CHOICES = (
        (DIRECTION_ADD, 'Add'),
        (DIRECTION_LESS, 'Less'),
    )

    id = models.AutoField(primary_key=True)
    completion_statement = models.ForeignKey(
        CompletionStatement, on_delete=models.CASCADE,
        related_name='manual_entries')
    direction = models.CharField(max_length=8, choices=DIRECTION_CHOICES)
    date = models.DateField(null=True, blank=True)
    description = models.CharField(max_length=500)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    is_pending = models.BooleanField(default=True)
    is_system_managed = models.BooleanField(default=False)
    sort_order = models.IntegerField(default=0)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sort_order', 'date', 'id']

    def __str__(self):
        return f'{self.direction}: {self.description}'


class CompletionStatementMortgageRedemption(models.Model):
    id = models.AutoField(primary_key=True)
    completion_statement = models.OneToOneField(
        CompletionStatement, on_delete=models.CASCADE,
        related_name='mortgage_redemption')
    lender_name = models.CharField(max_length=255, blank=True)
    loan_account_ref = models.CharField(max_length=100, blank=True)
    redemption_figure = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'))
    redemption_statement_date = models.DateField(null=True, blank=True)
    daily_interest_amount = models.DecimalField(
        max_digits=12, decimal_places=4, default=Decimal('0.00'))
    completion_date = models.DateField(null=True, blank=True)
    calculated_days = models.PositiveIntegerField(default=0)
    calculated_interest = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'))
    linked_manual_entry = models.ForeignKey(
        CompletionStatementManualEntry, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='mortgage_redemption_link')

    def __str__(self):
        return f'Mortgage redemption - {self.lender_name or "Lender"}'


class CompletionStatementApportionment(models.Model):
    ITEM_RENT = 'rent'
    ITEM_SERVICE_CHARGE = 'service_charge'
    ITEM_GROUND_RENT = 'ground_rent'
    ITEM_INSURANCE = 'insurance'
    ITEM_OTHER = 'other'
    ITEM_TYPE_CHOICES = (
        (ITEM_RENT, 'Rent'),
        (ITEM_SERVICE_CHARGE, 'Service charge'),
        (ITEM_GROUND_RENT, 'Ground rent'),
        (ITEM_INSURANCE, 'Insurance'),
        (ITEM_OTHER, 'Other'),
    )
    DIRECTION_ADD = 'add'
    DIRECTION_LESS = 'less'
    DIRECTION_CHOICES = (
        (DIRECTION_ADD, 'Add'),
        (DIRECTION_LESS, 'Less'),
    )

    id = models.AutoField(primary_key=True)
    completion_statement = models.ForeignKey(
        CompletionStatement, on_delete=models.CASCADE,
        related_name='apportionments')
    item_type = models.CharField(
        max_length=32, choices=ITEM_TYPE_CHOICES, default=ITEM_OTHER)
    description = models.CharField(max_length=500)
    annual_amount = models.DecimalField(max_digits=12, decimal_places=2)
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    paid_in_advance = models.BooleanField(default=True)
    completion_date = models.DateField(null=True, blank=True)
    seller_days = models.PositiveIntegerField(default=0)
    buyer_days = models.PositiveIntegerField(default=0)
    calculated_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'))
    direction = models.CharField(max_length=8, choices=DIRECTION_CHOICES)
    sort_order = models.IntegerField(default=0)
    linked_manual_entry = models.ForeignKey(
        CompletionStatementManualEntry, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='apportionment_link')

    class Meta:
        ordering = ['sort_order', 'id']

    def __str__(self):
        return self.description


class CompletionStatementProceedsDistribution(models.Model):
    SHARE_FRACTION = 'fraction'
    SHARE_PERCENT = 'percent'
    SHARE_FIXED = 'fixed'
    SHARE_REMAINDER = 'remainder'
    SHARE_MODE_CHOICES = (
        (SHARE_FRACTION, 'Fraction'),
        (SHARE_PERCENT, 'Percent'),
        (SHARE_FIXED, 'Fixed amount'),
        (SHARE_REMAINDER, 'Remainder'),
    )

    id = models.AutoField(primary_key=True)
    completion_statement = models.ForeignKey(
        CompletionStatement, on_delete=models.CASCADE,
        related_name='proceeds_distributions')
    payee_name = models.CharField(max_length=255)
    reference = models.CharField(max_length=255, blank=True)
    share_mode = models.CharField(
        max_length=16, choices=SHARE_MODE_CHOICES, default=SHARE_FRACTION)
    share_value = models.CharField(max_length=32, blank=True)
    projected_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'))
    actual_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True)
    penny_adjustment = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'))
    linked_slip = models.ForeignKey(
        PmtsSlips, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='proceeds_distribution_links')
    linked_manual_entry = models.ForeignKey(
        CompletionStatementManualEntry, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='proceeds_distribution_link')
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']

    def __str__(self):
        return self.payee_name


class CompletionStatementScheduledPayment(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_SLIP_CREATED = 'slip_created'
    STATUS_COMPLETED = 'completed'
    STATUS_CHOICES = (
        (STATUS_PENDING, 'Pending'),
        (STATUS_SLIP_CREATED, 'Slip created'),
        (STATUS_COMPLETED, 'Completed'),
    )
    SOURCE_MANUAL = 'manual'
    SOURCE_MORTGAGE = 'mortgage'
    SOURCE_APPORTIONMENT = 'apportionment'
    SOURCE_DISTRIBUTION = 'distribution'
    SOURCE_MAIN_LINE = 'main_line'
    SOURCE_KIND_CHOICES = (
        (SOURCE_MANUAL, 'Manual'),
        (SOURCE_MORTGAGE, 'Mortgage redemption'),
        (SOURCE_APPORTIONMENT, 'Apportionment'),
        (SOURCE_DISTRIBUTION, 'Distribution'),
        (SOURCE_MAIN_LINE, 'Main line'),
    )
    LEDGER_CLIENT = 'C'
    LEDGER_OFFICE = 'O'
    LEDGER_ACCOUNT_CHOICES = (
        (LEDGER_CLIENT, 'Client account'),
        (LEDGER_OFFICE, 'Office account'),
    )
    DIRECTION_ADD = 'add'
    DIRECTION_LESS = 'less'
    DIRECTION_CHOICES = (
        (DIRECTION_ADD, 'Add'),
        (DIRECTION_LESS, 'Less'),
    )

    id = models.AutoField(primary_key=True)
    completion_statement = models.ForeignKey(
        CompletionStatement, on_delete=models.CASCADE,
        related_name='scheduled_payments')
    payee_name = models.CharField(max_length=255)
    description = models.CharField(max_length=500, blank=True)
    reference = models.CharField(max_length=255, blank=True)
    # Payee bank details — captured before a slip is created so the payment can
    # be made directly. Optional; carried onto the slip when one is created.
    bank_name = models.CharField(max_length=255, blank=True)
    bank_sort_code = models.CharField(max_length=20, blank=True)
    bank_account_number = models.CharField(max_length=30, blank=True)
    bank_account_name = models.CharField(max_length=255, blank=True)
    bank_reference = models.CharField(max_length=255, blank=True)
    direction = models.CharField(max_length=8, choices=DIRECTION_CHOICES)
    ledger_account = models.CharField(
        max_length=1, choices=LEDGER_ACCOUNT_CHOICES, default=LEDGER_CLIENT)
    projected_amount = models.DecimalField(max_digits=12, decimal_places=2)
    actual_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True)
    payment_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    linked_slip = models.ForeignKey(
        PmtsSlips, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='scheduled_payment_links')
    source_kind = models.CharField(
        max_length=16, choices=SOURCE_KIND_CHOICES, default=SOURCE_MANUAL)
    source_id = models.PositiveIntegerField(null=True, blank=True)
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']
        unique_together = ('completion_statement', 'source_kind', 'source_id')

    def __str__(self):
        return f'{self.payee_name} - {self.projected_amount}'


class GranolaConfig(models.Model):
    """Central, team-wide configuration for the Granola integration.

    A single row holds the shared API key and sync state. The API key can also
    be supplied via the ``GRANOLA_API_KEY`` environment variable / Django
    setting, which takes precedence over this row (see ``backend.granola``).
    """
    id = models.AutoField(primary_key=True)
    api_key = models.CharField(
        max_length=255, blank=True, default='',
        help_text='Central Granola API key (Settings → Connectors in Granola). '
                  'Leave blank to use the GRANOLA_API_KEY environment variable.')
    enabled = models.BooleanField(
        default=False, help_text='Master switch for the scheduled Granola sync.')
    start_date = models.DateField(
        null=True, blank=True,
        help_text='The scheduled sync stays dormant until this date (manual '
                  '"Sync now" still works). Leave blank to start immediately.')
    attendance_folder = models.CharField(
        max_length=255, blank=True, default='Attendance Note',
        help_text='Name of the shared Granola folder whose notes become matter '
                  'attendance notes.')
    free30_folder = models.CharField(
        max_length=255, blank=True, default='Free 30 min',
        help_text='Name of the shared Granola folder whose notes become Free '
                  '30 minute meeting records.')
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_full_scan_at = models.DateTimeField(
        null=True, blank=True,
        help_text='When the last complete folder re-scan ran (catches notes '
                  'added to a folder without bumping their updated_at).')
    last_sync_status = models.TextField(
        blank=True, default='', help_text='Outcome of the most recent sync run.')
    updated_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='granola_config_updated_by')
    timestamp = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Granola configuration'
        verbose_name_plural = 'Granola configuration'

    def __str__(self):
        return f'Granola config (enabled={self.enabled})'

    @classmethod
    def get_solo(cls):
        """Return the single config row, creating it on first access."""
        obj = cls.objects.first()
        if obj is None:
            obj = cls.objects.create()
        return obj


class GranolaImportedNote(models.Model):
    """Ledger of notes pulled from Granola.

    Doubles as the de-duplication table (one row per Granola note id) and the
    central review inbox: notes whose matter could not be auto-resolved sit in
    ``STATUS_PENDING`` until a back-office user assigns them to a matter.
    """
    STATUS_PENDING = 'pending'      # awaiting manual matter assignment
    STATUS_CREATED = 'created'      # attendance note created (auto or manual)
    STATUS_IGNORED = 'ignored'      # dismissed by a reviewer
    STATUS_ERROR = 'error'          # could not be processed
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending review'),
        (STATUS_CREATED, 'Record created'),
        (STATUS_IGNORED, 'Ignored'),
        (STATUS_ERROR, 'Error'),
    ]

    TYPE_ATTENDANCE = 'attendance'  # -> MatterAttendanceNotes
    TYPE_FREE30 = 'free30'          # -> Free30Mins
    TYPE_CHOICES = [
        (TYPE_ATTENDANCE, 'Attendance note'),
        (TYPE_FREE30, 'Free 30 minutes'),
    ]

    id = models.AutoField(primary_key=True)
    note_type = models.CharField(
        max_length=16, choices=TYPE_CHOICES, default=TYPE_ATTENDANCE)
    granola_note_id = models.CharField(max_length=255, unique=True)
    title = models.CharField(max_length=500, blank=True, default='')
    summary_md = models.TextField(
        blank=True, default='', help_text='Raw Markdown summary from Granola.')
    summary_html = models.TextField(
        blank=True, default='',
        help_text='Sanitised HTML rendered from the Markdown summary.')
    transcript = models.TextField(
        blank=True, default='', help_text='Plain-text transcript from Granola.')
    transcript_json = models.JSONField(
        null=True, blank=True,
        help_text='Structured per-utterance transcript as returned by Granola.')
    meeting_start = models.DateTimeField(null=True, blank=True)
    meeting_end = models.DateTimeField(null=True, blank=True)
    note_created_at = models.DateTimeField(null=True, blank=True)
    owner_email = models.EmailField(
        blank=True, default='', help_text='Email of the Granola note owner.')

    parsed_file_number = models.CharField(max_length=20, blank=True, default='')
    parsed_is_charged = models.BooleanField(default=True)
    matched_file = models.ForeignKey(
        WIP, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='granola_notes')
    matched_fee_earner = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='granola_notes')

    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    error_message = models.TextField(blank=True, default='')
    attendance_note = models.OneToOneField(
        MatterAttendanceNotes, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='granola_source')
    free30_meeting = models.OneToOneField(
        Free30Mins, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='granola_source')

    reviewed_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='granola_notes_reviewed')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-meeting_start', '-timestamp']

    def __str__(self):
        return f'{self.title or self.granola_note_id} ({self.status})'


class OnboardingGroup(models.Model):
    """A pre-matter onboarding case for a future matter. A matter can have more
    than one client, so several people (the members below) are onboarded
    together under one group — each with their own upload link — and the whole
    group is converted into a single matter (WIP) with one lead client and the
    rest as additional clients."""

    STATUS_COLLECTING = 'collecting'
    STATUS_READY = 'ready_for_review'
    STATUS_CONVERTED = 'converted'
    STATUS_CHOICES = [
        (STATUS_COLLECTING, 'Collecting'),
        (STATUS_READY, 'Ready for review'),
        (STATUS_CONVERTED, 'Converted'),
    ]

    id = models.AutoField(primary_key=True)
    label = models.CharField(max_length=255, blank=True, default='')
    matter_description = models.CharField(max_length=500, blank=True, default='')
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_COLLECTING)
    matter = models.ForeignKey(
        'WIP', on_delete=models.SET_NULL, related_name='onboarding_groups', null=True, blank=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, related_name='onboarding_groups_created', null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return self.label or f'Onboarding group {self.id}'


class Onboarding(models.Model):
    """One person within an onboarding group. The office is the system of record;
    it owns the client_ref that the external client portal keys every upload on.
    Once the person's documents are collected and KYC-accepted, the group they
    belong to is converted into a matter (WIP)."""

    STATUS_INVITED = 'invited'
    STATUS_COLLECTING = 'collecting'
    STATUS_READY = 'ready_for_review'
    STATUS_CONVERTED = 'converted'
    STATUS_CHOICES = [
        (STATUS_INVITED, 'Invited'),
        (STATUS_COLLECTING, 'Collecting'),
        (STATUS_READY, 'Ready for review'),
        (STATUS_CONVERTED, 'Converted'),
    ]

    id = models.AutoField(primary_key=True)
    client_ref = models.CharField(max_length=20, unique=True, editable=False)
    client_name = models.CharField(max_length=255)
    email = models.CharField(max_length=255)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_INVITED)
    portal_submission_id = models.CharField(max_length=64, blank=True, default='')
    portal_invite_id = models.CharField(max_length=64, blank=True, default='')
    portal_invite_link = models.CharField(max_length=512, blank=True, default='')
    invite_sent_at = models.DateTimeField(null=True, blank=True)
    invite_expired_at = models.DateTimeField(null=True, blank=True)

    # The documents/declarations this member is asked to provide for this matter
    # (a subset of OnboardingItem.ITEM_CHOICES keys). Chosen when the invite is
    # sent — e.g. an existing client who only needs fresh source-of-funds/PEP/
    # terms can have proof-of-id/address dropped. Empty == ask for everything.
    required_documents = models.JSONField(default=list, blank=True)

    # Each onboarding row is one person. People who will share a matter are
    # grouped under one OnboardingGroup; is_lead marks the one who becomes the
    # matter's primary client (client1).
    group = models.ForeignKey(
        'OnboardingGroup', on_delete=models.CASCADE, related_name='members',
        null=True, blank=True)
    is_lead = models.BooleanField(default=False)

    # Structured contact details for this person. Captured at convert time (and,
    # once the portal is live, pre-filled by it) and copied onto the resulting
    # ClientContactDetails — proof-of-address is only an image, so the typed
    # address lives here.
    dob = models.DateField(null=True, blank=True)
    occupation = models.CharField(max_length=255, blank=True, default='')
    address_line1 = models.CharField(max_length=255, blank=True, default='')
    address_line2 = models.CharField(max_length=255, blank=True, default='')
    county = models.CharField(max_length=255, blank=True, default='')
    postcode = models.CharField(max_length=10, blank=True, default='')
    contact_number = models.CharField(max_length=50, blank=True, default='')

    # The ClientContactDetails created from this member at convert time. Set once
    # so converting is idempotent (a retry reuses the same client record) and so
    # the new-matter form can pre-select it.
    client = models.ForeignKey(
        'ClientContactDetails', on_delete=models.SET_NULL,
        related_name='onboarding_member', null=True, blank=True)

    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, related_name='onboarding_created_by', null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def required_item_types(self):
        """The item_type keys this member must provide. Falls back to every
        document type when nothing has been chosen yet, so existing rows (and
        members invited before a selection is made) behave as 'ask for all'."""
        if self.required_documents:
            return [k for k in self.required_documents
                    if k in dict(OnboardingItem.ITEM_CHOICES)]
        return [key for key, _ in OnboardingItem.ITEM_CHOICES]

    @staticmethod
    def generate_client_ref():
        return f'ONB-{secrets.token_hex(4).upper()}'

    def save(self, *args, **kwargs):
        if not self.client_ref:
            ref = self.generate_client_ref()
            while Onboarding.objects.filter(client_ref=ref).exists():
                ref = self.generate_client_ref()
            self.client_ref = ref
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.client_name} ({self.client_ref})'


def onboarding_doc_storage():
    """Private, auth-served storage for onboarding documents (passports, selfies,
    declarations). Kept off the public media URL — files are only ever served
    through the login-protected preview view. Local disk for now; route to a
    SharePoint client-documents library when the portal goes live."""
    return FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, 'onboarding_docs'))


def onboarding_document_upload_path(instance, filename):
    from backend.sharepoint.paths import sanitize_filename
    ref = instance.onboarding.client_ref if instance.onboarding_id else 'unassigned'
    return f'{ref}/{instance.item_type}-{uuid.uuid4()}_{sanitize_filename(filename)}'


class OnboardingItem(models.Model):
    """Per-document state for an onboarding case: the durable SharePoint item id of
    the client's portal upload and, when staff upload a document on the client's
    behalf, the office-copy file. A document counts as collected once it is
    provided (a portal upload or an office copy) — there is no separate acceptance
    step. The portal owns the client-uploaded copies (fetched live / by id)."""

    ITEM_CHOICES = [
        ('proof_id', 'Proof of ID'),
        ('proof_address', 'Proof of address'),
        ('selfie_id', 'Selfie with ID'),
        ('source_of_funds', 'Source of funds declaration'),
        ('pep', 'PEP declaration'),
        ('terms_of_engagement', 'Terms of engagement'),
    ]

    id = models.AutoField(primary_key=True)
    onboarding = models.ForeignKey(
        Onboarding, on_delete=models.CASCADE, related_name='items')
    item_type = models.CharField(max_length=20, choices=ITEM_CHOICES)
    sharepoint_item_id = models.CharField(max_length=128, blank=True, default='')
    # Set when a staff member uploads the document on the client's behalf.
    file = models.FileField(
        upload_to=onboarding_document_upload_path,
        storage=onboarding_doc_storage, null=True, blank=True)
    # Document metadata captured during onboarding for identity documents (proof of
    # ID/address), copied onto the client's ClientKeyDocument at convert time so the
    # record is complete (with an expiry to track) rather than skeletal.
    document_type = models.CharField(max_length=100, blank=True, default='')
    document_reference = models.CharField(max_length=100, blank=True, default='')
    issue_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)

    class Meta:
        unique_together = ('onboarding', 'item_type')

    def __str__(self):
        return f'{self.onboarding.client_ref} - {self.get_item_type_display()}'


# ---------------------------------------------------------------------------
# Per-matter-per-client compliance. Engagement-level checks (terms of
# engagement, NCBA, source of funds, PEP) belong to each matter x client pairing
# and are collected fresh for every file. Identity (proof of ID/address, AML
# date) stays on ClientContactDetails and is reused across matters.
# ---------------------------------------------------------------------------


def matter_client_doc_storage():
    """Private, auth-served storage for per-matter client-care documents (signed
    terms, source-of-funds evidence, PEP forms, AML/ID checks). Served only
    through the login-protected preview view, never a public URL."""
    return FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, 'matter_client_docs'))


def matter_client_document_upload_path(instance, filename):
    from backend.sharepoint.paths import sanitize_filename
    mc = instance.matter_client
    ref = mc.matter.file_number if mc.matter_id else 'unassigned'
    return f'{ref}/{mc.client_id}/{instance.category}-{uuid.uuid4()}_{sanitize_filename(filename)}'


class MatterClient(models.Model):
    """One client's engagement-level compliance on one matter. Created for every
    client on a matter (lead + additional). Holds the checks redone for each new
    file — terms of engagement, NCBA (when the matter is under one), source of
    funds and PEP — with the sent/received dates that used to live matter-wide on
    WIP."""

    SOURCE_CAPTURED = 'captured'
    SOURCE_RECONSTRUCTED = 'reconstructed'
    SOURCE_CARRIED_OVER = 'carried_over'
    SOURCE_CHOICES = [
        (SOURCE_CAPTURED, 'Captured for this matter'),
        (SOURCE_RECONSTRUCTED, 'Reconstructed from matter evidence'),
        (SOURCE_CARRIED_OVER, 'Carried over from the client record'),
    ]

    matter = models.ForeignKey(
        WIP, on_delete=models.CASCADE, related_name='matter_clients')
    client = models.ForeignKey(
        ClientContactDetails, on_delete=models.CASCADE, related_name='matter_links')
    is_lead = models.BooleanField(default=False)

    # Terms of engagement
    terms_of_engagement_signed = models.BooleanField(default=False)
    terms_of_engagement_on = models.DateField(null=True, blank=True)
    terms_of_engagement_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    terms_sent_on = models.DateField(null=True, blank=True)
    terms_received_on = models.DateField(null=True, blank=True)

    # NCBA — only shown/required when the matter is under one (WIP.ncba_required)
    ncba_signed = models.BooleanField(default=False)
    ncba_on = models.DateField(null=True, blank=True)
    ncba_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    ncba_sent_on = models.DateField(null=True, blank=True)
    ncba_received_on = models.DateField(null=True, blank=True)

    # Source of funds
    source_of_funds_signed = models.BooleanField(default=False)
    source_of_funds_on = models.DateField(null=True, blank=True)
    source_of_funds_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    source_of_funds_details = models.CharField(max_length=255, blank=True, default='')

    # PEP declaration
    pep_signed = models.BooleanField(default=False)
    pep_on = models.DateField(null=True, blank=True)
    pep_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    source = models.CharField(
        max_length=20, choices=SOURCE_CHOICES, default=SOURCE_CAPTURED)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('matter', 'client')

    def __str__(self):
        return f'{self.matter.file_number} - {self.client.name}'


class MatterClientDocument(models.Model):
    """A client-care document uploaded against a matter x client — signed terms,
    source-of-funds evidence, a PEP form, or an AML/ID check captured after the
    file is open. Files are private, served only through a login-protected view."""

    CATEGORY_CHOICES = [
        ('terms', 'Terms of engagement'),
        ('ncba', 'NCBA'),
        ('source_of_funds', 'Source of funds'),
        ('pep', 'PEP declaration'),
        ('aml_id_check', 'AML / ID check'),
        ('other', 'Other'),
    ]

    matter_client = models.ForeignKey(
        MatterClient, on_delete=models.CASCADE, related_name='documents')
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    file = models.FileField(
        upload_to=matter_client_document_upload_path,
        storage=matter_client_doc_storage)
    document_type = models.CharField(max_length=100, blank=True, default='')
    document_reference = models.CharField(max_length=100, blank=True, default='')
    issue_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    uploaded_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.matter_client} - {self.get_category_display()}'


class ConveyancingDetails(models.Model):
    """Transaction detail for a conveyancing matter — the property and its
    purchase/sale price. Kept off WIP so type-specific fields don't bloat every
    matter; shown only when the matter type is conveyancing."""

    TRANSACTION_CHOICES = [
        ('purchase', 'Purchase'),
        ('sale', 'Sale'),
        ('purchase_sale', 'Purchase & sale'),
        ('remortgage', 'Remortgage'),
        ('transfer', 'Transfer of equity'),
    ]

    matter = models.OneToOneField(
        WIP, on_delete=models.CASCADE, related_name='conveyancing')
    transaction_type = models.CharField(
        max_length=20, choices=TRANSACTION_CHOICES, blank=True, default='')
    property_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True)
    property_address = models.CharField(max_length=500, blank=True, default='')
    completion_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.matter.file_number} conveyancing'
