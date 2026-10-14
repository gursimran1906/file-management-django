"""Synchronous Microsoft Graph mail client (application permissions).

Uses the same app registration as the email ingester (AZURE_* in .env), exposed
through settings.MAIL_GRAPH_*. Only reads mail; never sends.
"""
import logging
import re
import time
from datetime import datetime, timezone

import requests
from django.conf import settings

from .classify import EXPAND_MESSAGE_CLASS

logger = logging.getLogger('backend')

GRAPH = 'https://graph.microsoft.com/v1.0'
SELECT = (
    'id,internetMessageId,subject,receivedDateTime,sentDateTime,hasAttachments,'
    'from,toRecipients,ccRecipients,bccRecipients,parentFolderId,isDraft,webLink'
)


class GraphMailError(Exception):
    def __init__(self, status, code, message):
        super().__init__(f'HTTP {status} {code}: {message}')
        self.status = status
        self.code = code


def parse_graph_dt(value):
    if not value:
        return None
    value = value.strip()
    if value.endswith('Z'):
        value = value[:-1] + '+00:00'
    value = re.sub(r'(\.\d{6})\d+', r'\1', value)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def iso_utc(dt):
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def addr_only(entry):
    if not entry:
        return ''
    return ((entry.get('emailAddress', entry) or {}).get('address') or '').strip().lower()


def fmt_addr(entry):
    if not entry:
        return ''
    data = entry.get('emailAddress', entry) or {}
    name = (data.get('name') or '').strip()
    address = (data.get('address') or '').strip()
    if name and address and name.lower() != address.lower():
        return f'{name} <{address}>'
    return address or name


def fmt_addrs(entries):
    return '; '.join(filter(None, (fmt_addr(e) for e in (entries or []))))


