import os
from django import forms
from .models import *
from django.forms import formset_factory, inlineformset_factory
from datetime import date
from math import ceil
from django.utils import timezone
from django.core.validators import RegexValidator
from django.utils.safestring import mark_safe
from django.utils.html import format_html, format_html_join
from django_quill.forms import QuillFormField
from types import SimpleNamespace
from .risk_scoring import score_risk_assessment

class ArchiveDetailsForm(forms.ModelForm):
    """Retention and physical-file facts recorded once a matter is archived."""

    class Meta:
        model = WIP
        fields = ['earliest_destruction_date', 'actual_destruction_date', 'brought_down_on']
        labels = {
            'earliest_destruction_date': 'Earliest destruction date',
            'actual_destruction_date': 'Actual destruction date',
            'brought_down_on': 'Physical file brought down on',
        }
        widgets = {name: forms.DateInput(attrs={'type': 'date', 'class': 'form-input'})
                   for name in fields}


class OpenFileForm(forms.ModelForm):
    # Fields a matter can't be opened without. Enforced when a file is first
    # opened (the last step of onboarding) via require_critical=True; the edit
    # page keeps the model's own rules so older records with gaps still save.
    CRITICAL_FIELDS = (
        'file_number', 'fee_earner', 'matter_type', 'funding',
        'matter_description', 'client1',
    )

    class Meta:
        model = WIP
        # additional_clients is handled manually in the view (custom add-client
        # UI); the archive / retention dates have their own form on the matter
        # home. Keep them all off this ModelForm so a save never blanks them.
        exclude = [
            'additional_clients',
            *ArchiveDetailsForm.Meta.fields,
        ]

    undertakings = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}), required=False)

    def __init__(self, *args, require_critical=False, **kwargs):
        super().__init__(*args, **kwargs)
        if require_critical:
            for name in self.CRITICAL_FIELDS:
                self.fields[name].required = True

class NextWorkFormWithoutFileNumber(forms.ModelForm):
    class Meta:
        model = NextWork
        fields = ['person', 'task', 'date', 'status', 'urgency']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super(NextWorkFormWithoutFileNumber, self).__init__(*args, **kwargs)
        self.fields['date'].initial = timezone.localdate()
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-input'
        self.fields['task'].widget.attrs['rows'] = '2'
        self.fields['task'].widget.attrs['class'] = 'h-16 shadow-sm mb-2 mt-1 border border-gray-300 text-gray-900 text-sm rounded focus:ring-blue-100 focus:border-blue-100 block w-full p-2 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white dark:focus:ring-blue-500 dark:focus:border-blue-500'

class NextWorkForm(forms.ModelForm):
    class Meta:
        model = NextWork
        fields = '__all__'
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super(NextWorkForm, self).__init__(*args, **kwargs)
        self.fields['date'].initial = timezone.localdate()
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'shadow-sm mb-1 mt-1 border border-gray-300 text-gray-900 text-sm rounded focus:ring-blue-100 focus:border-blue-100 block w-full p-2 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white dark:focus:ring-blue-500 dark:focus:border-blue-500'
        self.fields['task'].widget.attrs['rows'] = '2'
        self.fields['task'].widget.attrs['class'] = 'h-16 shadow-sm mb-2 mt-1 border border-gray-300 text-gray-900 text-sm rounded focus:ring-blue-100 focus:border-blue-100 block w-full p-2 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white dark:focus:ring-blue-500 dark:focus:border-blue-500'

class LastWorkFormWithoutFileNumber(forms.ModelForm):
    class Meta:
        model = LastWork
        fields = ['person', 'task', 'date']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super(LastWorkFormWithoutFileNumber, self).__init__(*args, **kwargs)
        self.fields['date'].initial = timezone.localdate()
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-input'
        self.fields['task'].widget.attrs['rows'] = '2'
        self.fields['task'].widget.attrs['class'] = 'h-16 shadow-sm mb-2 mt-1 border border-gray-300 text-gray-900 text-sm rounded focus:ring-blue-100 focus:border-blue-100 block w-full p-2 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white dark:focus:ring-blue-500 dark:focus:border-blue-500'

class LastWorkForm(forms.ModelForm):
    class Meta:
        model = LastWork
        fields = '__all__'
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super(LastWorkForm, self).__init__(*args, **kwargs)
        self.fields['date'].initial = timezone.localdate()
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-input'
        self.fields['task'].widget.attrs['rows'] = '2'
        self.fields['task'].widget.attrs['class'] = 'h-16 shadow-sm mb-2 mt-1 border border-gray-300 text-gray-900 text-sm rounded focus:ring-blue-100 focus:border-blue-100 block w-full p-2 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white dark:focus:ring-blue-500 dark:focus:border-blue-500'

