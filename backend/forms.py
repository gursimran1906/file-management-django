from django import forms
from .models import *
from django.forms import formset_factory
from datetime import date
from math import ceil
from django.utils import timezone
from django.core.validators import RegexValidator
from django.utils.safestring import mark_safe
from django_quill.forms import QuillFormField

class OpenFileForm(forms.ModelForm):
    class Meta:
        model = WIP
        fields = '__all__'

    undertakings = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}), required=False)

class NextWorkFormWithoutFileNumber(forms.ModelForm):
    class Meta:
        model = NextWork
        fields = ['person', 'task', 'date']
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
        fields = ['date', 'from_ledger_account','file_number_from', 'to_ledger_account', 'file_number_to', 'amount', 'description']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super(LedgerAccountTransfersHalfForm, self).__init__(*args, **kwargs)
        self.fields['date'].initial = timezone.localdate()
        self.fields['file_number_from'].choices = sorted(self.fields['file_number_from'].choices, key=lambda choice: choice[1])
        self.fields['file_number_to'].choices = sorted(self.fields['file_number_to'].choices, key=lambda choice: choice[1])
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-input'

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

class ClientForm(forms.ModelForm):
    class Meta:
        model = ClientContactDetails
        fields = ['name', 'dob', 'occupation','address_line1', 'address_line2',
                  'county', 'postcode', 'email', 'contact_number', 'date_of_last_aml', 'id_verified']
        
        widgets = {
            'dob': forms.DateInput(attrs={'type': 'date'}),
            'date_of_last_aml': forms.DateInput(attrs={'type': 'date'})
        }

    def __init__(self, *args, **kwargs):
        super(ClientForm, self).__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-input'

class AuthorisedPartyForm(forms.ModelForm):
    class Meta:
        model = AuthorisedParties
        fields = ['name', 'relationship_to_client', 'address_line1', 'address_line2',
                  'county', 'postcode', 'email', 'contact_number', 'id_check', 'date_of_id_check', ]
        
        widgets = {

            'date_of_id_check': forms.DateInput(attrs={'type': 'date'})
        }

    def __init__(self, *args, **kwargs):
        super(AuthorisedPartyForm, self).__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-input'

class OtherSideForm(forms.ModelForm):
    
    class Meta:
        model = OthersideDetails
        fields = '__all__'
        widgets = {
            
        }

    def __init__(self, *args, **kwargs):
        super(OtherSideForm, self).__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-input'

class RiskAssessmentForm(forms.ModelForm):
    
    class Meta:
        model = RiskAssessment
        fields = '__all__'
        
        widgets = {
            'due_diligence_date': forms.DateInput(attrs={'type': 'date'}),
            'escalated_date':forms.DateInput(attrs={'type': 'date'}),
        }
    def __init__(self, *args, **kwargs):
        super(RiskAssessmentForm, self).__init__(*args, **kwargs)   
        self.fields['due_diligence_date'].initial = timezone.localdate()
        # self.fields['third_party_authority'].widget = forms.CheckboxInput()
        for field_name, field in self.fields.items():

            if field_name != 'escalated_date':
                
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

class OngoingMonitoringForm(forms.ModelForm):
    
    class Meta:
        model = OngoingMonitoring
        fields = '__all__'
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
        
        # Create the datalist options, showing file number but using ID as the value
        datalist_html = f'<datalist id="{self.datalist_id}">'
        for option in self.choices:
            datalist_html += f'<option >{option[0]}</option>'  # option[0] is ID, option[1] is file number
        datalist_html += '</datalist>'
        
        # Return the input field along with the datalist
        return mark_safe(f'{text_html}{datalist_html}')

    def update_choices(self, choices):
        """Update the choices for the datalist (ID, File Number)"""
        self.choices = choices

class UndertakingForm(forms.ModelForm):
    

    class Meta:
        model = Undertaking
        fields = '__all__'
        widgets = {
            'date_given': forms.DateInput(attrs={'type': 'date'}),
            'date_discharged': forms.DateInput(attrs={'type': 'date'}),
        }

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
            field.widget.attrs['class'] = 'form-input'



