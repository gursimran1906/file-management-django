from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from users.models import CustomUser
from django_quill.fields import QuillField
from math import ceil
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType

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


class ClientContactDetails(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255)
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
    timestamp = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, related_name='client_created_by', null=True, blank=True)

    def __str__(self):
        return f'{self.name}'


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
    date_of_id_check = models.DateField(null=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, related_name='ap_created_by', null=True, blank=True)

    def __str__(self):
        return f'ID: {self.id}, Name: {self.name}'


class OthersideDetails(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255, null=True, blank=True)
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

    client1 = models.ForeignKey(ClientContactDetails, on_delete=models.SET(
        get_sentinel_user), related_name='client1_wip', )
    client2 = models.ForeignKey(ClientContactDetails, on_delete=models.SET(
        get_sentinel_user), related_name='client2_wip', null=True, blank=True)

    matter_type = models.ForeignKey(
        MatterType, on_delete=models.SET_NULL, related_name='matter_type', null=True)
    file_status = models.ForeignKey(
        FileStatus, on_delete=models.SET_NULL, related_name='file_status', null=True)
    file_location = models.ForeignKey(
        FileLocation, on_delete=models.SET_NULL, related_name='file_location', null=True)

    other_side = models.ForeignKey(
        OthersideDetails, on_delete=models.SET_NULL, null=True, blank=True)
    date_of_client_care_sent = models.DateField(null=True, blank=True)
    terms_of_engagement_client1 = models.BooleanField(null=True, blank=True)
    terms_of_engagement_client2 = models.BooleanField(null=True, blank=True)
    date_of_toe_sent = models.DateField(null=True, blank=True)
    date_of_toe_rcvd = models.DateField(null=True, blank=True)
    ncba_client1 = models.BooleanField(null=True, blank=True)
    ncba_client2 = models.BooleanField(null=True, blank=True)
    date_of_ncba_sent = models.DateField(null=True, blank=True)
    date_of_ncba_rcvd = models.DateField(null=True, blank=True)
    
    funding = models.CharField(max_length=3)
    authorised_party1 = models.ForeignKey(
        AuthorisedParties, on_delete=models.SET_NULL, related_name='auth_party1_wip', null=True, blank=True)
    authorised_party2 = models.ForeignKey(
        AuthorisedParties, on_delete=models.SET_NULL, related_name='auth_party2_wip', null=True, blank=True)

    key_information = models.TextField(null=True, blank=True)
    undertakings = models.JSONField(null=True, blank=True)
    comments = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, related_name='wip_created_by', null=True, blank=True)

    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.file_number


