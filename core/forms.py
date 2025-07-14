# core/forms.py
from django import forms
from .models import UserProfile

class SearchForm(forms.Form):
    query = forms.CharField(label='Search User', max_length=100)
    def clean_query(self):
        query = self.cleaned_data.get('query')
        if not query:
            raise forms.ValidationError("Search query cannot be empty.")
        return query

class ProfilePicForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ['profile_pic']