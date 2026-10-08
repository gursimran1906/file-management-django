"""Responsible fee earner aliases.

Some "fee earners" are pseudo users used to group files rather than people,
e.g. ``DC`` (Debt Collection). A file assigned to such a user keeps that
``fee_earner`` (that is how the files are filtered), but the *person*
responsible for it - who signs things off, whose dashboard it appears on and
who it is reported under - is someone else.

The mapping is the ``RESPONSIBLE_FEE_EARNER_ALIASES`` setting: a JSON object
of staff codes, e.g. ``{"DC": "ND"}``. Use ``WIP.responsible_fee_earner`` in
sign-off, dashboard and reporting code; keep the raw ``fee_earner`` for
"which files are DC files" style filters and displays.
"""

import json

from django.conf import settings
from django.db.models import Q

from users.models import CustomUser


def responsible_aliases():
    """{pseudo staff code: responsible staff code}, upper-cased, never raises."""
    raw = getattr(settings, 'RESPONSIBLE_FEE_EARNER_ALIASES', '') or ''
    if isinstance(raw, dict):
        data = raw
    else:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return {}
    if not isinstance(data, dict):
        return {}
    aliases = {}
    for code, target in data.items():
        code = str(code or '').strip().upper()
        target = str(target or '').strip().upper()
        if code and target and code != target:
            aliases[code] = target
    return aliases


def responsible_username(username):
    """The staff code responsible for files owned by `username` (itself if none)."""
    if not username:
        return username
    return responsible_aliases().get(str(username).upper(), username)


def responsible_fee_earner(user):
    """The person responsible for files owned by `user` (the user itself if none)."""
    if user is None:
        return None
    target = responsible_aliases().get((user.username or '').upper())
    if not target:
        return user
    return CustomUser.objects.filter(username__iexact=target).first() or user


def responsible_user_ids(user):
    """Ids of every user whose files count as `user`'s own.

    That is the user plus any pseudo fee earners aliased to them, so
    ``WIP.objects.filter(fee_earner_id__in=responsible_user_ids(nd))`` returns
    ND's files and the DC files ND is responsible for.
    """
    if user is None:
        return []
    ids = {user.id}
    codes = [code for code, target in responsible_aliases().items()
             if target == (user.username or '').upper()]
    if codes:
        query = Q()
        for code in codes:
            query |= Q(username__iexact=code)
        ids.update(CustomUser.objects.filter(query).values_list('id', flat=True))
    return sorted(ids)


def responsible_user_ids_for_id(user_id):
    """Like `responsible_user_ids` but from a raw id (e.g. a GET parameter)."""
    try:
        user = CustomUser.objects.filter(pk=int(user_id)).first()
    except (TypeError, ValueError):
        return []
    return responsible_user_ids(user) if user else []