class AttendanceNoteFormHalf(forms.ModelForm):
    class Meta:
        model = MatterAttendanceNotes
        fields = ['date', 'start_time', 'finish_time', 'subject_line', 'content', 'is_charged', 'person_attended']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'start_time': forms.TimeInput(attrs={'type': 'time'}),
            'finish_time': forms.TimeInput(attrs={'type': 'time'}),
        }

    def __init__(self, *args, **kwargs):
        super(AttendanceNoteFormHalf, self).__init__(*args, **kwargs)
        self.fields['date'].initial = timezone.localdate()
        for field_name, field in self.fields.items():
            if field_name not in ['content', 'is_charged']:
                field.widget.attrs['class'] = 'form-input'

class AttendanceNoteForm(forms.ModelForm):
    class Meta:
        model = MatterAttendanceNotes
        fields = ['file_number', 'date', 'start_time', 'finish_time', 'subject_line', 'content', 'is_charged', 'person_attended']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'start_time': forms.TimeInput(attrs={'type': 'time'}),
            'finish_time': forms.TimeInput(attrs={'type': 'time'}),
        }

    def save(self, commit=True):
        instance = super().save(commit=False)

        time_diff_minutes = (instance.finish_time.hour * 60 + instance.finish_time.minute) - \
            (instance.start_time.hour * 60 + instance.start_time.minute)

        instance.unit = max(1, ceil(time_diff_minutes / 6))

        if commit:
            instance.save()

        return instance

    def __init__(self, *args, **kwargs):
        super(AttendanceNoteForm, self).__init__(*args, **kwargs)
        self.fields['date'].initial = timezone.localdate()
        for field_name, field in self.fields.items():
            if field_name not in ['content', 'is_charged']:
                field.widget.attrs['class'] = 'form-input'

class LetterForm(forms.ModelForm):
    class Meta:
        model = MatterLetters
        fields = '__all__'
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super(LetterForm, self).__init__(*args, **kwargs)
        self.fields['date'].initial = timezone.localdate()
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-input'

class LetterHalfForm(forms.ModelForm):
    class Meta:
        model = MatterLetters
        fields = ['date', 'to_or_from', 'subject_line', 'sent', 'person_attended']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super(LetterHalfForm, self).__init__(*args, **kwargs)
        self.fields['date'].initial = timezone.localdate()
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-input'

class PmtsForm(forms.ModelForm):
    class Meta:
        model = PmtsSlips
        fields = '__all__'
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super(PmtsForm, self).__init__(*args, **kwargs)
        self.fields['date'].initial = timezone.localdate()
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-input'

class PmtsHalfForm(forms.ModelForm):
    class Meta:
        model = PmtsSlips
        fields = ['date', 'ledger_account', 'mode_of_pmt', 'amount', 'pmt_person', 'description']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super(PmtsHalfForm, self).__init__(*args, **kwargs)
        self.fields['date'].initial = timezone.localdate()
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-input'


class PmtsSlipEditForm(forms.ModelForm):
    class Meta:
        model = PmtsSlips
        fields = [
            'date', 'ledger_account', 'mode_of_pmt', 'amount',
            'pmt_person', 'description', 'is_money_out',
        ]
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-input'


def apply_pmts_slip_edit_locks(form, slip_usage):
    if not slip_usage.get('amount_editable', True):
        form.fields['amount'].widget = forms.HiddenInput()
    elif slip_usage.get('amount_edit_note'):
        form.fields['amount'].help_text = slip_usage['amount_edit_note']


def apply_green_slip_edit_locks(form, slip_usage):
    if not slip_usage.get('amount_editable', True):
        form.fields['amount'].widget = forms.HiddenInput()
    elif slip_usage.get('amount_edit_note'):
        form.fields['amount'].help_text = slip_usage['amount_edit_note']
    if slip_usage.get('has_usage'):
        form.fields['file_number_from'].widget = forms.HiddenInput()
        form.fields['file_number_to'].widget = forms.HiddenInput()


class GreenSlipEditForm(forms.ModelForm):
    class Meta:
        model = LedgerAccountTransfers
        fields = [
            'date', 'from_ledger_account', 'file_number_from',
            'to_ledger_account', 'file_number_to', 'amount', 'description',
        ]
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['file_number_from'].choices = sorted(
            self.fields['file_number_from'].choices, key=lambda choice: choice[1])
        self.fields['file_number_to'].choices = sorted(
            self.fields['file_number_to'].choices, key=lambda choice: choice[1])
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-input'


class LedgerAccountTransfersForm(forms.ModelForm):
    class Meta:
        model = LedgerAccountTransfers
        fields = '__all__'
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super(LedgerAccountTransfersForm, self).__init__(*args, **kwargs)
        self.fields['date'].initial = timezone.localdate()
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-input'

