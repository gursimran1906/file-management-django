import logging
import asyncio
import configparser
import datetime
import asyncio
import csv

from datetime import datetime, timezone, timedelta
import json
from pprint import pprint
import re
import math
import sys
import os
from asgiref.sync import sync_to_async
from dotenv import load_dotenv
from configparser import SectionProxy
from azure.identity.aio import ClientSecretCredential
from msgraph import GraphServiceClient
from msgraph.generated.users.users_request_builder import UsersRequestBuilder
from msgraph import GraphServiceClient
import httpx
from datetime import datetime, timedelta
import json

logger = logging.getLogger('email_sorting')


def count_words(email_body):
    # Define common closing phrases used in signatures
    closing_phrases = ['kind regards', 'best regards',
                       'yours faithfully', 'yours sincerely', 'regards']

    # Split the email body into lines
    lines = email_body.split('\n')

    # Identify and exclude lines containing signatures
    signature_found = False
    cleaned_lines = []
    for line in lines:
        if any(phrase.lower() in line.lower() for phrase in closing_phrases):
            signature_found = True
            break
        cleaned_lines.append(line)

    # If a signature is found, use only the lines before the signature
    body_without_signature = '\n'.join(
        cleaned_lines) if signature_found else email_body

    # Split the remaining text into words and count them
    word_count = len(re.findall(r'\b\w+\b', body_without_signature))

    return word_count


def calc_units_email(email_body):

    word_count = count_words(email_body)

    word_sections = word_count/300

    return math.ceil(word_sections/6)


