from django import forms
from .models import CPDTrainingLog, CustomUser, HolidayRecord, UserDocument
from django.contrib.auth.forms import UserCreationForm

class LoginForm(forms.Form):
    user_initials = forms.CharField(label='User Initials', max_length=3, required=True)
    password = forms.CharField(label='Password', widget=forms.PasswordInput, required=True)

class CustomUserCreationForm(UserCreationForm):
    email = forms.EmailField(required=True)
    first_name = forms.CharField(max_length=30, required=True)
    last_name = forms.CharField(max_length=30, required=True)

    class Meta:
        model = CustomUser
        fields = ('first_name', 'last_name', 'username', 'email', 'password1', 'password2')

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        if commit:
            user.save()
        return user
    
    def __init__(self, *args, **kwargs):
        super(CustomUserCreationForm, self).__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-control'


class HolidayRecordForm(forms.ModelForm):
    class Meta:
        model = HolidayRecord
        fields = '__all__'
        widgets = {
            'start_date': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'end_date': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'checked_on': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'approved_on': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
        }

    def __init__(self, *args, **kwargs):
        super(HolidayRecordForm, self).__init__(*args, **kwargs)

        if self.instance and self.instance.pk:
            for field in ['start_date', 'end_date', 'checked_on', 'approved_on']:
                datetime_value = getattr(self.instance, field)
                if datetime_value:
                    formatted_value = datetime_value.strftime('%Y-%m-%dT%H:%M')
                    self.fields[field].initial = formatted_value

        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-input'
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = ' mb-1 text-gray-900 rounded focus:ring-blue-100 focus:border-blue-100 dark:bg-gray-700 dark:border-gray-600 dark:focus:ring-blue-500 dark:focus:border-blue-500'


class OfficeClosureRecordForm(forms.ModelForm):
    employees = forms.ModelMultipleChoiceField(
        queryset=CustomUser.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        label="Select Employees"
    )

    class Meta:
        model = HolidayRecord
        fields = ['employees', 'start_date', 'end_date']
        widgets = {
            'start_date': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'end_date': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }

    def __init__(self, *args, **kwargs):
        super(OfficeClosureRecordForm, self).__init__(*args, **kwargs)
        self.fields['employees'].queryset = CustomUser.objects.filter(is_active=True)

        if self.instance and self.instance.pk:
            for field in ['start_date', 'end_date']:
                datetime_value = getattr(self.instance, field)
                if datetime_value:
                    formatted_value = datetime_value.strftime('%Y-%m-%dT%H:%M')
                    self.fields[field].initial = formatted_value

        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxSelectMultiple):
                field.widget.attrs['class'] = 'employee-checkbox space-y-2'
            elif isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = 'mb-1 text-gray-900 rounded focus:ring-blue-100 focus:border-blue-100 dark:bg-gray-700 dark:border-gray-600 dark:focus:ring-blue-500 dark:focus:border-blue-500'
            else:
                field.widget.attrs['class'] = 'form-input border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 w-full'

class UserDocumentForm(forms.ModelForm):
    class Meta:
        model = UserDocument
        fields = ['document', 'employee', 'description']

class CPDTrainingLogForm(forms.ModelForm):
    class Meta:
        model = CPDTrainingLog
        fields = [
            'user', 'course_title', 'delivered_by', 'delivery_of_course',
            'date_completed', 'impact', 'certificate_provided'
        ]
        widgets = {
            'date_completed': forms.DateInput(attrs={'type': 'date'}),
        }
    def __init__(self, *args, **kwargs):
        super(CPDTrainingLogForm, self).__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-input'
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = ' mb-1 text-gray-900 rounded focus:ring-blue-100 focus:border-blue-100 dark:bg-gray-700 dark:border-gray-600 dark:focus:ring-blue-500 dark:focus:border-blue-500'

