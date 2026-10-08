"""HTTP layer for the compliance stats page and its drill-down lists.

The numbers and rows come from ``backend.compliance_stats``; this module only
reads the request and hands the result to a template or ``render_report``.
"""

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse

from .compliance_stats import METRICS, Snapshot, build_compliance_stats, build_metric_detail
from .views import render_report


@login_required
def compliance_stats(request):
    return render(request, 'compliance_stats.html', build_compliance_stats())


@login_required
def compliance_stats_detail(request, metric_key):
    metric = METRICS.get(metric_key)
    if metric is None:
        raise Http404('Unknown compliance metric')

    fee_earner = request.GET.get('fee_earner', '').strip()
    reason = request.GET.get('reason', '').strip()
    q = request.GET.get('q', '').strip()
    if reason and reason not in metric.reasons:
        reason = ''

    snapshot = Snapshot()
    columns, rows, fee_earner_options = build_metric_detail(
        metric, fee_earner=fee_earner, reason=reason, q=q, snapshot=snapshot)

    filters = [
        {'name': 'q', 'label': 'Search', 'type': 'text', 'value': q,
         'placeholder': 'File, client or matter…'},
        {'name': 'fee_earner', 'label': 'Fee earner', 'type': 'select', 'value': fee_earner,
         'options': [{'value': '', 'label': 'All'}] + fee_earner_options},
    ]
    if metric.reasons:
        filters.append({
            'name': 'reason', 'label': 'Why', 'type': 'select', 'value': reason,
            'options': [{'value': '', 'label': 'All'}] + [
                {'value': key, 'label': label.capitalize()} for key, label in metric.reasons.items()
            ],
        })

    return render_report(
        request,
        slug=f'compliance_{metric.key}',
        title=metric.label,
        description=metric.help_for(snapshot),
        filters=filters, columns=columns, rows=rows,
        back_url=reverse('compliance_stats'), back_label='Compliance stats',
    )