class Graph:
    settings: SectionProxy
    client_credential: ClientSecretCredential
    app_client: GraphServiceClient

    def __init__(self, config: SectionProxy):
        self.settings = config
        client_id = self.settings['clientId']
        tenant_id = self.settings['tenantId']
        client_secret = self.settings['clientSecret']

        self.client_credential = ClientSecretCredential(
            tenant_id, client_id, client_secret)
        self.app_client = GraphServiceClient(
            self.client_credential)  # type: ignore

    async def get_app_only_token(self):
        graph_scope = 'https://graph.microsoft.com/.default'
        access_token = await self.client_credential.get_token(graph_scope)
        return access_token.token

    async def get_users(self):
        query_params = UsersRequestBuilder.UsersRequestBuilderGetQueryParameters(
            # Only request specific properties
            select=['displayName', 'id', 'mail'],
            # Get at most 25 results
            top=25,
            # Sort by display name
            orderby=['displayName']
        )
        request_config = UsersRequestBuilder.UsersRequestBuilderGetRequestConfiguration(
            query_parameters=query_params
        )

        users = await self.app_client.users.get(request_configuration=request_config)
        return users

    async def close_all_sessions(self):
        # Close all open client sessions
        httpx._client._pool_map.clear()

    async def get_shared_mailbox_messages(self, shared_mailbox_email):
        # Specify the shared mailbox's email address in the request URL
        request_url = f"https://graph.microsoft.com/v1.0/users/{shared_mailbox_email}/messages"

        fifteen_minutes_ago = datetime.utcnow() - timedelta(hours=2)
        formatted_time = fifteen_minutes_ago.strftime('%Y-%m-%dT%H:%M:%SZ')

        # You can customize the query parameters based on your requirements
        query_params = {
            '$select': 'bccRecipients, subject,body,from,receivedDateTime, webLink, toRecipients, parentFolderId',
            '$top': 2147483647,
            '$orderby': 'receivedDateTime',
            '$filter': f'receivedDateTime ge {formatted_time}'

        }

        # Set up the authentication header using the app-only token
        headers = {
            'Authorization': f'Bearer {await self.get_app_only_token()}'
        }

        # Add preference header for body content type
        headers['Prefer'] = 'outlook.body-content-type="text"'

        # Send the request to retrieve messages from the shared mailbox
        async with httpx.AsyncClient() as client:
            response = await client.get(request_url, params=query_params, headers=headers)

            # Check if the request was successful (status code 200)
            if response.status_code == 200:

                messages = response.json().get('value', [])
                return messages

            else:
                # Handle the error or raise an exception
                print(f"Error: {response.status_code}, {response.text}")
                return None

    async def get_shared_mailbox_messages_from_date(self, shared_mailbox_email, start_date):

        test = {'mail@anpsolicitors.com': [
                {
                    "id": "AQMkADJlY2U5ZTQ3LTM4NWItNDU0MS1hZTAyLTIyAGFmMjYwMmY5ODEALgAAA-czlc0P5H9Mra57SrzHVDoBAO1Ocb4hydpJpvWtwMOgkdMAAAIBDAAAAA==",
                    "displayName": "Inbox",
                },
                {
                    'displayName': 'Sent Items',
                    'id': 'AQMkADJlY2U5ZTQ3LTM4NWItNDU0MS1hZTAyLTIyAGFmMjYwMmY5ODEALgAAA-czlc0P5H9Mra57SrzHVDoBAO1Ocb4hydpJpvWtwMOgkdMAAAIBCQAAAA==',
                }
                ]}
        # Specify the shared mailbox's email address in the request URL
        request_url = f"https://graph.microsoft.com/v1.0/users/{shared_mailbox_email}/mailFolders/Inbox/messages"

        formatted_time = start_date.strftime('%Y-%m-%dT%H:%M:%SZ')

        # You can customize the query parameters based on your requirements
        query_params = {
            '$select': 'subject,body,from,receivedDateTime,webLink,toRecipients',
            '$top': 2147483647,
            '$orderby': 'receivedDateTime',
            '$filter': f'receivedDateTime ge {formatted_time}'
        }

        # Set up the authentication header using the app-only token
        headers = {
            'Authorization': f'Bearer {await self.get_app_only_token()}'
        }

        # Add preference header for body content type
        headers['Prefer'] = 'outlook.body-content-type="text"'

        # Send the request to retrieve messages from the shared mailbox
        async with httpx.AsyncClient() as client:
            response = await client.get(request_url, params=query_params, headers=headers)

            # Check if the request was successful (status code 200)
            if response.status_code == 200:
                messages = response.json().get('value', [])
                return messages
            else:
                # Handle the error or raise an exception
                print(f"Error: {response.status_code}, {response.text}")
                return None

    async def get_mail_folders_shared_mailbox(self, shared_mailbox_email):
        try:
            # Specify the shared mailbox's email address in the request URL
            request_url = f"https://graph.microsoft.com/v1.0/users/{shared_mailbox_email}/mailFolders/?top=50"

            # Set up the authentication header using the app-only token
            headers = {
                'Authorization': f'Bearer {await self.get_app_only_token()}'
            }

            # Send the request to retrieve mail folders from the shared mailbox
            async with httpx.AsyncClient() as client:
                response = await client.get(request_url, headers=headers)

                # Check if the request was successful (status code 200)
                if response.status_code == 200:
                    mail_folders = response.json().get('value', [])
                    return mail_folders
                else:
                    # Handle the error or raise an exception
                    print(f"Error: {response.status_code}, {response.text}")
                    return None
        except Exception as e:
            # Handle the error or raise an exception
            print(f"Error: {e}")
            return None

    async def get_messages_with_attachments_for_mailboxes(
        self,
        mailboxes,
        start_date=None,
        end_date=None,
    ):
        """
        Fetch messages (with attachments expanded) for the given mailboxes.
        Results are not filtered by domain or deduplicated – that is handled by callers.
        """

        base_url_template = "https://graph.microsoft.com/v1.0/users/{mailbox}/messages"

        # Build common query params
        filter_clauses = []
        if start_date is not None:
            filter_clauses.append(
                "receivedDateTime ge "
                + start_date.strftime("%Y-%m-%dT%H:%M:%SZ")
            )
        if end_date is not None:
            filter_clauses.append(
                "receivedDateTime le "
                + end_date.strftime("%Y-%m-%dT%H:%M:%SZ")
            )

        query_params = {
            "$select": ",".join(
                [
                    "id",
                    "subject",
                    "from",
                    "toRecipients",
                    "ccRecipients",
                    "bccRecipients",
                    "receivedDateTime",
                    "webLink",
                    "hasAttachments",
                    "internetMessageId",
                ]
            ),
            "$orderby": "receivedDateTime",
            "$top": "500",
        }

        if filter_clauses:
            query_params["$filter"] = " and ".join(filter_clauses)

        headers = {
            "Authorization": f"Bearer {await self.get_app_only_token()}",
            "Prefer": 'outlook.body-content-type="text"',
        }

        all_messages = []

        # Use a more generous timeout because some pages can be large/slow.
        timeout = httpx.Timeout(60.0, connect=10.0, read=60.0)

        async with httpx.AsyncClient(timeout=timeout) as client:
            for mailbox in mailboxes:
                logger.info(
                    "Starting fetch for mailbox %s (start=%s, end=%s)",
                    mailbox,
                    start_date,
                    end_date,
                )

                request_url = base_url_template.format(mailbox=mailbox)
                params = {
                    **query_params,
                    "$expand": "attachments($select=name)",
                }

                while request_url:
                    try:
                        response = await client.get(
                            request_url, params=params, headers=headers
                        )
                    except httpx.ReadTimeout:
                        logger.error(
                            "Read timeout fetching messages for mailbox %s. "
                            "Stopping pagination for this mailbox.",
                            mailbox,
                        )
                        # Stop paging this mailbox but keep what we already fetched.
                        break

                    if response.status_code != 200:
                        logger.error(
                            "Error fetching messages for %s: %s %s",
                            mailbox,
                            response.status_code,
                            response.text,
                        )
                        break

                    data = response.json()
                    messages = data.get("value", [])
                    total_for_mailbox = len(messages)
                    logger.info(
                        "Fetched %s messages in current page for mailbox %s",
                        total_for_mailbox,
                        mailbox,
                    )
                    all_messages.extend(messages)

                    # Handle pagination
                    next_link = data.get("@odata.nextLink")
                    if next_link:
                        request_url = next_link
                        params = None
                    else:
                        request_url = None

        return all_messages

    async def get_messages_for_all_mailboxes(self):

        mail_folders = {
            'mail@anpsolicitors.com': [
                {
                    "folder_id": "AQMkADJlY2U5ZTQ3LTM4NWItNDU0MS1hZTAyLTIyAGFmMjYwMmY5ODEALgAAA-czlc0P5H9Mra57SrzHVDoBAO1Ocb4hydpJpvWtwMOgkdMAAAIBDAAAAA==",
                    "display_name": "Inbox",
                },
                {
                    'display_name': 'Sent Items',
                    'folder_id': 'AQMkADJlY2U5ZTQ3LTM4NWItNDU0MS1hZTAyLTIyAGFmMjYwMmY5ODEALgAAA-czlc0P5H9Mra57SrzHVDoBAO1Ocb4hydpJpvWtwMOgkdMAAAIBCQAAAA==',
                }
            ],
            'conveyancing@anpsolicitors.com': [
                {
                    'folder_id': 'AAMkADAwOThhYmE0LTY0NjQtNDY2Ni04M2M1LWY2MWQwZTU1ODRhNgAuAAAAAAB0sEcMp6sXRZ5GrUXbNVxIAQAELNg3UJcNTrbdXAIOHOIgAAAAAAEMAAA=',
                    'display_name': 'Inbox',
                },
                {
                    'folder_id': 'AAMkADAwOThhYmE0LTY0NjQtNDY2Ni04M2M1LWY2MWQwZTU1ODRhNgAuAAAAAAB0sEcMp6sXRZ5GrUXbNVxIAQAELNg3UJcNTrbdXAIOHOIgAAAAAAEJAAA=',
                    'display_name': 'Sent Items',
                }
            ],
            'disputeresolution@anpsolicitors.com': [
                {
                    'folder_id': 'AQMkAGE3MzQyYWM2LTFkNzEtNDBiYy04YmQ1LTRhNDJkNGQ4MjdjNwAuAAADarxPYozBm0yb4YgzEd0kwgEAM0JBsGtrAIxIkNsp4BqxWVEAAAIBDAAAAA==',
                    'display_name': 'Inbox',
                },
                {
                    'folder_id': 'AQMkAGE3MzQyYWM2LTFkNzEtNDBiYy04YmQ1LTRhNDJkNGQ4MjdjNwAuAAADarxPYozBm0yb4YgzEd0kwgEAM0JBsGtrAIxIkNsp4BqxWVEAAAIBCQAAAA==',   'display_name': 'Sent Items',
                }
            ],
            'privateclient@anpsolicitors.com': [
                {
                    'folder_id': 'AQMkAGY4YTA2OWUyLWEyMgA3LTRjNDYtOTJjMC00YjA5MmZkMGJkYWQALgAAAwOw4RuddyJDnCUNs_2QDkMBAINRfQYck-hNsYqZYDCQb7sAAAIBDAAAAA==',
                    'display_name': 'Inbox',
                },
                {
                    'folder_id': 'AQMkAGY4YTA2OWUyLWEyMgA3LTRjNDYtOTJjMC00YjA5MmZkMGJkYWQALgAAAwOw4RuddyJDnCUNs_2QDkMBAINRfQYck-hNsYqZYDCQb7sAAAIBCQAAAA==',
                    'display_name': 'Sent Items',
                }
            ],
            'family@anpsolicitors.com': [
                {
                    'folder_id': 'AAMkADk1ZWY4M2E3LWYyOGItNDExOS1iYmRjLThhYTE0NTNhYWMzYwAuAAAAAABKUpm0tLzdSIoKHgceG_ivAQChLtM8EQLZSYHkW7vNNl35AAAAAAEMAAA=',
                    'display_name': 'Inbox',
                },
                {
                    'folder_id': 'AAMkADk1ZWY4M2E3LWYyOGItNDExOS1iYmRjLThhYTE0NTNhYWMzYwAuAAAAAABKUpm0tLzdSIoKHgceG_ivAQChLtM8EQLZSYHkW7vNNl35AAAAAAEJAAA=',
                    'display_name': 'Sent Items',
                }
            ],
            'riskmanagement@anpsolicitors.com': [
                {
                    'folder_id': 'AQMkADBhMmIyYjcyLTAzNDAtNDFmMy1hMzQ4LWJjMDk0NTFmYWEAODUALgAAA-k0k9cTQy5GpOdUHYcYSl0BAPHVzTRWXKpIvewct3aKRE4AAAIBDAAAAA==',
                    'display_name': 'Inbox',
                },
                {
                    'folder_id': 'AQMkADBhMmIyYjcyLTAzNDAtNDFmMy1hMzQ4LWJjMDk0NTFmYWEAODUALgAAA-k0k9cTQy5GpOdUHYcYSl0BAPHVzTRWXKpIvewct3aKRE4AAAIBCQAAAA==',
                    'display_name': 'Sent Items',
                }
            ],
        }

        all_messages = []
        fifteen_minutes_ago = datetime.now(
            timezone.utc) - timedelta(minutes=15)
        formatted_time = fifteen_minutes_ago.strftime('%Y-%m-%dT%H:%M:%SZ')

        utc_time_now = datetime.utcnow()
        print('+-'*28 + f' {utc_time_now} ' + '+-'*28)
        # You can customize the query parameters based on your requirements
        query_params = {
            '$select': 'subject,body,from,receivedDateTime,webLink,toRecipients',
            '$top': 2147483647,
            '$orderby': 'receivedDateTime',
            '$filter': f'receivedDateTime ge {formatted_time}'
        }

        # Set up the authentication header using the app-only token
        headers = {
            'Authorization': f'Bearer {await self.get_app_only_token()}'
        }

        # Add preference header for body content type
        headers['Prefer'] = 'outlook.body-content-type="text"'

        for user_email, folders in mail_folders.items():
            for folder in folders:

                folder_id = folder['folder_id']
                folder_name = folder['display_name']
                request_url = f"https://graph.microsoft.com/v1.0/users/{user_email}/mailFolders/{folder_id}/messages"

                # Send the request to retrieve messages from the shared mailbox
                async with httpx.AsyncClient() as client:
                    response = await client.get(request_url, params=query_params, headers=headers)

                    # Check if the request was successful (status code 200)
                    if response.status_code == 200:
                        print(
                            f'Getting emails from ({user_email} - {folder_name})')
                        messages = response.json().get('value', [])
                        count_msgs = len(messages)
                        print(f'---+ fetched: {count_msgs} msgs')
                        all_messages.append(messages)
                    else:
                        # Handle the error or raise an exception
                        self.send_email(
                            f"---+ Error ({user_email} - {folder_name}): {response.status_code}, {response.text}")
                        print(
                            f"---+ Error ({user_email} - {folder_name}): {response.status_code}, {response.text}")

        return all_messages

    async def send_email(self, body):

        to_email = 'info@anpsolicitors.com'
        subject = 'Error in Automatic email sorting'
        # Specify the endpoint for sending emails
        send_mail_endpoint = "https://graph.microsoft.com/v1.0/users/info@anpsolicitors.com/sendMail/"

        # Create the email payload
        email_payload = {
            "message": {
                "subject": subject,
                "body": {
                    "contentType": "Text",
                    "content": body
                },
                "toRecipients": [
                    {
                        "emailAddress": {
                            "address": to_email
                        }
                    }
                ],
                "from": {
                    "emailAddress": {
                        "name": "File Management Errors",
                        "address": "info@anpsolicitors.com"
                    }
                }
            },
            "saveToSentItems": "true"
        }

        # Set up the authentication header using the app-only token
        headers = {
            'Authorization': f'Bearer {await self.get_app_only_token()}',
            'Content-Type': 'application/json'
        }

        # Send the request to send the email
        async with httpx.AsyncClient() as client:
            response = await client.post(send_mail_endpoint, data=json.dumps(email_payload), headers=headers)

            # Check if the request was successful (status code 202 for asynchronous operations)
            if response.status_code == 202:
                print(f"Email sent successfully to {to_email}")
            else:
                # Handle the error or raise an exception
                print(
                    f"Error sending email to {to_email}: {response.status_code}, {response.text}")


