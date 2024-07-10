import psycopg2
import json
from datetime import datetime
import pytz



conn = psycopg2.connect(database="filemanagement",
                        user="anp",
                        password="Mango@ANP290!",
                        host="192.168.5.251",
                        port="5432")
cur = conn.cursor()

def strip_time(time_str):
    return time_str[:8]

def convert_text_to_quill_format(text):
    # Wrap the text in a basic HTML paragraph tag
    html_content = f"<p>{text.strip().replace('\\n', '<br>')}</p>"
    
    # Create Quill Delta format
    quill_data = {
        "ops": [
            {"insert": text.strip()}
        ]
    }
    
    # Convert to JSON string
    delta_json = json.dumps(quill_data)
    
    # Create the final dictionary with both delta and html
    result = {
        "delta": delta_json,
        "html": html_content
    }
    
    # Convert to JSON string
    return json.dumps(result)

def validate_date(date_str):
    try:
        if date_str == "0000-00-00" or date_str == None:
            return datetime.now().strftime('%Y-%m-%d') # or replace with a default date like '1970-01-01'
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return None

def validate_boolean(boolean_number):
    return boolean_number == '1'

def validate_timestamp(date_str, timezone_str='UTC+1'):
    timezone = pytz.timezone('Europe/Berlin') if timezone_str == 'UTC+1' else pytz.timezone(timezone_str)
    
    if date_str in ["0000-00-00", "0000-00-00 00:00:00"]:
        current_timestamp = datetime.now(timezone)
        return current_timestamp.strftime('%Y-%m-%d %H:%M:%S.%f%z')
    
    try:
        dt = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
        dt = timezone.localize(dt)
        return dt.strftime('%Y-%m-%d %H:%M:%S.%f%z')
    except ValueError:
        return None

def amount_invoiced(json_data):
   
    if json_data == '{}':
        return json.dumps({})
    
    data = json.loads(json_data)

    updated_data = {}
   
    for outer_key, inner_dict in data.items():
        
        updated_inner_dict = {}
        inner_dict = json.loads(inner_dict)
        for key, value in inner_dict.items():
            if key == "Amount":
                updated_key = "amt_invoiced"
            elif key == "BalanceLeft":
                updated_key = "balance_left"
            else:
                updated_key = key
            updated_inner_dict[updated_key] = value
        
        updated_data[outer_key] = updated_inner_dict

    return json.dumps(updated_data, indent=4)

def amount_allocated(json_data):
    
    if json_data == '{}':
        return json.dumps({})
    
    
    data = json.loads(json_data)
    
    for key in data:
        # Load the nested JSON
        nested_data = json.loads(data[key])
       
        data[key] = nested_data["Amount"]
    
    # Convert back to JSON string
    return json.dumps(data)

def get_wip_id_by_file_number(file_number):
   
    try:
        # Query to fetch the ID based on file_number
        query = "SELECT id FROM backend_wip WHERE file_number = %s"
        cur.execute(query, (file_number,))
        
        
        row = cur.fetchone()
        
        if row:
            wip_id = row[0]
            return wip_id
        else:
            return None
        
    except psycopg2.Error as e:
        print(f"Error retrieving ID: {e}")
        return None
 
def get_matter_type_id(type):
   
    try:
        
        query = "SELECT id FROM backend_mattertype WHERE type = %s"
        cur.execute(query, (type,))
        
        row = cur.fetchone()
        
        if row:
            wip_id = row[0]
            return wip_id
        else:
            return None
        
    except psycopg2.Error as e:
        print(f"Error retrieving ID: {e}")
        return None
      
def get_location_id(location):

    try:
        
        query = "SELECT id FROM backend_filelocation WHERE location = %s"
        cur.execute(query, (location,))
        
        
        row = cur.fetchone()
        
        if row:
            wip_id = row[0]
            return wip_id
        else:
            return None
        
    except psycopg2.Error as e:
        print(f"Error retrieving ID: {e}")
        return None
   

