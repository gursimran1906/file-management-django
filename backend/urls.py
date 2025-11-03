from django.urls import path

from .views import add_memo, delete_memo, display_data_index_page, display_data_home_page, download_aml_checks_due, download_risk_assessments_due, edit_memo, open_new_file_page, add_new_work_file, edit_next_work, add_last_work_file, edit_last_work, read_memo, update_task_status, load_initial_tasks, load_more_tasks, get_files, get_users, create_task
from .views import attendance_note_view, add_attendance_note, download_attendance_note, edit_attendance_note, correspondence_view, add_letter, edit_letter, download_sowc
from .views import finance_view, add_blue_slip, add_pink_slip, add_green_slip, edit_pmts_slip, download_pmts_slip, edit_green_slip, download_green_slip, add_invoice
from .views import allocate_monies, download_statement_account, download_invoice, edit_invoice, download_estate_accounts, unallocated_emails, allocate_emails
from .views import download_cashier_data, edit_file, edit_client, edit_authorised_party, download_file_logs, download_frontsheet, generate_ledgers_report, user_dashboard, download_risk_assessment
from .views import add_risk_assessment, download_search_report, policies_display, policy_read, invoices_list, download_invoices, add_ongoing_monitoring, edit_risk_assessment, download_ongoing_monitoring
from .views import edit_ongoing_monitoring, download_document, onboarding_documents_display, edit_otherside, free30mins, download_free30mins, edit_free30mins
from .views import undertakings, edit_undertaking, add_policy, edit_policy, download_policy_pdf, management_reports, weekly_report_view, policies_read_per_user
from .views import bundle_create, bundle_edit, bundle_section_add, bundle_section_delete, bundle_section_reorder, bundle_document_upload, bundle_document_delete, bundle_document_reorder, bundle_generate, bundle_view, bundle_download, bundle_delete
from .views import update_comment

