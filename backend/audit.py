"""Audit logging helpers built on the Modifications model."""

from .utils import create_modification


def format_audit_value(value):
    if value is None:
        return ''
    return str(value)


def build_form_field_changes(duplicate_obj, saved_obj, changed_fields, exclude=None):
    """Build a Modifications.changes dict from form changed_data."""
    exclude = exclude or frozenset()
    changes = {}
    model = saved_obj.__class__
    for field in changed_fields:
        if field in exclude:
            continue
        label = field
        try:
            model_field = model._meta.get_field(field)
            label = str(model_field.verbose_name)
        except Exception:
            label = field.replace('_', ' ').title()
        changes[field] = {
            'old_value': format_audit_value(getattr(duplicate_obj, field)),
            'new_value': format_audit_value(getattr(saved_obj, field)),
            '_label': label,
        }
    return changes


def log_created(user, obj, summary, details=None):
    changes = {
        'created': {
            'old_value': '',
            'new_value': summary,
        }
    }
    if details:
        changes.update(details)
    return create_modification(user, obj, changes)


def log_field_change(user, obj, field, old_value, new_value):
    return create_modification(
        user,
        obj,
        {
            field: {
                'old_value': format_audit_value(old_value),
                'new_value': format_audit_value(new_value),
            }
        },
    )


def log_deleted_on_parent(user, parent_obj, entity_type, snapshot):
    return create_modification(
        user,
        parent_obj,
        {
            f'{entity_type}_deleted': {
                'old_value': snapshot,
                'new_value': '(deleted)',
            }
        },
    )


def snapshot_key_date(key_date):
    date_type = key_date.get_date_type_display()
    time_part = f' at {key_date.time.strftime("%H:%M")}' if key_date.time else ''
    return f'{date_type}: {key_date.title} ({key_date.date}{time_part})'


def snapshot_key_document(document):
    client_name = str(
        document.client) if document.client_id else 'Unknown client'
    doc_type = document.document_type or document.get_category_display()
    return f'{client_name} - {document.get_category_display()} - {doc_type}'


def audit_client_key_document_formset(user, formset, client):
    """Record create/update/delete events from a ClientKeyDocument formset."""
    for deleted in formset.deleted_objects:
        log_deleted_on_parent(
            user,
            client,
            'key_document',
            snapshot_key_document(deleted),
        )

    for form in formset.forms:
        if not getattr(form, 'cleaned_data', None) or form.cleaned_data.get('DELETE'):
            continue
        if not form.has_changed():
            continue

        if not form.initial.get('id'):
            log_created(
                user,
                form.instance,
                snapshot_key_document(form.instance),
            )
            continue

        changes = {}
        for field in form.changed_data:
            changes[field] = {
                'old_value': format_audit_value(form.initial.get(field)),
                'new_value': format_audit_value(form.cleaned_data.get(field)),
            }
        if changes:
            create_modification(user, form.instance, changes)


def log_bundle_event(user, bundle, event, **details):
    """Record a bundle lifecycle event (section/doc changes, finalize, etc.)."""
    changes = {
        'event': {
            'old_value': '',
            'new_value': event,
        }
    }
    for key, value in details.items():
        if isinstance(value, dict) and ('old_value' in value or 'new_value' in value):
            changes[key] = {
                'old_value': format_audit_value(value.get('old_value', '')),
                'new_value': format_audit_value(value.get('new_value', '')),
            }
        else:
            changes[key] = {
                'old_value': '',
                'new_value': format_audit_value(value),
            }
    return create_modification(user, bundle, changes)