def get_fee_earner_id(fee_earner):
    try:
        query = "SELECT id FROM users_customuser WHERE username = %s"
        cur.execute(query, (fee_earner,))
        
        
        row = cur.fetchone()
        
        if row:
            wip_id = row[0]
            return wip_id
        else:
            return None
        
    except psycopg2.Error as e:
        print(f"Error retrieving ID: {e}")
        return None
  

def get_fee_earner_initials_based_upon_id(fee_earner_id):
    fee_earners = {
        "1": "SD",
        "2": "ND",
        "3": "GM",
        "4": "JP",
        "5": "CP",
        "6": "TR",
        "7": "GB",
        "8": "AF",
        "9": "RY",
        "10": "KS",
        "11": "TRN",
        "12": "JPN"
    }
    return fee_earners.get(str(fee_earner_id), "ID not found")

def add_hourly_rates():
    data = [
        (1, 'Paralegal', '195.00', True),
        (2, 'Senior Fee Earner', '295.00', True),
        (3, 'Associate', '275.00', True),
        (4, 'Solicitors up to 4yr PQE', '250.00', True),
        (5, 'Trainee', '225.00', True),
        ]
    insert_query = """
        INSERT INTO users_rate (
           id, "desc", hourly_amount, is_active, timestamp
        ) VALUES (%s, %s,%s,%s,%s )
    """
    for item in data:
        try:
            cur.execute(insert_query, (
                item[0],
                item[1],
                item[2],
                item[3],
                validate_timestamp('0000-00-00 00:00:00')
            ))
            conn.commit()
        except psycopg2.Error as e:
            print("Error inserting row:", e)
            conn.rollback()
            continue
        except ValueError as ve:
            print("Value error:", ve)
            continue
    print('RATES ADDED')