class Setup:

    def __init__(self):

        # Ensure we load the .env for this app explicitly so that
        # AZURE_CLIENT_ID / SECRET / TENANT_ID are available even when
        # Django is run from the project root.
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        load_dotenv(env_path)

        azure_client_id = os.getenv('AZURE_CLIENT_ID')
        azure_client_secret = os.getenv('AZURE_CLIENT_SECRET')
        azure_tenant_id = os.getenv('AZURE_TENANT_ID')
        azure_settings = {'clientId': azure_client_id,
                          'clientSecret': azure_client_secret, 'tenantId': azure_tenant_id}

        # Use self.graph consistently
        self.graph = Graph(azure_settings)

    async def display_access_token(self):
        # Use self.graph consistently
        token = await self.graph.get_app_only_token()
        print('App-only token:', token, '\n')

    async def list_users(self):
        # Use self.graph consistently
        users_page = await self.graph.get_users()

        # Output each user's details
        if users_page and users_page.value:
            for user in users_page.value:
                print('User:', user.display_name)
                print('  ID:', user.id)
                print('  Email:', user.mail)

            # If @odata.nextLink is present
            more_available = users_page.odata_next_link is not None
            print('\nMore users available?', more_available, '\n')

    async def make_graph_call(self):
        # Use self.graph consistently
        messages = await self.graph.get_shared_mailbox_messages('mail@anpsolicitors.com')
        return messages

    async def make_graph_call_get_previous_emails(self, start_date):
        messages = await self.graph.get_shared_mailbox_messages_from_date('mail@anpsolicitors.com', start_date)
        return messages

    async def get_shared_mailbox_folder(self):
        folders = await self.graph.get_mail_folders_shared_mailbox('mail@anpsolicitors.com')
        return folders

    async def get_message_for_all_mailboxes(self):
        messages = await self.graph.get_messages_for_all_mailboxes()
        return messages

    async def send_error_email(self, body):
        await self.graph.send_email(body)