class GraphMail:
    def __init__(self, tenant_id, client_id, client_secret, session=None):
        if not (tenant_id and client_id and client_secret):
            raise GraphMailError(0, 'config', 'Microsoft Graph mail credentials are not configured')
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.session = session or requests.Session()
        self._token = None
        self._expires = 0.0
        self._folder_cache = {}
        self._name_cache = {}

    @classmethod
    def from_settings(cls):
        return cls(settings.MAIL_GRAPH_TENANT_ID, settings.MAIL_GRAPH_CLIENT_ID,
                   settings.MAIL_GRAPH_CLIENT_SECRET)

    # ------------------------------------------------------------------ transport
    def token(self):
        if self._token and time.time() < self._expires - 120:
            return self._token
        response = self.session.post(
            f'https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token',
            data={
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'grant_type': 'client_credentials',
                'scope': 'https://graph.microsoft.com/.default',
            },
            timeout=30,
        )
        body = response.json()
        if response.status_code != 200:
            description = body.get('error_description', '').split('Trace ID')[0].strip()
            raise GraphMailError(response.status_code, body.get('error', 'token_error'), description)
        self._token = body['access_token']
        self._expires = time.time() + int(body.get('expires_in', 3600))
        return self._token

    def _request(self, method, url, params=None, json=None):
        last = None
        for attempt in range(7):
            headers = {'Authorization': f'Bearer {self.token()}'}
            response = self.session.request(method, url, params=params, json=json,
                                            headers=headers, timeout=180)
            last = response
            if response.status_code in (429, 500, 502, 503, 504):
                wait = response.headers.get('Retry-After')
                time.sleep(min(float(wait) if wait else 2 ** attempt, 90))
                continue
            if response.status_code == 401 and attempt == 0:
                self._token = None
                continue
            return response
        return last

    @staticmethod
    def _raise(response):
        try:
            error = response.json().get('error', {})
        except ValueError:
            error = {}
        raise GraphMailError(response.status_code, error.get('code', 'error'),
                             error.get('message', response.text[:200]))

    def get_json(self, url, params=None):
        response = self._request('GET', url, params)
        if response.status_code != 200:
            self._raise(response)
        return response.json()

    def post_json(self, url, payload):
        response = self._request('POST', url, json=payload)
        if response.status_code not in (200, 201):
            self._raise(response)
        return response.json()

    def get_all(self, url, params):
        out = []
        page = self.get_json(url, params)
        out.extend(page.get('value', []))
        while page.get('@odata.nextLink'):
            page = self.get_json(page['@odata.nextLink'])
            out.extend(page.get('value', []))
        return out

    def get_bytes(self, url):
        response = self._request('GET', url)
        if response.status_code != 200:
            self._raise(response)
        return response.content

    # ------------------------------------------------------------------ mail
    def user_display_name(self, mailbox):
        if mailbox not in self._name_cache:
            try:
                data = self.get_json(f'{GRAPH}/users/{mailbox}', {'$select': 'displayName'})
                self._name_cache[mailbox] = data.get('displayName') or mailbox
            except GraphMailError:
                self._name_cache[mailbox] = mailbox
        return self._name_cache[mailbox]

    def folder_name(self, mailbox, folder_id):
        if not folder_id:
            return 'Unknown folder'
        key = (mailbox, folder_id)
        if key not in self._folder_cache:
            try:
                data = self.get_json(f'{GRAPH}/users/{mailbox}/mailFolders/{folder_id}',
                                     {'$select': 'displayName'})
                self._folder_cache[key] = data.get('displayName') or 'Unknown folder'
            except GraphMailError:
                self._folder_cache[key] = 'Unknown folder'
        return self._folder_cache[key]

    def search_kql(self, mailbox, kql, start, end):
        """$search over every folder; dates filtered locally ($search cannot combine with $filter)."""
        url = f'{GRAPH}/users/{mailbox}/messages'
        params = {'$search': f'"{kql}"', '$select': SELECT, '$top': 250, '$expand': EXPAND_MESSAGE_CLASS}
        try:
            results = self.get_all(url, params)
        except GraphMailError as exc:
            if exc.status != 400:
                raise
            params.pop('$expand')
            results = self.get_all(url, params)
        if len(results) >= 1000:
            logger.warning('Graph search for %s returned 1000+ results; results may be capped', mailbox)
        kept = []
        for message in results:
            received = parse_graph_dt(message.get('receivedDateTime'))
            if received and start <= received < end:
                kept.append(message)
        return kept

    def search_participant(self, mailbox, address, start, end):
        """Messages in [start, end) where `address` is a participant.

        Tries the exact $filter on sender/recipients first; Graph rejects it on some
        mailboxes, in which case a participant $search is used. Callers must still
        apply the strict participant check to what comes back.
        """
        url = f'{GRAPH}/users/{mailbox}/messages'
        escaped = address.replace("'", "''")
        date_part = f'receivedDateTime ge {iso_utc(start)} and receivedDateTime lt {iso_utc(end)}'
        clauses = [
            f"from/emailAddress/address eq '{escaped}'",
            f"toRecipients/any(r:r/emailAddress/address eq '{escaped}')",
            f"ccRecipients/any(r:r/emailAddress/address eq '{escaped}')",
            f"bccRecipients/any(r:r/emailAddress/address eq '{escaped}')",
        ]
        try:
            results = []
            for clause in clauses:
                results += self.get_all(url, {
                    '$filter': f'{date_part} and {clause}', '$select': SELECT,
                    '$top': 100, '$expand': EXPAND_MESSAGE_CLASS})
            return results
        except GraphMailError as exc:
            if exc.status != 400:
                raise
        return self.search_kql(mailbox, f'participants:{address}', start, end)

    def list_window(self, mailbox, start, end):
        """Every message received in [start, end]. Meant for narrow windows."""
        url = f'{GRAPH}/users/{mailbox}/messages'
        return self.get_all(url, {
            '$filter': f'receivedDateTime ge {iso_utc(start)} and receivedDateTime le {iso_utc(end)}',
            '$select': SELECT, '$top': 100, '$expand': EXPAND_MESSAGE_CLASS})

    def get_message(self, mailbox, message_id):
        return self.get_json(f'{GRAPH}/users/{mailbox}/messages/{message_id}',
                             {'$select': SELECT, '$expand': EXPAND_MESSAGE_CLASS})

    def get_mime(self, mailbox, message_id):
        return self.get_bytes(f'{GRAPH}/users/{mailbox}/messages/{message_id}/$value')

    def translate_exchange_ids(self, mailbox, input_ids, source_type='ewsId', target_type='restId'):
        """Convert ids between Exchange formats. Returns {source: target}."""
        out = {}
        for offset in range(0, len(input_ids), 100):
            chunk = input_ids[offset:offset + 100]
            data = self.post_json(f'{GRAPH}/users/{mailbox}/translateExchangeIds', {
                'inputIds': chunk, 'sourceIdType': source_type, 'targetIdType': target_type})
            for entry in data.get('value', []):
                if entry.get('sourceId') and entry.get('targetId'):
                    out[entry['sourceId']] = entry['targetId']
        return out
