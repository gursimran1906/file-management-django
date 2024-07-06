from django import template
import re
from django.utils.safestring import mark_safe
register = template.Library()
import json

@register.filter(name='get_type')
def get_type(value):
    return str(type(value))



 
 
 
@register.filter(name='jsonify')
def jsonify(data):
    
    if isinstance(data, dict):
        return data
    elif data == '':
        return {}
    else:
        return json.loads(data)
    
@register.filter(name='add_list_class')
def add_list_class(value):
    # Use regex to add or modify the class attribute in <ol> tags
    def replace_ol(match):
        tag = match.group(0)
        if 'class=' in tag:
            return re.sub(r'class="([^"]*)"', r'class="\1 list-decimal"', tag)
        else:
            return tag[:-1] + ' class="list-decimal">'
    
    updated_html = re.sub(r'<ol[^>]*>', replace_ol, value)
    return mark_safe(updated_html)