class LedgerAccountTransfersHalfForm(forms.ModelForm):
    class Meta:
        model = LedgerAccountTransfers
        fields = [
            'date', 'from_ledger_account', 'file_number_from',
            'to_ledger_account', 'file_number_to', 'amount', 'description',
        ]
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }
        labels = {
            'from_ledger_account': 'From ledger',
            'to_ledger_account': 'To ledger',
            'file_number_from': 'From file',
            'file_number_to': 'To file',
        }

    def __init__(self, *args, **kwargs):
        super(LedgerAccountTransfersHalfForm, self).__init__(*args, **kwargs)
        self.fields['date'].initial = timezone.localdate()
        self.fields['file_number_from'].choices = sorted(
            self.fields['file_number_from'].choices, key=lambda choice: choice[1])
        self.fields['file_number_to'].choices = sorted(
            self.fields['file_number_to'].choices, key=lambda choice: choice[1])
        self.fields['description'].widget.attrs['placeholder'] = 'Reason for transfer'
        self.fields['amount'].widget.attrs['placeholder'] = '0.00'
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-input'


class PricingItemForm(forms.ModelForm):
    class Meta:
        model = PricingItem
        fields = [
            'category',
            'matter_type',
            'name',
            'pricing_type',
            'price',
            'minimum_price',
            'maximum_price',
            'vat_treatment',
            'notes',
            'manager_only',
            'is_active',
        ]
        labels = {
            'manager_only': 'Only managers can edit this price',
            'is_active': 'Active',
            'minimum_price': 'Minimum',
            'maximum_price': 'Maximum',
            'vat_treatment': 'VAT',
        }
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super(PricingItemForm, self).__init__(*args, **kwargs)
        is_manager = bool(getattr(user, 'is_manager', False))

        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = 'w-4 h-4 text-blue-600 bg-gray-100 border-gray-300 rounded focus:ring-blue-500'
            else:
                field.widget.attrs['class'] = 'form-input'

        if not is_manager:
            for field_name in ['category', 'matter_type', 'name', 'pricing_type', 'manager_only', 'is_active']:
                self.fields[field_name].disabled = True

    def clean(self):
        cleaned_data = super().clean()
        category = cleaned_data.get('category')
        pricing_type = cleaned_data.get('pricing_type')
        price = cleaned_data.get('price')
        minimum_price = cleaned_data.get('minimum_price')
        maximum_price = cleaned_data.get('maximum_price')

        if category == 'veriphy':
            cleaned_data['matter_type'] = None

        if pricing_type == 'fixed' and price is None:
            self.add_error('price', 'Enter a fixed price.')

        if pricing_type == 'range':
            if minimum_price is None:
                self.add_error('minimum_price', 'Enter a minimum price.')
            if maximum_price is None:
                self.add_error('maximum_price', 'Enter a maximum price.')
            if minimum_price is not None and maximum_price is not None and minimum_price > maximum_price:
                self.add_error('maximum_price', 'Maximum price must be greater than or equal to minimum price.')

        return cleaned_data


class InvoicesForm(forms.ModelForm):
    class Meta:
        model = Invoices
        fields = '__all__'
        today_date = timezone.localdate()
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'})
        }

    def __init__(self, *args, **kwargs):
        super(InvoicesForm, self).__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-input'


class CreditNoteHalfForm(forms.ModelForm):
    class Meta:
        model = CreditNote
        fields = ['invoice', 'date', 'amount', 'reason']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super(CreditNoteHalfForm, self).__init__(*args, **kwargs)
        self.fields['date'].initial = timezone.localdate()
        self.fields['invoice'].queryset = Invoices.objects.filter(
            state='F').order_by('-invoice_number')
        self.fields['invoice'].label_from_instance = (
            lambda obj: f"Invoice {obj.invoice_number} - {obj.file_number.file_number} ({obj.date.strftime('%d/%m/%Y')})"
        )
        self.fields['amount'].help_text = 'Enter the total credit amount including VAT (gross).'
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-input'
        self.fields['amount'].widget.attrs['placeholder'] = 'e.g. 120.00 (incl. VAT)'


