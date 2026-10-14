"""Index, summary and listing files written into every export."""
import csv
import html as html_mod
import io

INDEX_COLUMNS = [
    'No', 'Date', 'Time', 'Direction', 'From', 'To', 'Cc', 'Subject', 'Attachments',
    'Attachment count', 'Found in', 'Found by', 'Matched', 'Flags', 'Email PDF',
    'Enclosures folder', 'Original .eml',
]
EXCLUDED_COLUMNS = ['Date', 'Time', 'Direction', 'From', 'To', 'Subject', 'Type', 'Found in']

# Keys of a result row (stored on the export for the in-app table), in INDEX_COLUMNS order.
ROW_KEYS = [
    'no', 'date', 'time', 'direction', 'from', 'to', 'cc', 'subject', 'attachments',
    'attachment_count', 'found_in', 'found_by', 'matched', 'flags', 'pdf_name',
    'enc_dir', 'eml_name',
]


def row_values(row):
    return [str(row.get(key, '') or '') for key in ROW_KEYS]


def csv_bytes(header, rows):
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator='\r\n')
    writer.writerow(header)
    writer.writerows(rows)
    return buf.getvalue().encode('utf-8-sig')


def index_csv(rows):
    return csv_bytes(INDEX_COLUMNS, [row_values(r) for r in rows])


def flagged_csv(rows):
    return csv_bytes(INDEX_COLUMNS, [row_values(r) for r in rows if r.get('flags')])


def excluded_csv(excluded_rows):
    return csv_bytes(EXCLUDED_COLUMNS, [
        [r.get('date', ''), r.get('time', ''), r.get('direction', ''), r.get('from', ''),
         r.get('to', ''), r.get('subject', ''), r.get('type', ''), r.get('found_in', '')]
        for r in excluded_rows])


def index_html(title, summary_lines, rows):
    head = ''.join(f'<th>{html_mod.escape(c)}</th>' for c in INDEX_COLUMNS)
    body = []
    for row in rows:
        cls = ' class="flag"' if row.get('flags') else ''
        cells = []
        for key, value in zip(ROW_KEYS, row_values(row)):
            escaped = html_mod.escape(value)
            if key == 'pdf_name' and value:
                escaped = f'<a href="{html_mod.escape(value)}">{escaped}</a>'
            elif key == 'eml_name' and value:
                escaped = f'<a href="originals/{html_mod.escape(value)}">{escaped}</a>'
            elif key == 'enc_dir' and value:
                escaped = f'<a href="{html_mod.escape(value)}/">{escaped}</a>'
            cells.append(f'<td>{escaped}</td>')
        body.append(f"<tr{cls}>{''.join(cells)}</tr>")
    summary = ''.join(f'<p>{html_mod.escape(line)}</p>' for line in summary_lines)
    doc = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'><title>" + html_mod.escape(title) + '</title><style>'
        'body{font-family:Carlito,Calibri,Arial,sans-serif;font-size:13px;margin:20px}'
        'table{border-collapse:collapse;width:100%}'
        'th,td{border:1px solid #bbb;padding:4px 6px;vertical-align:top;text-align:left}'
        'th{background:#eee;position:sticky;top:0}tr.flag td{background:#fff3cd}'
        'td:nth-child(8){min-width:220px}</style></head><body>'
        f'<h2>{html_mod.escape(title)}</h2>{summary}<table><thead><tr>{head}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table></body></html>"
    )
    return doc.encode('utf-8')


def summary_text(lines):
    return ('\r\n'.join(lines) + '\r\n').encode('utf-8')
