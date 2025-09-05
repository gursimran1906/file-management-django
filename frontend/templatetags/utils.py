import json
from django import template
import re
import os
from django.utils.safestring import mark_safe
register = template.Library()


@register.filter(name='get_type')
def get_type(value):
    return str(type(value))


@register.filter(name='jsonify')
def jsonify(data):

    if isinstance(data, dict):
        return data
    elif isinstance(data, list):
        return data
    elif data == '' or data == None:
        return {}
    else:
        return json.loads(data)


@register.filter(name='add_list_class')
def add_list_class(value):
    # Function to add or modify class for <ol> tags
    def replace_ol(match):
        tag = match.group(0)
        if 'class=' in tag:
            return re.sub(r'class="([^"]*)"', r'class="\1 ql-list-ordered"', tag)
        else:
            return tag[:-1] + ' class="ql-list-ordered">'

    # Function to add or modify class for <ul> tags
    def replace_ul(match):
        tag = match.group(0)
        if 'class=' in tag:
            return re.sub(r'class="([^"]*)"', r'class="\1 ql-list-bullet"', tag)
        else:
            return tag[:-1] + ' class="ql-list-bullet">'

    # Apply replacements
    updated_html = re.sub(r'<ol[^>]*>', replace_ol, value)
    updated_html = re.sub(r'<ul[^>]*>', replace_ul, updated_html)

    return mark_safe(updated_html)


@register.filter(name='zip')
def zip_lists(a, b):
    return zip(a, b)


@register.filter(name='basename')
def basename(value):
    """Extract the filename from a file path"""
    if hasattr(value, 'name'):
        # If it's a file field, get the name
        return os.path.basename(value.name)
    elif isinstance(value, str):
        # If it's a string path
        return os.path.basename(value)
    else:
        return str(value)
