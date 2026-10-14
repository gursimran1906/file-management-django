"""Correspondence export: a matter's emails from Microsoft 365, rendered as
Outlook memo-style PDFs with enclosures, indexed and stored per matter.

Modules
-------
classify    read/delivery receipt detection from the Exchange message class or MIME
mime        original message parsing: body, inline images, enclosures
render      memo-style HTML -> PDF (WeasyPrint in a child process), enclosure appending
graph_mail  sync Microsoft Graph mail client (app-only)
mailboxes   which mailboxes/addresses/keywords an export starts from
discovery   builds the candidate list for a matter (system-filed + client addresses)
index       index/summary files written into the export
storage     writes export files to the configured storage (SharePoint or local media)
runner      runs discovery and export jobs, with progress on the model
sharing     Microsoft share links for the finished zip
cron        django-crontab entry point
"""
