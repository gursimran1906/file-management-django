from django import forms
from .models import WIP, ClientContactDetails, NextWork, LastWork, MatterAttendanceNotes, MatterLetters, PmtsSlips, LedgerAccountTransfers, Invoices, ClientContactDetails, AuthorisedParties, RiskAssessment, OngoingMonitoring
from datetime import date
from math import ceil


class OpenFileForm(forms.ModelForm):
    class Meta:
        model = WIP
        fields = '__all__'

    undertakings = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}), required=False)


class NextWorkFormWithoutFileNumber(forms.ModelForm):
    class Meta:
        model = NextWork
        fields = ['person', 'task', 'date',]
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super(NextWorkFormWithoutFileNumber, self).__init__(*args, **kwargs)

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

        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'shadow-sm mb-1 mt-1 border border-gray-300 text-gray-900 text-sm rounded focus:ring-blue-100 focus:border-blue-100 block w-full p-2 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white dark:focus:ring-blue-500 dark:focus:border-blue-500'

        self.fields['task'].widget.attrs['rows'] = '2'
        self.fields['task'].widget.attrs['class'] = 'h-16 shadow-sm mb-2 mt-1 border border-gray-300 text-gray-900 text-sm rounded focus:ring-blue-100 focus:border-blue-100 block w-full p-2 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white dark:focus:ring-blue-500 dark:focus:border-blue-500'


class LastWorkFormWithoutFileNumber(forms.ModelForm):
    class Meta:
        model = LastWork
        fields = ['person', 'task', 'date',]
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super(LastWorkFormWithoutFileNumber, self).__init__(*args, **kwargs)

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

        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-input'
        self.fields['task'].widget.attrs['rows'] = '2'
        self.fields['task'].widget.attrs['class'] = 'h-16 shadow-sm mb-2 mt-1 border border-gray-300 text-gray-900 text-sm rounded focus:ring-blue-100 focus:border-blue-100 block w-full p-2 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white dark:focus:ring-blue-500 dark:focus:border-blue-500'



class AttendanceNoteFormHalf(forms.ModelForm):
    class Meta:
        model = MatterAttendanceNotes
        fields = ['date', 'start_time', 'finish_time', 'subject_line',
                  'content', 'is_charged', 'person_attended', ]
        today_date = date.today()
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'value': today_date}),
            'start_time': forms.TimeInput(attrs={'type': 'time'}),
            'finish_time': forms.TimeInput(attrs={'type': 'time'}),
        }

    def __init__(self, *args, **kwargs):
        super(AttendanceNoteFormHalf, self).__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-input'


class AttendanceNoteForm(forms.ModelForm):
    class Meta:
        model = MatterAttendanceNotes
        fields = ['file_number', 'date', 'start_time', 'finish_time',
                  'subject_line', 'content', 'is_charged', 'person_attended', ]
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'start_time': forms.TimeInput(attrs={'type': 'time'}),
            'finish_time': forms.TimeInput(attrs={'type': 'time'}),
        }

    def save(self, commit=True):
        instance = super().save(commit=False)

        # Calculate the difference between start_time and finish_time in minutes
        time_diff_minutes = (instance.finish_time.hour * 60 + instance.finish_time.minute) - \
            (instance.start_time.hour * 60 + instance.start_time.minute)

        # Calculate the number of units (assuming each unit is 6 minutes) and round up
        instance.unit = max(1, ceil(time_diff_minutes / 6))

        if commit:
            instance.save()

        return instance

    def __init__(self, *args, **kwargs):
        super(AttendanceNoteForm, self).__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-input'

class LetterForm(forms.ModelForm):
    class Meta:
        model = MatterLetters
        fields = '__all__'
        today_date = date.today()
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'value': today_date})
        }

    def __init__(self, *args, **kwargs):
        super(LetterForm, self).__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-input'

class LetterHalfForm(forms.ModelForm):
    class Meta:
        model = MatterLetters
        fields = ['date', 'to_or_from', 'subject_line',
                  'sent', 'person_attended', ]
        today_date = date.today()
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'value': today_date})
        }

    def __init__(self, *args, **kwargs):
        super(LetterHalfForm, self).__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-input'

class PmtsForm(forms.ModelForm):
    class Meta:
        model = PmtsSlips
        fields = '__all__'
        today_date = date.today()
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'value': today_date})
        }

    def __init__(self, *args, **kwargs):
        super(PmtsForm, self).__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-input'

class PmtsHalfForm(forms.ModelForm):
    class Meta:
        model = PmtsSlips
        fields = ['date', 'ledger_account', 'mode_of_pmt',
                  'amount', 'pmt_person', 'description']
        today_date = date.today()
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'value': today_date})
        }

    def __init__(self, *args, **kwargs):
        super(PmtsHalfForm, self).__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-input'

class LedgerAccountTransfersForm(forms.ModelForm):
    class Meta:
        model = LedgerAccountTransfers
        fields = '__all__'
        today_date = date.today()
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'value': today_date})
        }

    def __init__(self, *args, **kwargs):
        super(LedgerAccountTransfersForm, self).__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-input'

class LedgerAccountTransfersHalfForm(forms.ModelForm):
    class Meta:
        model = LedgerAccountTransfers
        fields = ['date', 'file_number_to', 'from_ledger_account',
                  'to_ledger_account', 'amount', 'description']
        today_date = date.today()
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'value': today_date})
        }

    def __init__(self, *args, **kwargs):
        super(LedgerAccountTransfersHalfForm, self).__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-input'

class InvoicesForm(forms.ModelForm):
    class Meta:
        model = Invoices
        fields = '__all__'
        today_date = date.today()
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
        today_date = date.today()
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
        today_date = date.today()
        widgets = {

            'date_of_id_check': forms.DateInput(attrs={'type': 'date'})
        }

    def __init__(self, *args, **kwargs):
        super(AuthorisedPartyForm, self).__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-input'

class RiskAssessmentForm(forms.ModelForm):
    
    class Meta:
        model = RiskAssessment
        fields = '__all__'
        today_date = date.today()
        widgets = {
            'due_diligence_date': forms.DateInput(attrs={'type': 'date', 'value': today_date}),
            'escalated_date':forms.DateInput(attrs={'type': 'date'}),
        }
    def __init__(self, *args, **kwargs):
        super(RiskAssessmentForm, self).__init__(*args, **kwargs)   
       
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
        today_date = date.today()
        widgets = {
            'date_due_diligence_conducted': forms.DateInput(attrs={'type': 'date', 'value': today_date})
        }
    def __init__(self, *args, **kwargs):
        super(OngoingMonitoringForm, self).__init__(*args, **kwargs)   
       
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