class Sorting:
    def __init__(self):
        self.name = ''

    def extract_key_and_feeearner(self, subject):
        key_match = re.search(r'[A-Z]{3}\d{7}', subject)
        feeearner_match = re.search(r'\b(\w{10})/(\d{2})\b', subject)

        key = key_match.group() if key_match else ''
        feeearner_code = feeearner_match.group(2) if feeearner_match else '0'

        return key, feeearner_code

    def convert_datetime_to_db_str(self, rcvd_time_str):

        # Convert the string to a datetime object
        rcvd_time = datetime.strptime(rcvd_time_str, '%Y-%m-%dT%H:%M:%SZ')

        # Get the UTC timezone
        utc_timezone = timezone.utc

        # Convert UTC time to local time
        local_time = rcvd_time.replace(tzinfo=utc_timezone).astimezone(tz=None)

        # Format local time as a string
        local_rcvd_time_str = local_time.strftime('%Y-%m-%d %H:%M:%S')

        return local_rcvd_time_str

    def process_email(self, email):
        try:
            # Lazy import so that using this module outside Django
            # (for CSV exports) does not require Django settings.
            from backend.utils import insert_data

            subject = email['subject']
            file_num, fee_earner = self.extract_key_and_feeearner(subject)

            from_address = email['from']
            to_recipients = email['toRecipients']
            to_1_email_address = to_recipients[0]['emailAddress']['address']

            body = email['body']['content']

            desc = ''

            rcvd_time_str = email['receivedDateTime']
            local_rcvd_time_str = rcvd_time_str

            web_link = email['webLink']

            from_address_json = json.dumps(from_address)
            to_recipients_json = json.dumps(to_recipients)

            from_email_address = from_address['emailAddress']['address']

            if 'anpsolicitors.com' in from_email_address:
                isSent = 1
            else:
                isSent = 0

            from_emails_to_avoid = ['no-reply@access.service.gov.uk', 'no-reply@royalmail.com', 'news-q2@law360.com',
                                    'info@lexisnexis.co.uk', 'MicrosoftExchange329e71ec88ae4615bbc36ab6ce41109e@anpsolicitors.com']
            if 'postmaster' in from_email_address or from_email_address in from_emails_to_avoid:
                return False

            if subject == 'Login verification code':
                return False

            if 'anpsolicitors.com' in from_email_address and 'anpsolicitors.com' in to_1_email_address:
                return False

            insert_data(file_num, from_address_json, to_recipients_json, desc, subject, body,
                        web_link, isSent, local_rcvd_time_str, calc_units_email(body), fee_earner)
            return True

        except KeyError as e:
            print(f"Error processing email in process method: {str(e)}")
            return False

    async def get_emails(self):
        setup_instance = Setup()

        try:
            emails = await setup_instance.make_graph_call()
            num_of_emails_processed = 0
            num_of_email_added_to_db = 0
            time_now = datetime.utcnow()
            print(
                f'*********************************Email sorting at {time_now} *********************************************')
            for email in emails:
                try:
                    result = await self.process_email(email)
                    if result:
                        num_of_email_added_to_db += 1
                    num_of_emails_processed += 1
                except re.error as regex_error:
                    print(f"Error processing email: {str(regex_error)}")
            print(f"{num_of_email_added_to_db} emails added to db")
            print(f"Processed {num_of_emails_processed} emails")

        except Exception as e:
            print(f"Error fetching emails: {str(e)}")

    async def get_emails_from_all_mailboxes(self):
        setup_instance = Setup()

        try:
            emails = await setup_instance.get_message_for_all_mailboxes()

            num_of_emails_processed = 0
            num_of_email_added_to_db = 0
            time_now = datetime.utcnow()

            print(
                f'*********************************Email sorting at {time_now} *********************************************')

            for user_emails in emails:
                for email in user_emails:
                    try:
                        result = await sync_to_async(self.process_email)(email)
                        if result:
                            num_of_email_added_to_db += 1
                        num_of_emails_processed += 1
                    except re.error as regex_error:
                        print(f"Error processing email: {regex_error}")
                        await setup_instance.send_error_email(f"Dear ND, \n Error processing email: {regex_error} . \n Kind regards\nGB")
            print(f"{num_of_email_added_to_db} emails added to db")
            print(f"Processed {num_of_emails_processed} emails")

        except Exception as e:
            print(f"Error fetching emails: {str(e)}")
            await setup_instance.send_error_email(f"Dear ND, \n Error fetching emails: {e}\n Kind regards\nGB")

    async def diplay_access_token(self):
        setup_instance = Setup()
        token = await setup_instance.display_access_token()
        print(token)

    async def get_all_emails_from_date(self):
        setup_instance = Setup()
        start_date = datetime(2024, 2, 2)

        try:
            emails = await setup_instance.make_graph_call_get_previous_emails(start_date)
            num_of_emails_processed = 0

            for email in emails:
                result = await self.process_email(email)
                if result:
                    num_of_emails_processed += 1

            print(f"Processed {num_of_emails_processed} emails")

        except Exception as e:
            print(f"Error fetching emails: {str(e)}")

    async def get_shared_mailbox_folders(self):
        setup_instance = Setup()

        try:
            folders = await setup_instance.get_shared_mailbox_folder()

            pprint(folders)
        except Exception as e:
            print(e)

    def convert_datetime_to_db_str(self, rcvd_time_str):

        # Convert the string to a datetime object
        rcvd_time = datetime.strptime(rcvd_time_str, '%Y-%m-%dT%H:%M:%SZ')

        # Get the UTC timezone
        utc_timezone = timezone.utc

        # Convert UTC time to local time
        local_time = rcvd_time.replace(tzinfo=utc_timezone).astimezone(tz=None)

        # Format local time as a string
        local_rcvd_time_str = local_time.strftime('%Y-%m-%d %H:%M:%S')

        return local_rcvd_time_str
    # Run the event loop to execute the async function

    async def send_email(self):
        setup_instance = Setup()

        try:
            await setup_instance.send_error_email(body='Test')

        except Exception as e:
            print(e)

    async def export_domain_emails_to_csv(
        self,
        target_domains,
        output_csv_path,
        mailboxes=None,
        start_date=None,
        end_date=None,
    ):
        """
        Export all emails in/out for the given domains and mailboxes to a CSV file.

        - Avoids duplicates by using internetMessageId.
        - Description: "Email from xxx to yyy" (yyy can be a comma‑separated list).
        - Date format: dd/mm/yyyy HH:MM (local time).
        - Attachments: semicolon‑separated list of attachment names.
        """

        # Default mailboxes to check if none are provided.
        # NOTE: Explicitly exclude mail@anpsolicitors.com as requested.
        if mailboxes is None:
            mailboxes = [
                "disputeresolution@anpsolicitors.com",
                "n.dhillon@anpsolicitors.com",
                "j.phillips@anpsolicitors.com",
            ]

        # Normalise domains (lowercase, strip whitespace)
        target_domains = [d.strip().lower() for d in target_domains if d.strip()]
        if not target_domains:
            raise ValueError("target_domains must contain at least one domain")

        setup_instance = Setup()

        # Collect messages mailbox‑by‑mailbox so we can:
        # - Apply per‑mailbox date ranges
        # - Survive failures on individual mailboxes
        all_messages = []

        for mailbox in mailboxes:
            if mailbox == "mail@anpsolicitors.com":
                continue

            # Per‑mailbox date rules:
            # - n.dhillon & j.phillips: only 2021‑01‑01 to 2022‑12‑31
            # - everyone else: use provided start_date/end_date
            if mailbox in {
                "n.dhillon@anpsolicitors.com",
                "j.phillips@anpsolicitors.com",
            }:
                mb_start = datetime(2021, 1, 1)
                mb_end = datetime(2022, 12, 31, 23, 59, 59)
            else:
                mb_start = start_date
                mb_end = end_date

            try:
                mailbox_messages = await setup_instance.graph.get_messages_with_attachments_for_mailboxes(
                    mailboxes=[mailbox],
                    start_date=mb_start,
                    end_date=mb_end,
                )
                all_messages.extend(mailbox_messages)
            except Exception as fetch_err:
                logger.error(
                    "Error fetching messages for mailbox %s: %s",
                    mailbox,
                    fetch_err,
                )

        seen_ids = set()
        rows = []

        def email_domain(address):
            if not address or "@" not in address:
                return None
            return address.split("@", 1)[1].lower()

        for msg in all_messages:
            internet_id = msg.get("internetMessageId") or msg.get("id")
            if not internet_id:
                continue
            if internet_id in seen_ids:
                continue
            seen_ids.add(internet_id)

            from_obj = msg.get("from") or {}
            from_email = (
                ((from_obj.get("emailAddress") or {}).get("address"))
                if from_obj
                else ""
            ) or ""

            to_recipients = msg.get("toRecipients") or []
            cc_recipients = msg.get("ccRecipients") or []
            bcc_recipients = msg.get("bccRecipients") or []

            all_recips = []
            for collection in (to_recipients, cc_recipients, bcc_recipients):
                for r in collection:
                    addr = (r.get("emailAddress") or {}).get("address")
                    if addr:
                        all_recips.append(addr)

            # Decide if this message concerns any of the target domains
            addresses_to_check = [from_email] + all_recips
            if not any(
                email_domain(addr) in target_domains for addr in addresses_to_check
            ):
                continue

            # Build description
            unique_recips = sorted(set(all_recips))
            recip_part = ", ".join(unique_recips) if unique_recips else "Unknown"
            from_part = from_email or "Unknown"
            description = f"Email from {from_part} to {recip_part}"

            # Format date
            rcvd_str = msg.get("receivedDateTime")
            if not rcvd_str:
                continue
            try:
                # Handle both Z and offset formats
                if rcvd_str.endswith("Z"):
                    dt = datetime.fromisoformat(rcvd_str.replace("Z", "+00:00"))
                else:
                    dt = datetime.fromisoformat(rcvd_str)
                local_dt = dt.astimezone()
                date_str = local_dt.strftime("%d/%m/%Y %H:%M")
            except Exception:
                # Fallback: keep original if parsing fails
                date_str = rcvd_str

            # Attachments
            attachments = msg.get("attachments") or []
            attachment_names = [
                a.get("name")
                for a in attachments
                if isinstance(a, dict) and a.get("name")
            ]
            attachments_str = "; ".join(attachment_names)

            rows.append([description, date_str, attachments_str])

        # Always try to save whatever we have, even if processing raised earlier.
        try:
            pass
        finally:
            if rows:
                output_dir = os.path.dirname(output_csv_path)
                if output_dir:
                    os.makedirs(output_dir, exist_ok=True)

                with open(output_csv_path, mode="w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(["Description", "Date", "Attachments"])
                    writer.writerows(rows)

                logger.info(
                    "Exported %s email rows to CSV at %s",
                    len(rows),
                    output_csv_path,
                )

    async def export_client_subject_emails_to_csv(
        self,
        client_keywords,
        output_csv_path,
        mailboxes=None,
        start_date=None,
        end_date=None,
    ):
        """
        Export emails where the subject mentions any of the given client
        names/keywords to a CSV file.

        - Uses same CSV format as domain export.
        - Avoids duplicates by internetMessageId.
        - Case-insensitive match on subject.
        """

        # Default mailboxes to check if none are provided
        # NOTE: Explicitly exclude mail@anpsolicitors.com as requested.
        if mailboxes is None:
            mailboxes = [
                "disputeresolution@anpsolicitors.com",
                "n.dhillon@anpsolicitors.com",
                "j.phillips@anpsolicitors.com",
            ]

        # Normalise keywords
        keywords = [k.strip().lower() for k in client_keywords if k.strip()]
        if not keywords:
            raise ValueError("client_keywords must contain at least one value")

        # Court-related domains to restrict results to
        court_domains = {
            "justice.gov.uk",
            "hmcts.net",
            "judiciary.uk",
        }

        setup_instance = Setup()

        all_messages = []
        for mailbox in mailboxes:
            if mailbox == "mail@anpsolicitors.com":
                continue

            if mailbox in {
                "n.dhillon@anpsolicitors.com",
                "j.phillips@anpsolicitors.com",
            }:
                mb_start = datetime(2021, 1, 1)
                mb_end = datetime(2022, 12, 31, 23, 59, 59)
            else:
                mb_start = start_date
                mb_end = end_date

            try:
                mailbox_messages = await setup_instance.graph.get_messages_with_attachments_for_mailboxes(
                    mailboxes=[mailbox],
                    start_date=mb_start,
                    end_date=mb_end,
                )
                all_messages.extend(mailbox_messages)
            except Exception as fetch_err:
                logger.error(
                    "Error fetching client-subject messages for mailbox %s: %s",
                    mailbox,
                    fetch_err,
                )

        seen_ids = set()
        rows = []

        def email_domain(address: str | None) -> str | None:
            if not address or "@" not in address:
                return None
            return address.split("@", 1)[1].lower()

        for msg in all_messages:
            internet_id = msg.get("internetMessageId") or msg.get("id")
            if not internet_id:
                continue
            if internet_id in seen_ids:
                continue
            seen_ids.add(internet_id)

            subject = (msg.get("subject") or "").lower()
            if not subject:
                continue

            # Include only if any keyword appears in subject
            if not any(kw in subject for kw in keywords):
                continue

            from_obj = msg.get("from") or {}
            from_email = (
                ((from_obj.get("emailAddress") or {}).get("address"))
                if from_obj
                else ""
            ) or ""

            to_recipients = msg.get("toRecipients") or []
            cc_recipients = msg.get("ccRecipients") or []
            bcc_recipients = msg.get("bccRecipients") or []

            all_recips = []
            for collection in (to_recipients, cc_recipients, bcc_recipients):
                for r in collection:
                    addr = (r.get("emailAddress") or {}).get("address")
                    if addr:
                        all_recips.append(addr)

            # Additionally require that at least one address is a court-domain address
            addresses_to_check = [from_email] + all_recips
            if not any(
                (email_domain(addr) in court_domains)
                for addr in addresses_to_check
                if addr
            ):
                continue

            unique_recips = sorted(set(all_recips))
            recip_part = ", ".join(unique_recips) if unique_recips else "Unknown"
            from_part = from_email or "Unknown"
            description = f"Email from {from_part} to {recip_part}"

            rcvd_str = msg.get("receivedDateTime")
            if not rcvd_str:
                continue
            try:
                if rcvd_str.endswith("Z"):
                    dt = datetime.fromisoformat(rcvd_str.replace("Z", "+00:00"))
                else:
                    dt = datetime.fromisoformat(rcvd_str)
                local_dt = dt.astimezone()
                date_str = local_dt.strftime("%d/%m/%Y %H:%M")
            except Exception:
                date_str = rcvd_str

            attachments = msg.get("attachments") or []
            attachment_names = [
                a.get("name")
                for a in attachments
                if isinstance(a, dict) and a.get("name")
            ]
            attachments_str = "; ".join(attachment_names)

            rows.append([description, date_str, attachments_str])

        try:
            pass
        finally:
            if rows:
                output_dir = os.path.dirname(output_csv_path)
                if output_dir:
                    os.makedirs(output_dir, exist_ok=True)

                with open(output_csv_path, mode="w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(["Description", "Date", "Attachments"])
                    writer.writerows(rows)

                logger.info(
                    "Exported %s client-subject email rows to CSV at %s",
                    len(rows),
                    output_csv_path,
                )


def get_emails_and_store():
    try:
        logger.info('Starting email sync job')
        sorting_obj = Sorting()
        asyncio.run(sorting_obj.get_emails_from_all_mailboxes())
        logger.info('Email sync job completed successfully')
    except Exception as e:
        logger.error(f'Error in email sync job: {str(e)}', exc_info=True)
        raise


def export_emails_for_domains_to_csv(
    target_domains,
    output_csv_path,
    mailboxes=None,
    start_date=None,
    end_date=None,
):
    """
    Convenience synchronous wrapper so you can call this from
    a Django shell or a management command without dealing with asyncio.
    """
    sorting_obj = Sorting()
    asyncio.run(
        sorting_obj.export_domain_emails_to_csv(
            target_domains=target_domains,
            output_csv_path=output_csv_path,
            mailboxes=mailboxes,
            start_date=start_date,
            end_date=end_date,
        )
    )


def export_client_subject_emails_to_csv(
    client_keywords,
    output_csv_path,
    mailboxes=None,
    start_date=None,
    end_date=None,
):
    """
    Sync wrapper for export_client_subject_emails_to_csv so it can be called
    easily from Django shell / management commands.
    """
    sorting_obj = Sorting()
    asyncio.run(
        sorting_obj.export_client_subject_emails_to_csv(
            client_keywords=client_keywords,
            output_csv_path=output_csv_path,
            mailboxes=mailboxes,
            start_date=start_date,
            end_date=end_date,
        )
    )


def remove_log_file():
    try:
        from django.conf import settings
        logs_dir = settings.LOGS_DIR if hasattr(
            settings, 'LOGS_DIR') else os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(logs_dir, "email_job.log")
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(
                f"Email job log file {file_path} has been successfully removed on {datetime.now()}.")
        else:
            logger.warning(
                f"The email job log file {file_path} does not exist.")
    except Exception as e:
        logger.error(f'Error removing log file: {str(e)}', exc_info=True)