def add_users():
    data = [
        (1, "pbkdf2_sha256$720000$aixlVBV0VfPbqk0aWfmLRp$LYYp8Cq3GDoKQ0bx4WlJ+8PQvlTIWzkYDpUkrKbYg+g=", 
         "2024-07-07 22:04:29+01", False, False, True, "2024-07-07 22:04:29+01", "SD", "s.dhillon@anpsolicitors.com", 
         "Surinder", "Dhillon", True, True, 2),
        (2, "pbkdf2_sha256$720000$Q4EZ8K4lQnGG2kZZ2tOUae$0mFiZZ4/K5Ewc36FAnAPhRqTBMm1vqT9wfVS8QzGfsk=", 
         "2024-07-07 22:05:45+01", False, False, True, "2024-07-07 22:05:44+01", "ND", "n.dhillon@anpsolicitors.com", 
         "Navjot", "Dhillon", True, True, 2),
        (3, "pbkdf2_sha256$720000$zJyJarbnpELLjZTb8VfKv2$Ef0w813AqAHOSKyRPMKggDq710CG9iPZONqEGE0DLa8=", 
         "2024-07-07 22:06:35+01", False, False, True, "2024-07-07 22:06:34+01", "GM", "privateclient@anpsolicitors.com", 
         "Gabbi", "Marshall", True, False, 3),
        (4, "pbkdf2_sha256$720000$lex9al6pGc6Lt6ut1qorjZ$V8EsYp3A8fdIO8LRwImWCuPMZYLCFtRIhgA8EuZnyMg=", 
         "2024-07-07 22:07:42+01", False, False, True, "2024-07-07 22:07:42+01", "JP", "j.phillips@anpsolicitors.com", 
         "John", "Phillips", True, True, 5),
        (5, "pbkdf2_sha256$720000$mIYOMwRPzCLSGu0wwUj22u$nemdQfKS5TyYlPxcOk4mVMNBeaEc1WSt3GFlzJuTlqs=", 
         "2024-07-07 22:08:51+01", False, False, True, "2024-07-07 22:08:51+01", "CP", "mail@anpsolicitors.com", 
         "Chris", "Pinnion", True, False, 2),
        (6, "pbkdf2_sha256$720000$8jLz8Jbuf4I88hmRXauhet$yVXx1VHnyl0lIVAqAZgJn6S3diz1cnQWrUmtxMiDaUY=", 
         "2024-07-07 22:10:06+01", False, False, True, "2024-07-07 22:10:06+01", "TR", "family@anpsolicitors.com", 
         "Tracey", "Rowley", True, False, 2),
        (7, "pbkdf2_sha256$720000$BBMOO71BeXky0ehLcnW8ra$jHRS8F59hey36sE/GGmwJ9XLJ3DRWpxVaVMuXbxhayo=", 
         "2024-07-07 22:24:25+01", True, True, True, "2024-07-07 22:10:46+01", "GB", "mail@anpsolicitors.com", 
         "Gursimran", "Bassi", False, True, 1),
        (8, "pbkdf2_sha256$720000$ARonTcixcWUpTbvJARP4Ee$ijOqqFo50Bf5E9+i/pOEenRsqy6OmpkWvGEDmaVmX0o=", 
         "2024-07-07 22:12:26.058965+01", False, False, True, "2024-07-07 22:12:25.8463+01", "AF", 
         "a.fraser@anpsolicitors.com", "Abbie", "Fraser", False, False, 1),
        (9, "pbkdf2_sha256$720000$04JNSBCQtiKG51H8fqrlkK$eEFKFksbPi5Q+UELoPmhISz8jU+COgcTOjs8r0eKfcE=", 
         "2024-07-07 22:13:20.480679+01", False, False, True, "2024-07-07 22:13:20.263684+01", "RY", 
         "mail@anpsolicitors.com", "Robbie", "Yates", False, False, 1),
        (10, "pbkdf2_sha256$720000$U4pFZq54U5V1tDkO2mqsnq$BBR+Vv6/9f3zwoVLxKRgsZUngsNpdqE739cRWQR25uk=", 
         "2024-07-07 22:13:53.812347+01", False, False, True, "2024-07-07 22:13:53.580991+01", "KS", "mail@anpsolicitors.com", 
         "Katie", "Spears", False, False, 1),
        (11, "pbkdf2_sha256$720000$LifJftyPvl1eghUTQD3e6o$V9AC2aYWKI0eF/da1N3+UwJMUKSSgdHE7+f2x9AVbX8=", 
         "2024-07-07 22:16:10.700877+01", False, False, True, "2024-07-07 22:16:10.472382+01", "TRN", 
         "family@anpsolicitors.com", "Tracey", "Rowley", False, False, 2),
        (12, "pbkdf2_sha256$720000$cfQe0zSBBmodQKKRhhl53z$P8PUtRt+iy6iajSvQo9L3E0SqVSx/ohem26Pm3Te4dg=", 
         "2024-07-07 22:17:11.481575+01", False, False, True, "2024-07-07 22:17:11.264042+01", "JPN",
           "j.phillips@anpsolicitors.com", "John", "Phillips", False, False, 4)
    ]


    insert_query = """
        INSERT INTO users_customuser (
            id, password, last_login, is_superuser,
             is_staff, is_active, date_joined, username,
               email, first_name, last_name, is_matter_fee_earner, 
               is_manager, hourly_rate_id
        ) VALUES (%s, %s,%s,%s, %s, %s,%s,%s, %s, %s,%s,%s,%s,%s)
    """
    for item in data:
        try:
            cur.execute(
                insert_query,
                (
                    item[0],
                    item[1],
                    item[2],
                    item[3],
                    item[4],
                    item[5],
                    item[6],
                    item[7],
                    item[8],
                    item[9],
                    item[10],
                    item[11],
                    item[12],
                    item[13],

                ))
            conn.commit()
        except psycopg2.Error as e:
            print("Error inserting row:", e)
            conn.rollback()
            continue
        except ValueError as ve:
            print("Value error:", ve)
            continue
    print('USERS ADDED')

def get_file_status_id(status):
    if status == 'Open':
        return 1
    if status == 'Archived':
        return 2
    if status == 'To Be Closed':
        return 3


