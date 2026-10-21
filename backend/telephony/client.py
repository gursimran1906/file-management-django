"""Sync Microsoft Graph client for the Teams PSTN call-log report APIs.

App-only (client-credentials) auth against Microsoft Graph, mirroring
``backend.sharepoint.client``. Two report functions are polled:

* ``GET /communications/callRecords/getPstnCalls(fromDateTime=..,toDateTime=..)``
  — Calling Plan / Operator Connect calls (``pstnCallLogRow``).
* ``GET /communications/callRecords/getDirectRoutingCalls(...)`` — Direct
  Routing calls (``directRoutingLogRow``).

Both accept a date range (max 90 days), return tabular rows under ``value``, and
page via an ``@odata.nextLink``. Requires the application permission
``CallRecord-PstnCalls.Read.All`` (admin consent).
"""
import logging
import time
from datetime import timezone as dt_timezone

import httpx
from azure.identity import ClientSecretCredential
from django.conf import settings

logger = logging.getLogger(__name__)

MAX_RETRIES = 5


class TelephonyError(Exception):
    """Raised when the Graph call-log API returns an unrecoverable error."""


def _api_timestamp(dt):
    """RFC3339 UTC ``Z`` timestamp Graph's date-range functions expect."""
    return dt.astimezone(dt_timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


class TeamsGraphClient:
    """Poll the Graph call-log report functions with app-only credentials."""

    def __init__(self):
        tenant = settings.TEAMS_AZURE_TENANT_ID
        client_id = settings.TEAMS_AZURE_CLIENT_ID
        secret = settings.TEAMS_AZURE_CLIENT_SECRET
        if not (tenant and client_id and secret):
            raise TelephonyError(
                'Teams Graph credentials are not configured (set TEAMS_AZURE_* '
                'or the fallback AZURE_* / SHAREPOINT_AZURE_* variables).')
        self.credential = ClientSecretCredential(
            tenant_id=tenant, client_id=client_id, client_secret=secret)
        self.base = settings.TEAMS_GRAPH_BASE.rstrip('/')

    def _token(self):
        return self.credential.get_token(
            'https://graph.microsoft.com/.default').token

    def _headers(self):
        return {'Authorization': f'Bearer {self._token()}'}

    def _request(self, url):
        delay = 1
        for attempt in range(MAX_RETRIES):
            with httpx.Client(timeout=120.0) as client:
                response = client.get(url, headers=self._headers())

            if response.status_code == 429 or (
                    response.status_code == 503 and attempt < MAX_RETRIES - 1):
                retry_after = int(response.headers.get('Retry-After', delay))
                logger.warning(
                    'Teams Graph throttled (%s), retry in %ss (attempt %s)',
                    response.status_code, retry_after, attempt + 1)
                time.sleep(retry_after)
                delay = min(delay * 2, 60)
                continue

            return response

        raise TelephonyError('Teams Graph request failed after retries')

    def _iter_report(self, function_name, from_dt, to_dt, page_limit=200):
        """Yield rows from a call-log report function, following @odata.nextLink."""
        url = (f'{self.base}/communications/callRecords/{function_name}'
               f'(fromDateTime={_api_timestamp(from_dt)},'
               f'toDateTime={_api_timestamp(to_dt)})')
        for _ in range(page_limit):
            response = self._request(url)
            if response.status_code == 404:
                return  # function not available on this endpoint, or no data
            if not response.is_success:
                raise TelephonyError(
                    f'Teams Graph {response.status_code} on {function_name}: '
                    f'{response.text[:300]}')
            data = response.json() or {}
            for row in data.get('value', []):
                yield row
            url = data.get('@odata.nextLink')
            if not url:
                return
        logger.warning('%s hit page_limit (%s) — coverage may be truncated.',
                       function_name, page_limit)

    def get_pstn_calls(self, from_dt, to_dt):
        return self._iter_report('getPstnCalls', from_dt, to_dt)

    def get_direct_routing_calls(self, from_dt, to_dt):
        return self._iter_report('getDirectRoutingCalls', from_dt, to_dt)

    def test_connection(self, from_dt, to_dt, *, pstn=True, direct_routing=True):
        """Count rows in a small window per enabled endpoint, importing nothing."""
        counts = {}
        if pstn:
            counts['pstn'] = sum(1 for _ in self.get_pstn_calls(from_dt, to_dt))
        if direct_routing:
            counts['directRouting'] = sum(
                1 for _ in self.get_direct_routing_calls(from_dt, to_dt))
        return counts
