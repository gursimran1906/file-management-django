import json

from django.test import TestCase
from django.urls import reverse

from users.models import CustomUser

from ..models import NextWork


class AdminPoolTaskTests(TestCase):
    def setUp(self):
        self.creator = CustomUser.objects.create_user(
            username='abc',
            email='abc@example.com',
            first_name='A',
            last_name='Creator',
            password='password',
            max_holidays_in_year=20,
        )
        self.claimer = CustomUser.objects.create_user(
            username='xyz',
            email='xyz@example.com',
            first_name='X',
            last_name='Claimer',
            password='password',
            max_holidays_in_year=20,
        )
        self.client.force_login(self.creator)

    def _create_task(self, payload):
        return self.client.post(
            reverse('create_task'),
            data=json.dumps(payload),
            content_type='application/json',
        )

    def test_create_admin_pool_task_is_unassigned(self):
        response = self._create_task({
            'task': 'Shared admin chore',
            'is_admin_pool': True,
            'urgency': 'medium',
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])

        task = NextWork.objects.get(task='Shared admin chore')
        self.assertTrue(task.is_admin_pool)
        self.assertIsNone(task.person_id)
        self.assertEqual(task.status, 'to_do')
        self.assertEqual(task.created_by_id, self.creator.id)

    def test_task_with_no_person_falls_into_pool(self):
        response = self._create_task({'task': 'No assignee', 'person': ''})
        self.assertEqual(response.status_code, 200)

        task = NextWork.objects.get(task='No assignee')
        self.assertTrue(task.is_admin_pool)
        self.assertIsNone(task.person_id)

    def test_pool_task_appears_only_in_pool_column(self):
        NextWork.objects.create(
            task='Pool item', is_admin_pool=True, created_by=self.creator,
            status='to_do',
        )
        response = self.client.post(
            reverse('load_initial_tasks'),
            data=json.dumps({'count': 5, 'filter_created_by_me': False}),
            content_type='application/json',
        )
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['total_counts']['admin_pool'], 1)
        self.assertEqual(data['total_counts']['to_do'], 0)

    def test_claim_task_assigns_to_claimer_and_leaves_pool(self):
        task = NextWork.objects.create(
            task='Claim me', is_admin_pool=True, created_by=self.creator,
            status='to_do',
        )
        self.client.force_login(self.claimer)
        response = self.client.post(
            reverse('claim_task'),
            data=json.dumps({'task_id': task.id}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['success'])
        # The moved task is returned so the UI can render the new card.
        self.assertEqual(payload['task']['id'], task.id)
        self.assertFalse(payload['task']['is_admin_pool'])

        task.refresh_from_db()
        self.assertFalse(task.is_admin_pool)
        self.assertEqual(task.person_id, self.claimer.id)
        self.assertEqual(task.status, 'to_do')

    def test_claim_rejects_non_pool_task(self):
        task = NextWork.objects.create(
            task='Personal', person=self.creator, created_by=self.creator,
            status='to_do',
        )
        response = self.client.post(
            reverse('claim_task'),
            data=json.dumps({'task_id': task.id}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['success'])
        task.refresh_from_db()
        self.assertEqual(task.person_id, self.creator.id)
        self.assertFalse(task.is_admin_pool)

    def test_release_sends_personal_task_back_to_pool(self):
        task = NextWork.objects.create(
            task='Give it back', person=self.creator, created_by=self.creator,
            status='to_do',
        )
        response = self.client.post(
            reverse('release_task'),
            data=json.dumps({'task_id': task.id}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['task']['id'], task.id)
        self.assertTrue(payload['task']['is_admin_pool'])

        task.refresh_from_db()
        self.assertTrue(task.is_admin_pool)
        self.assertIsNone(task.person_id)
        self.assertEqual(task.status, 'to_do')

    def test_release_rejects_in_progress_task(self):
        # In-progress tasks must be moved back to "To do" before they can be
        # returned to the pool (mirrors the UI, which hides "To pool" there).
        task = NextWork.objects.create(
            task='Mid-flight', person=self.creator, created_by=self.creator,
            status='in_progress',
        )
        response = self.client.post(
            reverse('release_task'),
            data=json.dumps({'task_id': task.id}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['success'])
        task.refresh_from_db()
        self.assertFalse(task.is_admin_pool)
        self.assertEqual(task.person_id, self.creator.id)

    def test_release_rejects_other_users_task(self):
        task = NextWork.objects.create(
            task='Not yours', person=self.claimer, created_by=self.claimer,
            status='to_do',
        )
        # self.creator is logged in and is neither person nor creator.
        response = self.client.post(
            reverse('release_task'),
            data=json.dumps({'task_id': task.id}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['success'])
        task.refresh_from_db()
        self.assertFalse(task.is_admin_pool)
        self.assertEqual(task.person_id, self.claimer.id)
