from datetime import datetime
from email_sorting.utils import export_client_subject_emails_to_csv

client_names = [
    "Valencia Waste",
    "Hadleigh Salvage (Recycling) Limited",
    "K15ZA362"
    # add all relevant client names
]

export_client_subject_emails_to_csv(
    client_keywords=client_names,
    output_csv_path="/tmp/disputeresolution_court_client_emails.csv",
    mailboxes=["disputeresolution@anpsolicitors.com"],
    start_date=datetime(2020, 1, 1),
    end_date=datetime(2026, 12, 31),
)

# from datetime import datetime
# import os
# from dotenv import load_dotenv

# BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# EMAIL_SORTING_DIR = os.path.join(BASE_DIR, "email_sorting")

# # Load Azure creds from email_sorting/.env
# load_dotenv(os.path.join(EMAIL_SORTING_DIR, ".env"))

# from email_sorting.utils import (
#     export_emails_for_domains_to_csv,
#     export_client_subject_emails_to_csv,
# )

# def main():
#     # 1) Domain-based export
#     export_emails_for_domains_to_csv(
#         target_domains=["viridor.co.uk", "bexleybeaumont.com"],
#         output_csv_path="/tmp/domain_emails.csv",
#         start_date=datetime(2020, 1, 1),
#         end_date=datetime(2026, 12, 31),
#     )

#     # 2) Court emails by client name in subject
#     client_names = [
#         "Valencia Waste",
#         "Hadleigh Salvage (Recycling) Limited",
#         # add more...
#     ]

#     export_client_subject_emails_to_csv(
#         client_keywords=client_names,
#         output_csv_path="/tmp/court_client_subject_emails.csv",
#         start_date=datetime(2020, 1, 1),
#         end_date=datetime(2026, 12, 31),
#     )

# if __name__ == "__main__":
#     main()