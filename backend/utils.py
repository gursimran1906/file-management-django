from .models import MatterEmails, WIP
from users.models import CustomUser
from django.db import connection
from django.contrib.contenttypes.models import ContentType
from .models import Modifications
import os
import re
from datetime import datetime


def insert_data(file_number, sender, receiver, description, subject, body, link, is_sent, rcvd_time, units, fee_earner_code):
    try:
        if file_number != None:
            file = WIP.objects.filter(file_number=file_number).first()
        else:
           file =  None
        
        user = CustomUser.objects.filter(id=fee_earner_code).first()
        email = MatterEmails(
            file_number=file ,
            sender=sender,
            receiver=receiver,
            description=description,
            subject=subject,
            body=body,
            link=link,
            is_sent=is_sent,
            time=rcvd_time,
            units=units,
            fee_earner=user
        )
        
        # Save the object to the database
        email.save()

        print("Data inserted successfully")

    except Exception as e:
        
        print(f"Error in inserting: {e}")
        print('in email','sender: '+sender , 'receiver: '+receiver, rcvd_time)



 
def create_modification(user, modified_obj, changes=None):
    """
    Utility method to create a modification instance.
    
    Args:
        user (CustomUser): The user who made the modification.
        modified_obj (Model): The object being modified.
        changes (dict): Optional. Changes made to the object (default is None).
        
    Returns:
        Modifications: The created Modifications instance.
    """
    content_type = ContentType.objects.get_for_model(modified_obj)
    
    modification = Modifications.objects.create(
        modified_by=user,
        content_type=content_type,
        object_id=modified_obj.pk,
        modified_obj=modified_obj,
        changes=changes
    )
    
    return modification


def parse_bundle_filename(filename):
    """Extract description and date from a PDF filename.

    Supported prefixes (date then description):
    - YYYY-MM-DD Letter to client.pdf
    - YYYYMMDD Letter to client.pdf
    - DD-MM-YYYY or DD.MM.YYYY Letter to client.pdf
    Separator after the date may be a space, hyphen, or underscore.
    """
    basename = os.path.splitext(os.path.basename(filename))[0]
    patterns = (
        (r'^(\d{4})-(\d{2})-(\d{2})[\s_-]+(.+)$', lambda m: (m.group(1), m.group(2), m.group(3), m.group(4))),
        (r'^(\d{4})(\d{2})(\d{2})[\s_-]+(.+)$', lambda m: (m.group(1), m.group(2), m.group(3), m.group(4))),
        (r'^(\d{2})[-.](\d{2})[-.](\d{4})[\s_-]+(.+)$', lambda m: (m.group(3), m.group(2), m.group(1), m.group(4))),
    )
    for pattern, extract in patterns:
        match = re.match(pattern, basename, re.IGNORECASE)
        if not match:
            continue
        year, month, day, description = extract(match)
        try:
            doc_date = datetime(int(year), int(month), int(day)).date()
        except ValueError:
            continue
        return description.replace('_', ' ').strip(), doc_date

    return basename.replace('_', ' ').strip(), None
       
