"""Completed tasks are dated on the day they were completed, not the day the
task was raised, so they land on the right day in "My time" and on the matter."""
import importlib
import json
from datetime import timedelta

from django.apps import apps
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from ..models import LastWork, NextWork
from .tests_staff_timeline import (
    WED,
    aware,
    events_of,
    make_client,
    make_matter,
    make_user,
)


class CompletedTaskDateTests(TestCase):
    def setUp(self):
        self.user = make_user('ABC')
        self.matter = make_matter('ABC0010001', make_client('Alice Client'))
        self.today = timezone.localdate()
        self.raised_on = self.today - timedelta(days=10)

    def raise_task(self, text='File the claim form', **kwargs):
        return NextWork.objects.create(
            file_number=self.matter, person=self.user, task=text,
            date=self.raised_on, created_by=self.user, **kwargs)

    def complete(self, task):
        task.status = 'completed'
        task.save()
        return task

    def test_completing_a_task_dates_it_on_the_completion_day(self):
        task = self.complete(self.raise_task())
        entry = LastWork.objects.get()
        self.assertEqual(entry.date, self.today)
        self.assertNotEqual(entry.date, task.date)
        self.assertEqual(
            (entry.file_number, entry.person, entry.task, entry.created_by),
            (self.matter, self.user, 'File the claim form', self.user))

    def test_task_raised_already_completed_is_dated_today(self):
        self.raise_task(status='completed')
        self.assertEqual(LastWork.objects.get().date, self.today)

    def test_resaving_or_editing_a_completed_task_does_not_duplicate(self):
        task = self.complete(self.raise_task())
        task.save()
        task.task = 'File the claim form (amended)'
        task.save()
        self.assertEqual(LastWork.objects.count(), 1)

    def test_reopening_and_recompleting_the_same_day_keeps_one_entry(self):
        task = self.complete(self.raise_task())
        task.status = 'to_do'
        task.save()
        self.assertEqual(LastWork.objects.count(), 1)
        self.complete(task)
        self.assertEqual(LastWork.objects.count(), 1)

    def test_timeline_shows_the_task_on_the_day_it_was_completed(self):
        self.complete(self.raise_task())
        events, data = events_of(self.user, view='day', anchor=self.today)
        self.assertEqual([e['title'] for e in events], ['File the claim form'])
        self.assertEqual(data['totals']['counts']['task'], 1)
        events, data = events_of(self.user, view='day', anchor=self.raised_on)
        self.assertEqual(events, [])
        self.assertEqual(data['totals']['counts']['task'], 0)

    def test_status_endpoint_returns_the_completed_entry(self):
        task = self.raise_task()
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('update_task_status'),
            data=json.dumps({'task_id': task.id, 'status': 'completed'}),
            content_type='application/json')
        payload = response.json()
        entry = LastWork.objects.get()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['task']['id'], entry.id)
        self.assertEqual(payload['task']['date'], self.today.isoformat())
        self.assertEqual(payload['task']['edit_url'], reverse('edit_last_work', args=[entry.id]))


class RedateCompletedTasksMigrationTests(TestCase):
    def setUp(self):
        self.user = make_user('ABC')
        self.matter = make_matter('ABC0010001', make_client('Alice Client'))
        module = importlib.import_module('backend.migrations.0069_redate_completed_tasks')
        self.redate = module.redate_completed_tasks

    def test_rows_copied_from_the_task_date_move_to_the_completion_day(self):
        monday = WED - timedelta(days=2)
        NextWork.objects.create(file_number=self.matter, person=self.user,
                                task='Chase the other side', date=monday, status='completed')
        auto = LastWork.objects.get()
        # Replay the old behaviour: dated on the task date, created on completion.
        LastWork.objects.filter(pk=auto.pk).update(date=monday, timestamp=aware(WED, '16:45'))
        manual = LastWork.objects.create(file_number=self.matter, person=self.user,
                                         task='Manually recorded work', date=monday)
        LastWork.objects.filter(pk=manual.pk).update(timestamp=aware(WED, '17:00'))

        self.redate(apps, None)

        self.assertEqual(LastWork.objects.get(pk=auto.pk).date, WED)
        self.assertEqual(LastWork.objects.get(pk=manual.pk).date, monday)

    def test_nothing_to_do_without_completed_tasks(self):
        manual = LastWork.objects.create(file_number=self.matter, person=self.user,
                                         task='Manually recorded work', date=WED)
        self.redate(apps, None)
        self.assertEqual(LastWork.objects.get(pk=manual.pk).date, WED)