urlpatterns = [
    path('dashboard/', user_dashboard, name='user_dashboard'),
    path('index/display_data/', display_data_index_page,
         name='display_data_index_page'),
    path('index/search/download/', download_search_report,
         name='download_search_report'),
    path('new_file/', open_new_file_page, name='new_file'),

    path('risk_assessment/add/<str:file_number>/',
         add_risk_assessment, name='add_risk_assessment'),
    path('risk_assessment/edit/<int:id>/',
         edit_risk_assessment, name='edit_risk_assessment'),
    path('risk_assessment/download/<int:id>/',
         download_risk_assessment, name='download_risk_assessment'),

    path('ongoing_monitoring/download/<int:id>/',
         download_ongoing_monitoring, name='download_ongoing_monitoring'),

    path('ongoing_monitoring/add/<str:file_number>/',
         add_ongoing_monitoring, name='add_ongoing_monitoring'),
    path('ongoing_monitoring/edit/<int:id>/',
         edit_ongoing_monitoring, name='edit_ongoing_monitoring'),


    path('<str:file_number>/edit/', edit_file, name='edit_file'),

    path('client/edit/<int:id>/', edit_client, name='edit_client'),
    path('authorised_party/edit/<int:id>/',
         edit_authorised_party, name='edit_authorised_party'),
    path('other_side/edit/<int:id>/', edit_otherside, name='edit_otherside'),

    path('home/<str:file_number>/', display_data_home_page, name='home'),
    path('home/<str:file_number>/next_work/add/',
         add_new_work_file, name='add_next_work_file'),
    path('home/<str:file_number>/last_work/add/',
         add_last_work_file, name='add_last_work_file'),

    path('file_logs/<str:file_number>/',
         download_file_logs, name='download_file_logs'),
    path('frontsheet/<str:file_number>/',
         download_frontsheet, name='download_frontsheet'),


    path('next_work/edit/<int:id>/', edit_next_work, name='edit_next_work'),
    path('last_work/edit/<int:id>/', edit_last_work, name='edit_last_work'),

    path('<str:file_number>/attendance_notes/',
         attendance_note_view, name='attendance_note_view'),
    path('<str:file_number>/attendance_notes/add/',
         add_attendance_note, name='add_attendance_note'),

    path('attendance_note/download/<int:id>/',
         download_attendance_note, name='download_attendance_note'),
    path('attendance_note/edit/<int:id>/',
         edit_attendance_note, name='edit_attendance_note'),


    path('<str:file_number>/correspondence/',
         correspondence_view, name='correspondence_view'),
    path('<str:file_number>/letter/add/', add_letter, name='add_letter'),
    path('letter/edit/<int:id>/', edit_letter, name='edit_letter'),

    path('<str:file_number>/sowc/download/',
         download_sowc, name='download_sowc'),

    path('<str:file_number>/finances/', finance_view, name='finance_view'),
    path('<str:file_number>/finances/statement/',
         download_statement_account, name='download_statement_account'),
    path('<str:file_number>/finances/ledger/',
         generate_ledgers_report, name='download_ledger_account'),
    path('<str:file_number>/finances/estate_account/',
         download_estate_accounts, name='download_estate_account'),
    path('<str:file_number>/pink_slip/add/',
         add_pink_slip, name='add_pink_slip'),
    path('<str:file_number>/blue_slip/add/',
         add_blue_slip, name='add_blue_slip'),

    path('<str:file_number>/green_slip/add/',
         add_green_slip, name='add_green_slip'),
    path('green_slip/edit/<int:id>/', edit_green_slip, name='edit_green_slip'),
    path('green_slip/download/<int:id>/',
         download_green_slip, name='download_green_slip'),

    path('pmts_slip/edit/<int:id>/', edit_pmts_slip, name='edit_pmts_slip'),
    path('pmts_slip/download/<int:id>/',
         download_pmts_slip, name='download_pmts_slip'),

    path('<str:file_number>/invoice/add/', add_invoice, name='add_invoice'),
    path('invoice/download/<int:id>/', download_invoice, name='download_invoice'),
    path('invoice/edit/<int:id>/', edit_invoice, name='edit_invoice'),

    path('allocate/monies_in/invoice/', allocate_monies, name='allocate_monies'),

    path('emails/unallocated/', unallocated_emails, name='unallocated_emails'),
    path('emails/allocate/', allocate_emails, name='allocate_emails'),

    path('cashier_data/', download_cashier_data, name='download_cashier_data'),

    path('policies/', policies_display, name='policies_display'),
    path('policy/read/<int:policy_id>/', policy_read, name='policy_read'),
    path('policy/add/', add_policy, name='add_policy'),
    path('policy/<int:policy_id>/edit/', edit_policy, name='edit_policy'),
    path('policy_version/<int:policy_version_id>/download/',
         download_policy_pdf, name='download_policy_pdf'),

    path('onboarding_documents/', onboarding_documents_display,
         name='onboarding_documents'),

    path('invoices_list/', invoices_list, name='invoices_list'),
    path('download_invoices/', download_invoices, name='download_invoices'),

    # path('download/document/', download_document, name='download_document'),

    path('free30mins/', free30mins, name='free30mins'),
    path('free30mins/download/<int:id>/',
         download_free30mins, name='download_free30mins'),
    path('free30mins/edit/<int:id>/', edit_free30mins, name='edit_free30mins'),

    path('undertakings/', undertakings, name='undertakings'),
    path('undertakings/edit/<int:id>/',
         edit_undertaking, name='edit_undertaking'),

    path('management_reports/', management_reports, name='management_reports'),
    path('user_weekly_report/', weekly_report_view, name='user_weekly_report'),
    path('policies_read_per_user/', policies_read_per_user,
         name='policies_read_per_user'),

    path('download_aml_checks_due', download_aml_checks_due,
         name='download_aml_checks_due'),
    path('download_risk_assessments_due', download_risk_assessments_due,
         name='download_risk_assessments_due'),

    path('memos/add/', add_memo, name='add_memo'),
    path('memos/<int:memo_id>/edit/', edit_memo, name='edit_memo'),
    path('memos/<int:memo_id>/delete/', delete_memo, name='delete_memo'),
    path('memos/<int:memo_id>/read/', read_memo, name='read_memo'),

    # Bundle URLs
    path('bundles/', bundle_create, name='bundle_create'),
    path('bundles/<str:file_number>/', bundle_create,
         name='bundle_create_with_file'),
    path('bundle/<int:bundle_id>/', bundle_edit, name='bundle_edit'),
    path('bundle/<int:bundle_id>/view/', bundle_view, name='bundle_view'),
    path('bundle/<int:bundle_id>/generate/',
         bundle_generate, name='bundle_generate'),
    path('bundle/<int:bundle_id>/download/',
         bundle_download, name='bundle_download'),
    path('bundle/<int:bundle_id>/delete/', bundle_delete, name='bundle_delete'),

    # Bundle Section URLs
    path('bundle/<int:bundle_id>/section/add/',
         bundle_section_add, name='bundle_section_add'),
    path('bundle/section/<int:section_id>/delete/',
         bundle_section_delete, name='bundle_section_delete'),
    path('bundle/<int:bundle_id>/section/reorder/',
         bundle_section_reorder, name='bundle_section_reorder'),

    # Bundle Document URLs
    path('bundle/section/<int:section_id>/document/upload/',
         bundle_document_upload, name='bundle_document_upload'),
    path('bundle/document/<int:document_id>/delete/',
         bundle_document_delete, name='bundle_document_delete'),
    path('bundle/section/<int:section_id>/document/reorder/',
         bundle_document_reorder, name='bundle_document_reorder'),

    # Kanban Board AJAX endpoints
    path('update-task-status/', update_task_status, name='update_task_status'),
    path('load-initial-tasks/', load_initial_tasks, name='load_initial_tasks'),
    path('load-more-tasks/', load_more_tasks, name='load_more_tasks'),

    # API endpoints for modal
    path('api/get-files/', get_files, name='get_files'),
    path('api/get-users/', get_users, name='get_users'),
    path('api/create-task/', create_task, name='create_task'),

    # Update comment endpoint
    path('update-comment/', update_comment, name='update_comment'),
]