def insert_client_contact_details(file_path):
    with open(file_path, 'r') as file:
        raw_data = json.load(file)
    
    data = None
    for table in raw_data:
        if 'name' in table and table['name'] == 'client_contact_details':
            data = table['data']
            break
    
    insert_query = """INSERT INTO backend_clientcontactdetails 
    (id, name, dob, address_line1, address_line2, county, postcode, 
    email, contact_number, date_of_last_aml, occupation, timestamp) 
    VALUES (%s,%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
    
    for item in data:
        try:
            cur.execute(
            insert_query,
            (
                item['ID'],
                item['ClientName'],
                validate_date(item['DOB']),
                item['AddressLine1'],
                item['AddressLine2'],
                item['County'],
                item['Postcode'],
                item['Email'],
                item['ContactNumber'],
                validate_date(item['DateOfLastAML']),
                item.get('Occupation', ''),
                validate_timestamp(item['Timestamp'])
            )
        )
            conn.commit()
        except psycopg2.Error as e:
            print("Error inserting row:", e)
            conn.rollback()
            continue
        except ValueError as ve:
            print("Value error:", ve)
            continue
    
def insert_authorised_parties(file_path):
    with open(file_path, 'r') as file:
        raw_data = json.load(file)
    
    data = None
    for table in raw_data:
        if 'name' in table and table['name'] == 'authorised_party_contact_details':
            data = table['data']
            break

    insert_query = """INSERT INTO backend_authorisedparties
    (id,name, relationship_to_client, address_line1, address_line2, county, postcode, email, contact_number,
    id_check, date_of_id_check, timestamp) 
    VALUES (%s,%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
    
    values = [
        (
            item['ID'],
            item['Name'],
            item['RelationshipToClient'],
            item['AddressLine1'],
            item['AddressLine2'],
            item['County'],
            item['Postcode'],
            item['Email'],
            item['ContactNumber'],
            validate_boolean(item['IDCheck']),
            validate_date(item['DateOfIDCheck']),
            validate_timestamp(item['Timestamp'])
        )
        for item in data
    ]
    
    cur.executemany(insert_query, values)
    conn.commit()

def add_file_locations():
    locations = []
    locations.append("Attic - See comments for box No see comments")
    locations.append("Back Office - Family")
    locations.append("Back Office - Litigation")
    locations.append("Back Office - Conveyancing")
    locations.append("Back Office - Miscellaneous")
    locations.append("Back Office - Private")
    locations.append("With CP")
    locations.append("With TR")
    query = """INSERT INTO backend_filelocation
    (location, timestamp) 
    VALUES (%s, %s)"""

    values = [
        (
            location,
            validate_timestamp('0000-00-00 00:00:00')
        )
        for location in locations
    ]
    
    cur.executemany(query, values)
    conn.commit()

def add_matter_types():
    types = []
    types.append('Conveyancing')
    types.append('Clinical Negligence')
    types.append('Corporate/Commercial')
    types.append('Debt Recovery')
    types.append('Employment')
    types.append('Family')
    types.append('General Advice')
    types.append('Housing')
    types.append('Immigration')
    types.append('Intellectual Property')
    types.append('Licensing')
    types.append('Litigation')
    types.append('Miscellaneous')
    types.append('Personal Injury')
    types.append('Power of Attorney')
    types.append('Probate')
    types.append('Trust')
    types.append('Wills')
    query = """INSERT INTO backend_mattertype
    (type, timestamp) 
    VALUES (%s, %s)"""

    values = [
        (
            type,
            validate_timestamp('0000-00-00 00:00:00')
        )
        for type in types
    ]
    
    cur.executemany(query, values)
    conn.commit()

def add_file_status():
    types = ['Open', 'Archived', 'To Be Closed']
    query = """INSERT INTO backend_filestatus
    (status, timestamp) 
    VALUES (%s, %s)"""

    values = [
        (
            type,
            validate_timestamp('0000-00-00 00:00:00')
        )
        for type in types
    ]
    
    cur.executemany(query, values)
    conn.commit()

def insert_wip(file_path):
    with open(file_path, 'r') as file:
        raw_data = json.load(file)
    
    for table in raw_data:
            if 'name' in table and table['name'] == 'wip':
                data = table['data']
   
    file_numbers_done = []
    for item in data:
        insert_query = """INSERT INTO backend_wip 
        (file_number, fee_earner_id, matter_description, client1_id, client2_id, 
        matter_type_id, file_status_id, file_location_id, other_side_id, date_of_client_care_sent, 
        terms_of_engagement_client1, terms_of_engagement_client2, date_of_toe_sent, date_of_toe_rcvd, 
        ncba_client1, ncba_client2, date_of_ncba_sent, date_of_ncba_rcvd, funding, authorised_party1_id, 
        authorised_party2_id, key_information, undertakings, comments, timestamp) 
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
        if item['FileNumber'] not in file_numbers_done:
            
        
            file_numbers_done.append(item['FileNumber'])
            
            
            values = (
                item['FileNumber'],
                get_fee_earner_id(item['FeeEarner']),
                item['MatterDescription'],
                item['Client1Contact_ID'] if item['Client1Contact_ID'] not in ['34', '339', '786'] else '859',
                item['Client2Contact_ID'] if item['Client2Contact_ID'] != '0' else None,
                get_matter_type_id(item['MatterType']),
                get_file_status_id(item['FileStatus']),
                get_location_id(item['FileLocation']),
                None if item['OtherSideDetails'] != '0' else None,
                validate_date(item['DateOfClientCareSent']),
                validate_boolean(item['TermsOfEngagementClient1']),
                validate_boolean(item['TermsOfEngagementClient2']),
                validate_date(item['DateOfToESent']),
                validate_date(item['DateOfToERcvd']),
                validate_boolean(item['NCBAClient1']),
                validate_boolean(item['NCBAClient2']),
                validate_date(item['DateOfNCBASent']),
                validate_date(item['DateOfNCBARcvd']),
                item['Funding'] if item['Funding'] != None else 'PF',
                item['AuthorisedParty1_ID'] if item['AuthorisedParty1_ID'] != '0' else None,
                item['AuthorisedParty2_ID'] if item['AuthorisedParty2_ID'] != '0' else None,
                item['KeyInformation'],
                item['Undertakings'],  
                item['Comments'],
                validate_timestamp(item['Timestamp'])  # Use current timestamp
            )

            cur.execute(insert_query, values)
            conn.commit()
    print('Total files added',len(file_numbers_done))
     
def insert_emails(file_path):
    try:
        with open(file_path, 'r') as file:
            raw_data = json.load(file)

        for table in raw_data:
            if 'name' in table and table['name'] == 'emails':
                data = table['data']

        insert_query = """INSERT INTO backend_matteremails
        (file_number_id, sender, receiver, subject, body, time, units, 
        fee_earner_id, is_sent, link, timestamp) 
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""

        for item in data:
            if item['FileNumber'] != 'XXXXXXXXXX':
                try:
                    cur.execute(insert_query, (
                        get_wip_id_by_file_number(item['FileNumber']),
                        json.dumps(item['Sender']),
                        json.dumps(item['Receiver']),
                        item['Subject'],
                        item['Body'],
                        item['ReceivedTime'],
                        item['Units'],
                        item['FeeEarner'] if item['FeeEarner'] != '0' else None,
                        True if item['isSent'] == '1' else False,
                        item['Link'],
                        validate_timestamp(item['Timestamp'])
                    ))
                    conn.commit()

                except psycopg2.Error as e:
                    print("Error inserting row:", e)
                    conn.rollback()
                    continue

        

    except IOError as e:
        print("Error reading file:", e)
   
def insert_attendance_notes(file_path):
    with open(file_path, 'r') as file:
        raw_data = json.load(file)

    for table in raw_data:
        if 'name' in table and table['name'] == 'matter_attendancenotes':
            data = table['data']
    
    insert_query = """INSERT INTO backend_matterattendancenotes
    (file_number_id, start_time, finish_time, subject_line, 
    content, is_charged, person_attended_id, date, unit, timestamp) 
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
    
    values = [
        (
            get_wip_id_by_file_number(item['FileNumber']),
            item['StartTime'],
            item['FinishTime'],
            item['SubjectLine'],
            convert_text_to_quill_format(item['Content']),
            validate_boolean(item['isCharged']),
            get_fee_earner_id(item['PersonAttended']),
            validate_date(item['Date']),
            item['Unit'],
            validate_timestamp(item['Timestamp'])
        )
        for item in data
    ]
    
    cur.executemany(insert_query, values)
    conn.commit()

def insert_pmt_slips(file_path):
    with open(file_path, 'r') as file:
        raw_data = json.load(file)

    for table in raw_data:
        if 'name' in table and table['name'] == 'pmts_slip':
            data = table['data']

    insert_query = """INSERT INTO backend_pmtsslips
    (id, file_number_id, ledger_account, mode_of_pmt, amount,
     is_money_out, pmt_person, description, date, amount_invoiced, 
     amount_allocated, balance_left, timestamp) 
    VALUES (%s,%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
    
    
    for item in data:
        try:
            cur.execute(insert_query, (
                item['ID'],
                get_wip_id_by_file_number(item['FileNumber']),
                item['LedgerAccount'],
                item['ModeOfPMT'],
                item['Amount'],
                True if item['PMTToOrFrom'] == '1' else False,
                item['PMTPerson'],
                item['Description'],
                validate_date(item['Date']),
                item['AmountInvoiced'] if item['PMTToOrFrom'] == '1' else amount_invoiced(item['AmountInvoiced']),
                amount_allocated(item['AmountAllocated']),  # Ensure this returns a JSON string
                item['BalanceLeft'],
                validate_timestamp(item['Timestamp']),
            ))
        except psycopg2.Error as e:
            print("Error inserting row:", e)
            conn.rollback()
            continue
    
    
    conn.commit()

def insert_green_slips(file_path):
    def process_amount_invoiced(value):
        if isinstance(value, str):
            try:
                
                value_float = float(value)
                return str(value_float) # Adjust to match your JSON structure
            except ValueError:
                try:
                    
                    return amount_invoiced(value)
                except json.JSONDecodeError:
                    print(f"Invalid value for amount invoiced: {value}")
                    return json.dumps({})  # Default or error handling as per requirements
        elif isinstance(value, float) or isinstance(value, int):
            return value if value > 0 else amount_invoiced(json.dumps({"Amount": value}))  # Adjust to match your JSON structure
        elif isinstance(value, dict):
            # Assume this is already a JSON-like dictionary
            return amount_invoiced(json.dumps(value))
        else:
            print(f"Unexpected type for amount invoiced: {type(value)}")
            return json.dumps({})  # Default or error handling as per requirements

    with open(file_path, 'r') as file:
        raw_data = json.load(file)

    for table in raw_data:
        if 'name' in table and table['name'] == 'ledger_accounts_transfers':
            data = table['data']
    
    insert_query = """INSERT INTO backend_ledgeraccounttransfers
    (id, file_number_from_id, file_number_to_id, from_ledger_account, to_ledger_account,
    amount, date, description, amount_invoiced_from, 
    balance_left_from, amount_invoiced_to, balance_left_to, timestamp) 
    VALUES (%s,%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""

    for item in data:
        try:
            amount_invoiced_from = process_amount_invoiced(item['AmountInvoicedFrom'])
            amount_invoiced_to = process_amount_invoiced(item['AmountInvoicedTo'])

            cur.execute(insert_query, (
                item['ID'],
                get_wip_id_by_file_number(item['FileNumberFrom']),
                get_wip_id_by_file_number(item['FileNumberTo']),
                item['FromLedgerAccount'],
                item['ToLedgerAccount'],
                float(item['Amount']),
                validate_date(item['Date']),
                item['Description'],
                amount_invoiced_from,
                item['BalanceLeftFrom'] if item['BalanceLeftFrom'] != None else item['Amount'] ,
                amount_invoiced_to,
                item['BalanceLeftTo'] if item['BalanceLeftTo'] != None else item['Amount'],
                validate_timestamp(item['Timestamp'])
            ))
        except psycopg2.Error as e:
            print("Error inserting row:", e)
            conn.rollback()
            continue
        except ValueError as ve:
            print("Value error:", ve)
            continue
    conn.commit()

def insert_invoices(file_path):
    def calculate_total_due_left(our_costs):
        json_costs = json.loads(our_costs)
        total_sum = sum(float(cost) for cost in json_costs)
        return total_sum

    def record_exists(table, invoices_id, pmtsslips_id):
        pmts_table = True if table != 'backend_invoices_green_slip_ids' else False
        if pmts_table:
            col = 'pmtsslips_id'
        else:
            col = 'ledgeraccounttransfers_id'
        query = f"SELECT 1 FROM {table} WHERE invoices_id = %s AND {col} = %s"
        cur.execute(query, (invoices_id, pmtsslips_id))
        return cur.fetchone() is not None

    with open(file_path, 'r') as file:
        raw_data = json.load(file)

    data = None
    for table in raw_data:
        if 'name' in table and table['name'] == 'invoices':
            data = table['data']
            break

    insert_query = """INSERT INTO backend_invoices
    (id, invoice_number, state, file_number_id, date,
    payable_by, by_email, by_post, description, 
    our_costs_desc, our_costs, total_due_left, timestamp) 
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id"""

    invoice_id_to_pink_slips = {}
    invoice_id_to_blue_slips = {}
    invoice_id_to_green_slips = {}
    invoice_id_to_cash_allocated_slips = {}

    for item in data:
        try:
            if item['InvoiceNumber'] != '2871':
                cur.execute(insert_query, (
                    item['ID'],
                    str(item['InvoiceNumber']),
                    'D' if item['State'] == 'Draft' else 'F',
                    get_wip_id_by_file_number(item['FileNumber']),
                    validate_date(item['Date']),
                    item['PayableBy'],
                    True if item['ByEmail'] == '1' else False,
                    True if item['ByPost'] == '1' else False,
                    item['Description'],
                    item['OurCostsDesc'],
                    item['OurCosts'],
                    '0.00' if item['Settled'] == '1' else calculate_total_due_left(item['OurCosts']),
                    validate_timestamp(item['Timestamp'])
                ))
                conn.commit()
                invoice_id = cur.fetchone()[0]

                pink_slip_ids = json.loads(item['DisbsIDs']) if item['DisbsIDs'] is not None else None
                invoice_id_to_pink_slips[invoice_id] = pink_slip_ids

                blue_slip_ids = json.loads(item['MOA_IDs']) if item['MOA_IDs'] is not None else None
                invoice_id_to_blue_slips[invoice_id] = blue_slip_ids

                green_slip_ids = json.loads(item['GreenSlip_IDs']) if item['GreenSlip_IDs'] is not None else None
                invoice_id_to_green_slips[invoice_id] = green_slip_ids

                cash_allocated_slips = json.loads(item['CashAllocatedSlips']) if item['CashAllocatedSlips'] is not None else None
                invoice_id_to_cash_allocated_slips[invoice_id] = cash_allocated_slips

        except psycopg2.Error as e:
            print("Error inserting row:", e)
            conn.rollback()
            continue
        except ValueError as ve:
            print("Value error:", ve)
            continue

    try:
        for invoice_id, pink_slips in invoice_id_to_pink_slips.items():
            for id in pink_slips:
                if not record_exists('backend_invoices_disbs_ids', invoice_id, id):
                    insert_query = """INSERT INTO backend_invoices_disbs_ids
                                    (invoices_id, pmtsslips_id)
                                    VALUES (%s,%s)"""
                    cur.execute(insert_query, (invoice_id, id))
        conn.commit()
    except psycopg2.Error as e:
        print("Error inserting row:", e)
        conn.rollback()
    
    try:
        for invoice_id, blue_slips in invoice_id_to_blue_slips.items():
            for id in blue_slips:
                if not record_exists('backend_invoices_moa_ids', invoice_id, id):
                    insert_query = """INSERT INTO backend_invoices_moa_ids
                                    (invoices_id, pmtsslips_id)
                                    VALUES (%s,%s)"""
                    cur.execute(insert_query, (invoice_id, id))
            conn.commit()
    except psycopg2.Error as e:
        print("Error inserting row:", e)
        conn.rollback()
 
    try:
        for invoice_id, green_slips in invoice_id_to_green_slips.items():
            for id in green_slips:
                if not record_exists('backend_invoices_green_slip_ids', invoice_id, id):
                    insert_query = """INSERT INTO backend_invoices_green_slip_ids
                                    (invoices_id, ledgeraccounttransfers_id)
                                    VALUES (%s,%s)"""
                    cur.execute(insert_query, (invoice_id, id))
            conn.commit()
    except psycopg2.Error as e:
        print("Error inserting row:", e)
        conn.rollback()
    conn.commit()
    
    try:
        for invoice_id, cash_allocated_slips in invoice_id_to_cash_allocated_slips.items():
            if cash_allocated_slips != None:
                for id in cash_allocated_slips:
                    if not record_exists('backend_invoices_cash_allocated_slips', invoice_id, id):
                        insert_query = """INSERT INTO backend_invoices_cash_allocated_slips
                                        (invoices_id, pmtsslips_id)
                                        VALUES (%s,%s)"""
                        cur.execute(insert_query, (invoice_id, id))
        conn.commit()
    except psycopg2.Error as e:
        print("Error inserting row:", e)
        conn.rollback()
    conn.commit()

def insert_letters(file_path):
    with open(file_path, 'r') as file:
        raw_data = json.load(file)

    data = None
    for table in raw_data:
        if 'name' in table and table['name'] == 'matter_letters':
            data = table['data']
            break
   
    '''
    "ID":"1","FileNumber":"TUR0050001","Date":"2022-08-16","ToOrFrom":"Alan Strachan ",
    "Sent":"0","Received":"1","SubjectLine":"Warning re Caveat ","PersonAttended":"SD",
    "IsCharged":"1","Timestamp":"0000-00-00 00:00:00"}
    '''
    insert_query = """INSERT INTO backend_matterletters
    (file_number_id, date, to_or_from, sent,
    subject_line, is_charged, timestamp, person_attended_id) 
    VALUES (%s,%s, %s, %s, %s, %s, %s, %s)"""

    for item in data:
        try: 
           
            cur.execute(insert_query, (
                get_wip_id_by_file_number(item['FileNumber']),
                validate_date(item['Date']),
                item['ToOrFrom'],
                validate_boolean(item['Sent']),

                item['SubjectLine'],
                validate_boolean(item['IsCharged']),
                validate_timestamp(item['Timestamp']),
                get_fee_earner_id(item['PersonAttended'])
            ))
            conn.commit()
        except psycopg2.Error as e:
            print("Error inserting row:", e)
            conn.rollback()
            continue
        except ValueError as ve:
            print("Value error:", ve)
            continue
    

data_path = 'old_db_data/all_data.json'

# add_hourly_rates()
# add_users()
# insert_client_contact_details(data_path)
# insert_authorised_parties(data_path)
# add_file_locations()
# add_matter_types()
# add_file_status()
# insert_wip(data_path)
# insert_emails(data_path)
# insert_attendance_notes(data_path)
# insert_pmt_slips(data_path)
# insert_green_slips(data_path)
insert_invoices(data_path# insert_letters(data_path)
# Close the connection
cur.close()
conn.close()
