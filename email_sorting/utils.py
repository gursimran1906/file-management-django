import asyncio
import configparser
import datetime
import asyncio

from datetime import datetime, timezone, timedelta
import json
from pprint import pprint
import re
import math
import sys
import os
from asgiref.sync import sync_to_async
from dotenv import load_dotenv
from backend.utils import insert_data
from configparser import SectionProxy
from azure.identity.aio import ClientSecretCredential
from msgraph import GraphServiceClient
from msgraph.generated.users.users_request_builder import UsersRequestBuilder
from msgraph import GraphServiceClient
import httpx
from datetime import datetime, timedelta
import json

def count_words(email_body):
    # Define common closing phrases used in signatures
    closing_phrases = ['kind regards', 'best regards', 'yours faithfully', 'yours sincerely', 'regards']

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
    body_without_signature = '\n'.join(cleaned_lines) if signature_found else email_body

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

        self.client_credential = ClientSecretCredential(tenant_id, client_id, client_secret)
        self.app_client = GraphServiceClient(self.client_credential) # type: ignore

    async def get_app_only_token(self):
        graph_scope = 'https://graph.microsoft.com/.default'
        access_token = await self.client_credential.get_token(graph_scope)
        return access_token.token
    
    async def get_users(self):
        query_params = UsersRequestBuilder.UsersRequestBuilderGetQueryParameters(
            # Only request specific properties
            select = ['displayName', 'id', 'mail'],
            # Get at most 25 results
            top = 25,
            # Sort by display name
            orderby= ['displayName']
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

        test = {'mail@anpsolicitors.com':[
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
        
    async def get_messages_for_all_mailboxes(self):

        mail_folders = {
            'mail@anpsolicitors.com':[
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
        fifteen_minutes_ago = datetime.utcnow() - timedelta(minutes=15)
        formatted_time = fifteen_minutes_ago.strftime('%Y-%m-%dT%H:%M:%SZ')

       

        utc_time_now = datetime.utcnow()
        print('+-'*28 +f' {utc_time_now} '+ '+-'*28)
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
                        print(f'Getting emails from ({user_email} - {folder_name})')
                        messages = response.json().get('value', [])
                        count_msgs = len(messages)
                        print(f'---+ fetched: {count_msgs} msgs')
                        all_messages.append(messages)
                    else:
                        # Handle the error or raise an exception
                        self.send_email(f"---+ Error ({user_email} - {folder_name}): {response.status_code}, {response.text}")
                        print(f"---+ Error ({user_email} - {folder_name}): {response.status_code}, {response.text}")
                        
        return all_messages
   
    async def send_email(self, body):

        to_email ='info@anpsolicitors.com'
        subject= 'Error in Automatic email sorting'
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
                print(f"Error sending email to {to_email}: {response.status_code}, {response.text}")


class Setup:

    def __init__(self):
        
        load_dotenv()
       
        azure_client_id = os.getenv('AZURE_CLIENT_ID')
        azure_client_secret = os.getenv('AZURE_CLIENT_SECRET')
        azure_tenant_id = os.getenv('AZURE_TENANT_ID')
        azure_settings = {'clientId':azure_client_id,'clientSecret': azure_client_secret,'tenantId':azure_tenant_id}
        
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
       
    async def make_graph_call_get_previous_emails(self,start_date):
        messages = await self.graph.get_shared_mailbox_messages_from_date('mail@anpsolicitors.com',start_date)
        return messages

    async def get_shared_mailbox_folder(self):
        folders = await self.graph.get_mail_folders_shared_mailbox('mail@anpsolicitors.com')
        return folders
    
    async def get_message_for_all_mailboxes(self):
        messages = await self.graph.get_messages_for_all_mailboxes()
        return messages
    
    async def send_error_email(self,body):
        await self.graph.send_email(body)


class Sorting:
    def __init__(self):
        self.name = ''

    def extract_key_and_feeearner(self,subject):
        key_match = re.search(r'[A-Z]{3}\d{7}', subject)
        feeearner_match = re.search(r'\b(\w{10})/(\d{2})\b', subject)

        key = key_match.group() if key_match else ''
        feeearner_code = feeearner_match.group(2) if feeearner_match else '0'

        return key, feeearner_code

    def convert_datetime_to_db_str(self,rcvd_time_str):
    

        # Convert the string to a datetime object
        rcvd_time = datetime.strptime(rcvd_time_str, '%Y-%m-%dT%H:%M:%SZ')

        # Get the UTC timezone
        utc_timezone = timezone.utc

        # Convert UTC time to local time
        local_time = rcvd_time.replace(tzinfo=utc_timezone).astimezone(tz=None)

        # Format local time as a string
        local_rcvd_time_str = local_time.strftime('%Y-%m-%d %H:%M:%S')

        return local_rcvd_time_str

    def process_email(self,email):
        try:
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
            
            insert_data(file_num, from_address_json, to_recipients_json, desc, subject, body, web_link, isSent, local_rcvd_time_str, calc_units_email(body), fee_earner) 
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
            print(f'*********************************Email sorting at {time_now} *********************************************')
            for email in emails:
                try:
                    result = await self.process_email(email)
                    if result:
                        num_of_email_added_to_db  += 1
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

            print(f'*********************************Email sorting at {time_now} *********************************************')
        
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

    def convert_datetime_to_db_str(self,rcvd_time_str):
    

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

def get_emails_and_store():
    sorting_obj = Sorting()
    asyncio.run(sorting_obj.get_emails_from_all_mailboxes())


def remove_log_file():

    current_directory = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(current_directory, "email_job.log")
    if os.path.exists(file_path):
        os.remove(file_path)
        
        (f"{file_path} has been successfully removed on {datetime.now()}.")
    else:
        print(f"The file {file_path} does not exist.")