class NextWork(models.Model):
    id = models.AutoField(primary_key=True)
    file_number = models.ForeignKey(WIP, on_delete=models.SET_NULL, null=True)
    person = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True)
    task = models.TextField(null=True, blank=True)
    date = models.DateField(null=True, blank=True)
    completed = models.BooleanField(default=False, null=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL,
                                   related_name='next_work_created_by', null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.completed:
            LastWork.objects.create(
                file_number=self.file_number,
                person=self.person,
                task=self.task,
                date=self.date
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
    id = models.AutoField(primary_key=True)
    invoice_number = models.IntegerField(null=True, blank=True)
    state = models.CharField(max_length=1, choices=STATES)
    file_number = models.ForeignKey(WIP, on_delete=models.SET_NULL, null=True)
    date = models.DateField()
    payable_by = models.CharField(default='Client', max_length=255)
    by_email = models.BooleanField(null=True, blank=True)
    by_post = models.BooleanField(null=True, blank=True)
    description = models.TextField()
    our_costs_desc = models.JSONField(default=dict)
    our_costs = models.JSONField(default=dict)
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

class RiskAssessment(models.Model):
    RISK_LEVEL_CHOICES = [
        ('Low', 'Low'),
        ('Medium', 'Medium'),
        ('High', 'High'),
    ]

    DUE_DILIGENCE_LEVEL_CHOICES = [
        ('Enhanced','Enhanced'),
        ('Standard','Standard'),
  
    ]

    BOOLEAN_CHOICES_WITH_NA = [
        ('N/A','N/A'),
        ('Yes', 'Yes'),
        ('No', 'No'),   
    ]

    BOOLEAN_CHOICES = [
        ('Yes', 'Yes'),
        ('No', 'No')  
    ]
    
    matter = models.ForeignKey(WIP,on_delete=models.SET_NULL, null=True)
    """ We already have some of these fields in Client and can add few others like dob, occupation
    client_name = models.CharField(max_length=255)
    client_address = models.TextField()
    client_date_of_birth = models.DateField()
    client_occupation = models.CharField(max_length=100)
    """
    client_source_of_funds = models.CharField(max_length=255)
    
    
    unusual_client = models.CharField(max_length=10, choices=BOOLEAN_CHOICES, default="No")
    client_concerns = models.CharField(max_length=10, choices=BOOLEAN_CHOICES, default="No")
    third_party_authority = models.CharField(max_length=10, choices=BOOLEAN_CHOICES_WITH_NA, default="N/A")
    concerns_about_parties = models.CharField(max_length=10, choices=BOOLEAN_CHOICES, default="No")
    designated_person_entity = models.CharField(max_length=10, choices=BOOLEAN_CHOICES, default="No")
    issues_identified_client_risks_sec = models.TextField()

    '''
    Try google auto address for client_location
    '''
    client_location = models.CharField(max_length=100) 
    location_of_instruction_concerns = models.CharField(max_length=10, choices=BOOLEAN_CHOICES, default="No")
    make_sense_location_of_instructions = models.CharField(max_length=10, choices=BOOLEAN_CHOICES, default="No")
    overseas_elements = models.CharField(max_length=10, choices=BOOLEAN_CHOICES, default="No") # Are there overseas elements? If yes, provide details below e.g. overseas beneficiary, contracts for overseas entities
    issues_identified_jurisdiction_risks_sec = models.TextField()
    
    meeting_in_person = models.CharField(max_length=10, choices=BOOLEAN_CHOICES, default="No") # Will we meet the client in person?  
    who_they_are = models.TextField()

    due_diligence_review = models.TextField()
    adverse_media = models.CharField(max_length=10, choices=BOOLEAN_CHOICES, default="No")

    beneficial_owners_details = models.TextField()#Please provide details of beneficial owners, shareholders/ controllers including percentages of shareholdings
    ultimate_beneficial_owners = models.TextField()#Please provide details of steps taken to identify and verify ultimate beneficial owners
    reportable_discrepancies = models.CharField(max_length=10, choices=BOOLEAN_CHOICES, default="No")#Have you identified any reportable discrepancies?

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
    matter_description = models.TextField() #Description of work and transaction value
    matter_transaction_value = models.DecimalField(max_digits=15, decimal_places=2) 
    usual_work = models.CharField(max_length=10, choices=BOOLEAN_CHOICES, default="No")
    complex_structure = models.CharField(max_length=10, choices=BOOLEAN_CHOICES, default="No")
    cash_intensive_industry = models.CharField(max_length=10, choices=BOOLEAN_CHOICES, default="No")
    high_risk_industry = models.CharField(max_length=10, choices=BOOLEAN_CHOICES, default="No")
    proliferation_financing = models.CharField(max_length=10, choices=BOOLEAN_CHOICES, default="No")
    other_risks = models.CharField(max_length=10, choices=BOOLEAN_CHOICES, default="No")
    transactional_matter = models.CharField(max_length=10, choices=BOOLEAN_CHOICES, default="No")
    movement_of_funds_assets = models.CharField(max_length=10, choices=BOOLEAN_CHOICES_WITH_NA, default="N/A")
    receiving_funds_from_overseas = models.CharField(max_length=10, choices=BOOLEAN_CHOICES, default="No")
    receiving_funds_from_third_parties = models.CharField(max_length=10, choices=BOOLEAN_CHOICES, default="No")
    consistent_with_client_profile = models.CharField(max_length=10, choices=BOOLEAN_CHOICES, default="No")
    issues_identified_matter_risks_sec = models.TextField()


    """Questionnaires
    Have you/Client completed and signed our PEP questionnaire?
    Have you/Client completed and signed our source of funds of questionnaire?
    """
    is_pep_questionnaire_completed = models.CharField(max_length=10, choices=BOOLEAN_CHOICES, default="No")
    is_source_of_funds_questionnaire_completed = models.CharField(max_length=10, choices=BOOLEAN_CHOICES, default="No")
    """
    Product/ service risk 
    Based on the client’s profile, does it make sense for the client to instruct us             
    on this transaction? 	Yes ☐      No ☐


    If no, please provide details

    """
    # Product/ service risk
    makes_sense_for_client = models.CharField(max_length=10, choices=BOOLEAN_CHOICES, default="No")
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
    complex_structure_or_unusual = models.CharField(max_length=10, choices=BOOLEAN_CHOICES, default="No")
    higher_risk_sector = models.CharField(max_length=10, choices=BOOLEAN_CHOICES, default="No")
    cash_intensive_business_activity = models.CharField(max_length=10, choices=BOOLEAN_CHOICES, default="No")
    high_risk_third_country_or_jurisdiction = models.CharField(max_length=10, choices=BOOLEAN_CHOICES, default="No")
    politically_exposed_person = models.CharField(max_length=10, choices=BOOLEAN_CHOICES, default="No")
    financial_sanctions = models.CharField(max_length=10, choices=BOOLEAN_CHOICES, default="No")
    country_subject_to_sanctions = models.CharField(max_length=10, choices=BOOLEAN_CHOICES, default="No")
    unusual_complex_transaction = models.CharField(max_length=10, choices=BOOLEAN_CHOICES, default="No")
    unusual_pattern_of_transactions = models.CharField(max_length=10, choices=BOOLEAN_CHOICES, default="No")
    lack_of_economic_or_legal_purpose = models.CharField(max_length=10, choices=BOOLEAN_CHOICES, default="No")
    other_high_risk_factors = models.CharField(max_length=10, choices=BOOLEAN_CHOICES, default="No")
    escalated_date = models.DateField(null=True, blank=True)
    issues_identified_enhanced_due_dilligence = models.TextField()

    # Risk level and justification
    client_risk_level = models.CharField(max_length=10, choices=RISK_LEVEL_CHOICES, default='Low')
    matter_risk_level = models.CharField(max_length=10, choices=RISK_LEVEL_CHOICES, default='Low')


    evidence_of_source_of_wealth = models.BooleanField(default=False, null=True, blank=True)
    source_of_wealth_correspondence = models.BooleanField(default=False,  null=True, blank=True)

    # Due Diligence
    customer_due_diligence_level = models.CharField(max_length=10, choices=DUE_DILIGENCE_LEVEL_CHOICES, default="Standard")
    due_diligence_date = models.DateField()
    due_diligence_signed_by = models.ForeignKey(CustomUser,on_delete=models.SET_NULL, null=True)

    timestamp=models.DateTimeField(auto_now_add=True)
    
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
    any_changes_discovered = models.CharField(max_length=10, choices=BOOLEAN_CHOICES, default='Yes')
    details_of_changes = models.TextField(null=True, blank=True)

    updated_risk_level_matter = models.CharField(max_length=10, choices=RISK_LEVEL_CHOICES, default='Low')
    updated_risk_level_client = models.CharField(max_length=10, choices=RISK_LEVEL_CHOICES, default='Low')
    how_it_will_be_monitored = models.TextField()
    date_due_diligence_conducted = models.DateField()
    signed_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    created_by = models.ForeignKey(CustomUser,related_name='created_by', on_delete=models.SET_NULL, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)

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
    is_charged = models.BooleanField(null=True, default=True)
    person_attended = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True)
    date = models.DateField()
    unit = models.IntegerField(default=1, null=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL,
                                   related_name='attendance_note_created_by', null=True, blank=True)

    timestamp = models.DateTimeField(auto_now_add=True)


class PoliciesRead(models.Model):
    id = models.AutoField(primary_key=True)
    policy_number = models.IntegerField()
    read_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL,
                                   related_name='read_by', null=True, blank=True)

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
    matter_type = models.ForeignKey(MatterType, on_delete=models.SET_NULL, null=True, blank=True)
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