class ClientForm(forms.ModelForm):
    class Meta:
        model = ClientContactDetails
        # Per-client identity only. Terms / NCBA / source of funds / PEP are now
        # recorded per matter-client (see MatterClient) and edited on each matter,
        # so they are no longer editable on the client record.
        fields = ['name', 'is_business', 'dob', 'occupation', 'address_line1', 'address_line2',
                  'county', 'postcode', 'email', 'contact_number', 'date_of_last_aml',
                  'id_verified']
        
        widgets = {
            'dob': forms.DateInput(attrs={'type': 'date'}),
            'date_of_last_aml': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super(ClientForm, self).__init__(*args, **kwargs)
        self.fields['is_business'].label = 'Business client'
        self.fields['date_of_last_aml'].label = 'Date of last AML / UK Business Check'
        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = 'h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500'
            else:
                field.widget.attrs['class'] = 'form-input'


class ClientKeyDocumentForm(forms.ModelForm):
    class Meta:
        model = ClientKeyDocument
        fields = ['category', 'document_type', 'document_reference',
                  'issue_date', 'expiry_date', 'verified_on', 'notes']
        widgets = {
            'issue_date': forms.DateInput(attrs={'type': 'date'}),
            'expiry_date': forms.DateInput(attrs={'type': 'date'}),
            'verified_on': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super(ClientKeyDocumentForm, self).__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-input'


# extra=0: existing documents render for editing; new ones are added on demand via
# the "Add document" / "Renew" buttons (keeping expired documents on file as
# history rather than overwriting them).
ClientKeyDocumentFormSet = inlineformset_factory(
    ClientContactDetails,
    ClientKeyDocument,
    form=ClientKeyDocumentForm,
    extra=0,
    can_delete=True
)


class MatterKeyDateForm(forms.ModelForm):
    class Meta:
        model = MatterKeyDate
        fields = ['date_type', 'title', 'date', 'time', 'location', 'notes']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'time': forms.TimeInput(attrs={'type': 'time'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super(MatterKeyDateForm, self).__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-input'


class AuthorisedPartyForm(forms.ModelForm):
    class Meta:
        model = AuthorisedParties
        fields = ['name', 'relationship_to_client', 'address_line1', 'address_line2',
                  'county', 'postcode', 'email', 'contact_number', 'id_check',
                  'date_of_id_check', 'date_of_last_aml']
        
        widgets = {

            'date_of_id_check': forms.DateInput(attrs={'type': 'date'}),
            'date_of_last_aml': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super(AuthorisedPartyForm, self).__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = 'h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500'
            else:
                field.widget.attrs['class'] = 'form-input'

class OtherSideForm(forms.ModelForm):

    class Meta:
        model = OthersideDetails
        fields = '__all__'
        widgets = {
            'dob': forms.DateInput(attrs={'type': 'date'}),
            'date_of_incorporation': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super(OtherSideForm, self).__init__(*args, **kwargs)
        self.fields['is_business'].label = 'Business / company'
        self.fields['dob'].label = 'Date of Birth'
        self.fields['date_of_incorporation'].label = 'Date of Incorporation'
        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = 'h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500'
            else:
                field.widget.attrs['class'] = 'form-input'

#: Risk assessment questions the form used to ask twice. They are asked once
#: now; the fields stay on the model so assessments that answered them still
#: render and score on what they said (backend.risk_scoring reads both).
SUPERSEDED_RISK_FIELDS = [
    'makes_sense_for_client',
    'higher_risk_sector',
    'cash_intensive_business_activity',
]


#: The answer that carries risk, per question, read from the model so the
#: form cannot drift from the scoring.
RISKY_ANSWERS = {field: answer for field, answer, _label
                 in RiskAssessment.RISK_FLAG_RULES}

#: "Issues identified in this section" boxes, and the questions whose answers
#: make them worth filling in. An assessment with nothing flagged in a section
#: has nothing to write there, so the box stays optional.
SECTION_DETAIL_QUESTIONS = {
    'issues_identified_client_risks_sec': (
        'unusual_client', 'client_concerns', 'third_party_authority',
        'concerns_about_parties', 'designated_person_entity'),
    'issues_identified_jurisdiction_risks_sec': (
        'location_of_instruction_concerns', 'make_sense_location_of_instructions',
        'overseas_elements'),
    'issues_identified_matter_risks_sec': (
        'usual_work', 'complex_structure', 'cash_intensive_industry',
        'high_risk_industry', 'proliferation_financing', 'other_risks',
        'receiving_funds_from_overseas', 'receiving_funds_from_third_parties',
        'consistent_with_client_profile'),
    'issues_identified_enhanced_due_dilligence': (
        'complex_structure_or_unusual', 'high_risk_third_country_or_jurisdiction',
        'pep_type', 'financial_sanctions', 'country_subject_to_sanctions',
        'unusual_complex_transaction', 'unusual_pattern_of_transactions',
        'lack_of_economic_or_legal_purpose', 'other_high_risk_factors'),
}

#: Boxes that follow a single answer: (field, answer that makes it necessary).
ANSWER_DETAIL_TRIGGERS = {
    'who_they_are': ('meeting_in_person', 'No'),
    'product_service_risk_details': ('consistent_with_client_profile', 'No'),
}

#: Only asked where the client is an entity.
ENTITY_DETAIL_FIELDS = ('beneficial_owners_details', 'ultimate_beneficial_owners')

#: Dropdowns that are not questions: the rating is scored, and these are set by
#: the workflow or follow from it.
NON_QUESTION_CHOICE_FIELDS = (
    'matter',
    'client_risk_level',
    'matter_risk_level',
    'customer_due_diligence_level',
    'evidence_of_source_of_wealth',
    'source_of_wealth_correspondence',
    'edd_senior_approval_by',
)


class RiskAssessmentForm(forms.ModelForm):
    """The client and matter risk assessment.

    The risk levels and the due diligence level are scored from the answers by
    ``backend.risk_scoring`` and arrive pre-filled. They stay editable because
    LSAG 5.13 requires a practice to be able to override an automatically
    generated score — but changing one without saying why is rejected, and no
    override may take the due diligence below enhanced where the MLRs make
    enhanced due diligence mandatory.

    Questions the old form asked twice (cash intensity, high-risk sector,
    whether the instruction makes sense for the client) are now asked once.
    The retired fields are still on the model so existing assessments render
    and score as they always did; they are simply not put to staff again.
    """

    #: Every question has to be answered — they are what the rating is scored
    #: from — but the free-text boxes are only required when there is something
    #: to write in them, which ``clean()`` works out from the answers given.
    #: These are never required by the field itself.
    OPTIONAL_FIELDS = [
        'escalated_date',
        'risk_override_reason',
        'edd_measures_taken',
        'edd_enhanced_monitoring',
        'edd_senior_approval_by',
        'edd_senior_approval_date',
        'evidence_of_source_of_wealth',
        'source_of_wealth_correspondence',
        # Filled in when the answers call for it (see clean()).
        'matter_description',
        *SECTION_DETAIL_QUESTIONS,
        *ANSWER_DETAIL_TRIGGERS,
        *ENTITY_DETAIL_FIELDS,
    ]

    class Meta:
        model = RiskAssessment
        # Sign-off fields are set by the workflow (a fee earner signs off from
        # the matter page) and the scores are computed from the answers, so
        # neither is picked on the form itself.
        exclude = [
            'due_diligence_signed_by',
            'signoff_status',
            'completed_by',
            'completed_at',
            'signed_off_by',
            'signed_off_at',
            'signoff_comments',
            'client_risk_score',
            'matter_risk_score',
            'computed_client_risk_level',
            'computed_matter_risk_level',
            'computed_due_diligence_level',
            'overall_risk_level',
            'scoring_version',
            'risk_score_breakdown',
            'politically_exposed_person',
        ] + SUPERSEDED_RISK_FIELDS

        widgets = {
            'due_diligence_date': forms.DateInput(attrs={'type': 'date'}),
            'escalated_date': forms.DateInput(attrs={'type': 'date'}),
            'edd_senior_approval_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super(RiskAssessmentForm, self).__init__(*args, **kwargs)
        self.fields['due_diligence_date'].initial = timezone.localdate()
        matter = self.initial.get('matter') or getattr(self.instance, 'matter', None)
        if not self.instance.pk and matter is not None:
            matter = (WIP.objects.filter(pk=matter).first()
                      if isinstance(matter, int) else matter)
            if matter is not None:
                self.fields['matter_description'].initial = matter.matter_description
        if not self.instance.pk:
            self._start_questions_unanswered()
        self.fields['edd_senior_approval_by'].label = 'Approved by'
        self.fields['edd_senior_approval_by'].empty_label = 'Not yet approved'
        self.fields['risk_override_reason'].label = (
            'Reason for recording a different rating')
        # The scoring is the source of the rating, so the dropdowns start on
        # what the answers produce and only move if someone overrides them.
        for field_name, computed in (
            ('client_risk_level', 'computed_client_risk_level'),
            ('matter_risk_level', 'computed_matter_risk_level'),
            ('customer_due_diligence_level', 'computed_due_diligence_level'),
        ):
            if self.instance.pk and getattr(self.instance, computed, None):
                self.fields[field_name].initial = getattr(self.instance, computed)

        for field_name, field in self.fields.items():
            # Every question is required; the boxes in OPTIONAL_FIELDS are not,
            # whatever the model says, because clean() decides when they are.
            field.required = field_name not in self.OPTIONAL_FIELDS
            if isinstance(field, forms.BooleanField):
                field.widget = forms.Select(choices=[(True, 'Yes'), (False, 'No')])
            # .form-input already styles inputs, selects and textareas for this
            # app's light interface. The hand-rolled class this used to carry
            # brought dark: variants with it, so on a machine set to dark mode
            # the text boxes rendered as dark panels in an otherwise light page.
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = (
                    'h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500')
            else:
                field.widget.attrs['class'] = 'form-input'
            if isinstance(field.widget, forms.Textarea):
                field.widget.attrs['rows'] = 3

    def _start_questions_unanswered(self):
        """A new assessment opens with every question blank.

        The model defaults these to 'No' or 'N/A', which would mean a saved
        assessment carried answers nobody gave and the rating was scored from
        them. They stay required, so each one has to be chosen.
        """
        for name, field in self.fields.items():
            if name in NON_QUESTION_CHOICE_FIELDS:
                continue
            if not isinstance(field, forms.TypedChoiceField):
                continue
            field.choices = ([('', 'Select\u2026')]
                             + [choice for choice in field.choices if choice[0]])
            field.initial = ''

    def answers(self):
        """The answers as they stand, for scoring.

        Falls back to the saved assessment for anything not on the form, so an
        older record keeps scoring on the superseded questions it actually
        answered. A new assessment answered none of them, and their model
        defaults happen to be the answer that scores, so they are left empty
        rather than inherited.
        """
        is_new = self.instance.pk is None
        data = {}
        for name in (f.name for f in RiskAssessment._meta.get_fields()
                     if hasattr(f, 'attname')):
            if name in self.cleaned_data:
                data[name] = self.cleaned_data[name]
            elif is_new and name in SUPERSEDED_RISK_FIELDS:
                data[name] = None
            else:
                data[name] = getattr(self.instance, name, None)
        return SimpleNamespace(**data)

    def clean(self):
        cleaned = super().clean()
        # Score what has been answered, then hold the recorded rating against
        # it. ``self.breakdown`` is handed to the template so the form can show
        # the working.
        self.breakdown = score_risk_assessment(self.answers())

        recorded = {
            'client_risk_level': cleaned.get('client_risk_level'),
            'matter_risk_level': cleaned.get('matter_risk_level'),
            'customer_due_diligence_level': cleaned.get('customer_due_diligence_level'),
        }
        computed = {
            'client_risk_level': self.breakdown['client']['level'],
            'matter_risk_level': self.breakdown['matter']['level'],
            'customer_due_diligence_level': self.breakdown['due_diligence_level'],
        }
        overridden = [name for name, value in recorded.items()
                      if value and value != computed[name]]

        if overridden and not (cleaned.get('risk_override_reason') or '').strip():
            self.add_error('risk_override_reason', forms.ValidationError(
                'The rating recorded differs from the rating these answers '
                'score. Say why, or put the rating back to the computed one.'))

        # A risk rating is a judgement and can be overridden. Enhanced due
        # diligence, where the MLRs require it, is not a judgement.
        mandatory = self.breakdown['edd_reasons']
        if mandatory and recorded['customer_due_diligence_level'] != 'Enhanced':
            self.add_error('customer_due_diligence_level', forms.ValidationError(
                'Enhanced due diligence is required here and cannot be '
                'reduced: %(reasons)s.',
                params={'reasons': '; '.join(mandatory)}))

        if recorded['customer_due_diligence_level'] == 'Enhanced':
            self._require_edd_measures(cleaned)

        self._require_relevant_details(cleaned)

        return cleaned

    def _is_risky(self, cleaned, field):
        return cleaned.get(field) == RISKY_ANSWERS.get(field)

    def _require_relevant_details(self, cleaned):
        """Ask for a free-text box only where the answers call for one.

        Most of these boxes have nothing to say on a clean file, and requiring
        them regardless taught people to type a full stop. They are required
        where the answers mean there is something to record.
        """
        for detail, questions in SECTION_DETAIL_QUESTIONS.items():
            if (cleaned.get(detail) or '').strip():
                continue
            flagged = [q for q in questions if self._is_risky(cleaned, q)]
            if flagged:
                self.add_error(detail, forms.ValidationError(
                    'Something in this section is flagged, so say what it is '
                    'and what you did about it.'))

        for detail, (field_name, answer) in ANSWER_DETAIL_TRIGGERS.items():
            if cleaned.get(field_name) == answer and not (cleaned.get(detail) or '').strip():
                self.add_error(detail, forms.ValidationError(
                    'This follows from the answer above, so it needs filling in.'))

        matter = cleaned.get('matter') or getattr(self.instance, 'matter', None)
        if matter is not None and any(getattr(c, 'is_business', False)
                                      for c in matter.all_clients):
            for detail in ENTITY_DETAIL_FIELDS:
                if not (cleaned.get(detail) or '').strip():
                    self.add_error(detail, forms.ValidationError(
                        'The client is an entity, so its beneficial ownership '
                        'has to be recorded.'))

    def _require_edd_measures(self, cleaned):
        """Enhanced due diligence has to say what was actually done."""
        if not (cleaned.get('edd_measures_taken') or '').strip():
            self.add_error('edd_measures_taken', forms.ValidationError(
                'Record the additional measures taken, now that enhanced due '
                'diligence applies.'))
        if not (cleaned.get('edd_enhanced_monitoring') or '').strip():
            self.add_error('edd_enhanced_monitoring', forms.ValidationError(
                'Record how this matter will be monitored more closely.'))
        if not cleaned.get('evidence_of_source_of_wealth'):
            self.add_error('evidence_of_source_of_wealth', forms.ValidationError(
                'Enhanced due diligence requires the source of wealth to be '
                'evidenced on the file.'))
        # MLRs reg 35(1)(a): a PEP relationship needs senior management
        # approval before it is entered into or continued.
        if cleaned.get('pep_type') and cleaned.get('pep_type') != 'N/A':
            if not cleaned.get('edd_senior_approval_by'):
                self.add_error('edd_senior_approval_by', forms.ValidationError(
                    'A PEP relationship needs senior management approval '
                    '(MLRs reg 35(1)).'))
            if not cleaned.get('edd_senior_approval_date'):
                self.add_error('edd_senior_approval_date', forms.ValidationError(
                    'Record the date senior management approved this.'))


class OngoingMonitoringForm(forms.ModelForm):

    class Meta:
        model = OngoingMonitoring
        # The matter and author are set by the view; the sign-off fields by
        # the workflow (a fee earner signs off from the matter page), so none
        # of them are picked on the form itself.
        exclude = [
            'file_number',
            'created_by',
            'signed_by',
            'signoff_status',
            'completed_by',
            'completed_at',
            'signed_off_by',
            'signed_off_at',
            'signoff_comments',
        ]
        today_date = timezone.localdate()
        widgets = {
            'date_due_diligence_conducted': forms.DateInput(attrs={'type': 'date'})
        }
    def __init__(self, *args, **kwargs):
        super(OngoingMonitoringForm, self).__init__(*args, **kwargs)   
        self.fields['date_due_diligence_conducted'].initial = timezone.localdate()
        # self.fields['third_party_authority'].widget = forms.CheckboxInput()
        for field_name, field in self.fields.items():

            field.required = True
            if isinstance(field, forms.BooleanField):
                field.widget = forms.Select(choices=[(True, 'Yes'), (False, 'No')])
                field.widget.attrs['class'] = 'form-input'
            elif isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = 'mb-1 text-gray-900 rounded focus:ring-blue-100 focus:border-blue-100 dark:bg-gray-700 dark:border-gray-600 dark:focus:ring-blue-500 dark:focus:border-blue-500'
            else:
                field.widget.attrs['class'] = 'form-input'
            if isinstance(field.widget, forms.Textarea):
                field.widget.attrs['class'] = 'h-16 shadow-sm mb-2 mt-1 border border-gray-300 text-gray-900 text-sm rounded focus:ring-blue-100 focus:border-blue-100 block w-full p-2 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white dark:focus:ring-blue-500 dark:focus:border-blue-500'
                field.widget.attrs['rows'] = 4


class MatterFileReviewForm(forms.ModelForm):
    class Meta:
        model = MatterFileReview
        exclude = ['matter', 'created_by', 'timestamp', 'updated_at']
        widgets = {
            'date_reviewed': forms.DateInput(attrs={'type': 'date'}),
            'date_review_completed': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super(MatterFileReviewForm, self).__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.required = False
            if isinstance(field, forms.ModelChoiceField):
                if field_name in ['file_reviewed_by', 'file_review_completed_by']:
                    field.queryset = field.queryset.filter(
                        is_active=True
                    ).order_by('first_name', 'last_name', 'username')
                field.empty_label = '---'
                field.widget.attrs['class'] = 'form-input'
            elif isinstance(field, forms.ChoiceField):
                field.choices = [('', '---')] + [
                    choice for choice in field.choices if choice[0] != ''
                ]
                field.widget.attrs['class'] = 'form-input'
            elif isinstance(field.widget, forms.Textarea):
                field.widget.attrs['class'] = 'h-16 shadow-sm mb-2 mt-1 border border-gray-300 text-gray-900 text-sm rounded focus:ring-blue-100 focus:border-blue-100 block w-full p-2 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white dark:focus:ring-blue-500 dark:focus:border-blue-500'
                field.widget.attrs['rows'] = 3
            else:
                field.widget.attrs['class'] = 'form-input'

class Free30MinsForm(forms.ModelForm):
    class Meta:
        model = Free30Mins
        fields = ['date', 'start_time', 'finish_time', 'matter_type',  'notes', 'fee_earner']
        
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'start_time': forms.TimeInput(attrs={'type': 'time'}),
            'finish_time': forms.TimeInput(attrs={'type': 'time'}),
        }

    def __init__(self, *args, **kwargs):
        super(Free30MinsForm, self).__init__(*args, **kwargs)
        self.fields['date'].initial = timezone.localdate()
        for field_name, field in self.fields.items():
            if field_name not in ['notes']:
                field.widget.attrs['class'] = 'form-input'

class Free30MinsAttendeesForm(forms.ModelForm):
    class Meta:
        model = Free30MinsAttendees
        fields = ['name', 'email', 'contact_number','address_line1', 'address_line2', 'county', 'postcode' ]

    def __init__(self, *args, **kwargs):
        super(Free30MinsAttendeesForm, self).__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-input'

formset_free_30mins_attendees = formset_factory(Free30MinsAttendeesForm,extra=2)

class DatalistWidget(forms.TextInput):
    def __init__(self, datalist_id, *args, **kwargs):
        self.datalist_id = datalist_id
        self.choices = []  # Initialize choices
        super(DatalistWidget, self).__init__(*args, **kwargs)

    def render(self, name, value, attrs=None, renderer=None):
        # Render the text input field first
        text_html = super(DatalistWidget, self).render(name, value, attrs, renderer)
        
        # Create the datalist options, showing file number but using ID as the value.
        # Use format_html so option values (DB-derived) are HTML-escaped.
        options_html = format_html_join(
            '', '<option>{}</option>',
            ((option[0],) for option in self.choices),  # option[0] is ID, option[1] is file number
        )
        datalist_html = format_html(
            '<datalist id="{}">{}</datalist>', self.datalist_id, options_html)

        # Return the input field along with the datalist
        return mark_safe(f'{text_html}{datalist_html}')

    def update_choices(self, choices):
        """Update the choices for the datalist (ID, File Number)"""
        self.choices = choices

# Upload limits for undertaking proof files. Generous size cap (primary DoS
# control) plus an extension allowlist of document/image types.
MAX_UNDERTAKING_FILE_SIZE = 100 * 1024 * 1024  # 100 MB
ALLOWED_UNDERTAKING_EXTENSIONS = frozenset({
    '.pdf', '.doc', '.docx', '.jpg', '.jpeg', '.png', '.tif', '.tiff',
})


def validate_undertaking_file(uploaded_file):
    """Validate a single undertaking upload; raise ValidationError if bad."""
    if uploaded_file is None:
        return uploaded_file
    # Only newly uploaded files have a size/name to check; existing stored
    # files come through as a FieldFile and are left untouched.
    if hasattr(uploaded_file, 'size') and hasattr(uploaded_file, 'name'):
        if uploaded_file.size and uploaded_file.size > MAX_UNDERTAKING_FILE_SIZE:
            raise forms.ValidationError(
                f'File too large (max {MAX_UNDERTAKING_FILE_SIZE // (1024 * 1024)} MB).')
        ext = os.path.splitext(uploaded_file.name)[1].lower()
        if ext not in ALLOWED_UNDERTAKING_EXTENSIONS:
            raise forms.ValidationError('File type not allowed.')
    return uploaded_file


class UndertakingForm(forms.ModelForm):


    class Meta:
        model = Undertaking
        fields = '__all__'
        widgets = {
            'date_given': forms.DateInput(attrs={'type': 'date'}),
            'date_discharged': forms.DateInput(attrs={'type': 'date'}),
        }

    def clean_document_given_on(self):
        return validate_undertaking_file(self.cleaned_data.get('document_given_on'))

    def clean_discharged_proof(self):
        return validate_undertaking_file(self.cleaned_data.get('discharged_proof'))

    def __init__(self, *args, **kwargs):
        super(UndertakingForm, self).__init__(*args, **kwargs)

        # Fetching the file numbers and their corresponding IDs for the datalist
        file_number_choices = WIP.objects.all().values_list('file_number').order_by('file_number')

        # Using the custom DatalistWidget for file_number field
        self.fields['file_number'].widget = DatalistWidget(datalist_id='file_number_datalist')
        
        # Update choices with (ID, file_number) tuples
        self.fields['file_number'].widget.update_choices([( file_number) for file_number in file_number_choices])

        # Adding a 'list' attribute to associate with the datalist
        self.fields['file_number'].widget.attrs.update({'list': 'file_number_datalist'})

        # Adding the 'form-input' class to all fields
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-input'

class PolicyForm(forms.ModelForm):
    content = QuillFormField()

    class Meta:
        model = Policy
        fields = ['description', 'content']
    
    def __init__(self, *args, **kwargs):
        super(PolicyForm, self).__init__(*args, **kwargs)

        if self.instance and self.instance.pk:
            latest_version = self.instance.latest_version()
            if latest_version:
                self.fields['content'].initial = latest_version.content
        for field_name, field in self.fields.items():
            if field_name != 'content':
                field.widget.attrs['class'] = 'form-input'


class MemoForm(forms.ModelForm):
    class Meta:
        model = Memo
        fields = ['content', 'date', 'is_final']
    def __init__(self, *args, **kwargs):
        super(MemoForm, self).__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
                if field_name not in ['content', 'is_charged']:
                    field.widget.attrs['class'] = 'form-input'
