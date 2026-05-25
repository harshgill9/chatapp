# core/forms.py
from django import forms
from .models import Profile
from .models import Room

class SearchForm(forms.Form):
    query = forms.CharField(label='Search User', max_length=100)
    def clean_query(self):
        query = self.cleaned_data.get('query')
        if not query:
            raise forms.ValidationError("Search query cannot be empty.")
        return query

class ProfilePicForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ['profile_pic']

class ProfileUpdateForm(forms.ModelForm):
    first_name = forms.CharField(required=False)
    
    class Meta:
        model = Profile
        fields = ['profile_pic', 'phone_number', 'about']

class RoomImageForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = ['image']