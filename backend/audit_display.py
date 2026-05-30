"""Presentation helpers for matter activity / audit logs."""

import json
import re
from collections import Counter

FIELD_LABELS = {
    'created': 'Record',
    'event': 'Event',
    'action': 'Action',
    'name': 'Name',
    'bundle_name': 'Bundle name',
    'file_number': 'File number',
    'date_type': 'Date type',
    'title': 'Title',
    'date': 'Date',
    'time': 'Time',
    'location': 'Location',
    'notes': 'Notes',
    'comments': 'Comments',
    'category': 'Category',
    'document_type': 'Document type',
    'document_reference': 'Reference',
    'issue_date': 'Issue date',
    'expiry_date': 'Expiry date',
    'verified_on': 'Verified on',
    'section': 'Section',
    'document': 'Document',
    'description': 'Description',
    'page_order': 'Page order',
    'date_sort': 'Sort order',
    'document_count': 'Documents',
    'key_date_deleted': 'Key date removed',
    'key_document_deleted': 'Key document removed',
    'bundle_deleted': 'Bundle removed',
    'status': 'Status',
    'amount': 'Amount',
    'total_due_left': 'Amount due',
    'reason': 'Reason',
    'heading': 'Section heading',
}

LOG_TYPE_META = {
    'file_info': {'label': 'File', 'group': 'matter'},
    'client_info': {'label': 'Client', 'group': 'matter'},
    'authorised_party_info': {'label': 'Authorised party', 'group': 'matter'},
    'other_side_info': {'label': 'Other side', 'group': 'matter'},
    'next_work': {'label': 'Next work', 'group': 'matter'},
    'last_work': {'label': 'Last work', 'group': 'matter'},
    'key_date': {'label': 'Key date', 'group': 'compliance'},
    'key_document': {'label': 'Key document', 'group': 'compliance'},
    'risk_assessment': {'label': 'Risk assessment', 'group': 'compliance'},
    'ongoing_monitoring': {'label': 'Ongoing monitoring', 'group': 'compliance'},
    'matter_file_review': {'label': 'File review', 'group': 'compliance'},
    'bundle': {'label': 'Bundle', 'group': 'documents'},
    'email': {'label': 'Email', 'group': 'correspondence'},
    'letter': {'label': 'Letter', 'group': 'correspondence'},
    'attendance_note': {'label': 'Attendance note', 'group': 'notes'},
    'invoice': {'label': 'Invoice', 'group': 'finance'},
    'credit_note': {'label': 'Credit note', 'group': 'finance'},
    'pmts_slip': {'label': 'Slip', 'group': 'finance'},
    'green_slip': {'label': 'Green slip', 'group': 'finance'},
}

FILTER_GROUPS = [
    ('matter', 'Matter'),
    ('compliance', 'Compliance'),
    ('documents', 'Documents'),
    ('finance', 'Finance'),
    ('correspondence', 'Correspondence'),
    ('notes', 'Notes'),
]

ACTION_LABELS = {
    'created': 'Created',
    'updated': 'Updated',
    'deleted': 'Deleted',
    'event': 'Logged',
}

DEFAULT_TYPE_META = {'label': 'Activity', 'group': 'matter'}


def humanize_field_name(field_name):
    if field_name in FIELD_LABELS:
        return FIELD_LABELS[field_name]
    label = str(field_name).replace('_', ' ').strip()
    return label[:1].upper() + label[1:] if label else str(field_name)


def format_log_user(user):
    if user is None or user == '':
        return 'System'
    if isinstance(user, str):
        return user
    full_name = getattr(user, 'get_full_name', lambda: '')()
    if full_name and full_name.strip():
        return full_name.strip()
    return getattr(user, 'username', str(user))


def normalize_changes(changes):
    if changes is None:
        return {}
    if isinstance(changes, str):
        try:
            changes = json.loads(changes)
        except (json.JSONDecodeError, TypeError):
            return {}
    if not isinstance(changes, dict):
        return {}
    if 'prev' in changes and 'after' in changes:
        return {
            'record': {
                'old_value': 'Previous version',
                'new_value': 'Updated record',
            }
        }
    return changes


def _display_change_value(value):
    if value is None or value == '' or value == 'None':
        return '(empty)'
    text = str(value)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) > 160:
        text = text[:157] + '...'
    return text


def build_change_items(changes):
    """Normalise Modifications.changes into template-friendly rows."""
    changes = normalize_changes(changes)
    if not changes:
        return []

    items = []
    for field, value in changes.items():
        if field.startswith('_'):
            continue
        if isinstance(value, dict) and value.get('_label'):
            label = value['_label']
        else:
            label = humanize_field_name(field)
        if isinstance(value, dict):
            old_key = 'old_value' if 'old_value' in value else 'old'
            new_key = 'new_value' if 'new_value' in value else 'new'
            old_display = _display_change_value(value.get(old_key))
            new_display = _display_change_value(value.get(new_key))
            kind = 'update'
            if old_display == '(empty)' and new_display != '(empty)':
                kind = 'add'
            elif new_display in ('(deleted)', '(empty)') and old_display != '(empty)':
                kind = 'remove'
            items.append({
                'label': label,
                'old_display': old_display,
                'new_display': new_display,
                'kind': kind,
            })
        else:
            items.append({
                'label': label,
                'old_display': '',
                'new_display': _display_change_value(value),
                'kind': 'add',
            })
    return items


def infer_log_action(log_entry, changes_list=None):
    desc = (log_entry.get('desc') or '').lower()
    changes_list = changes_list or log_entry.get('changes_list') or []

    for change in changes_list:
        label = (change.get('label') or '').lower()
        new_display = (change.get('new_display') or '').lower()
        if change.get('kind') == 'remove' or 'removed' in label or 'deleted' in label:
            return 'deleted'
        if change.get('kind') == 'add' and label in ('record', 'action', 'event'):
            if 'deleted' in new_display:
                return 'deleted'
            return 'created'

    if any(token in desc for token in (' deleted', ' removed', 'deleted.', 'removed.')):
        return 'deleted'
    if any(token in desc for token in (' created', ' added', ' completed', ' entered', ' done.')):
        return 'created'
    if changes_list:
        return 'updated'
    return 'event'


def enrich_log_entry(log_entry):
    entry = dict(log_entry)
    meta = LOG_TYPE_META.get(entry.get('type'), DEFAULT_TYPE_META)
    if not entry.get('changes_list') and entry.get('changes'):
        entry['changes_list'] = build_change_items(entry['changes'])

    action = infer_log_action(entry, entry.get('changes_list'))
    entry['type_label'] = meta['label']
    entry['filter_group'] = meta['group']
    entry['action'] = action
    entry['action_label'] = ACTION_LABELS.get(action, ACTION_LABELS['event'])
    entry['user_display'] = format_log_user(entry.get('user'))
    entry['change_count'] = len(entry.get('changes_list') or [])
    return entry


def enrich_file_logs(logs):
    enriched = [enrich_log_entry(log) for log in logs]
    type_counts = Counter(log['type'] for log in enriched)
    group_counts = Counter(log['filter_group'] for log in enriched)
    filter_options = []
    for group_key, group_label in FILTER_GROUPS:
        count = group_counts.get(group_key, 0)
        if count:
            filter_options.append({
                'key': group_key,
                'label': group_label,
                'count': count,
            })
    return enriched, {
        'groups': filter_options,
        'total': len(enriched),
        'types': dict(type_counts),
    }
