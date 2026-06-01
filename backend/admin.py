# from django.contrib import admin
# from .models import ClientContactDetails, FileLocation, FileStatus, MatterType, AuthorisedParties, OthersideDetails, WIP, NextWork, LastWork, PmtsSlips, LedgerAccountTransfers, TempSlips, Invoices, MatterEmails, MatterLetters, MatterAttendanceNotes, Modifications

# admin.site.register(ClientContactDetails)
# admin.site.register(FileLocation)
# admin.site.register(FileStatus)
# admin.site.register(MatterType)
# admin.site.register(AuthorisedParties)
# admin.site.register(OthersideDetails)
# admin.site.register(WIP)
# admin.site.register(NextWork)
# admin.site.register(LastWork)
# admin.site.register(PmtsSlips)
# admin.site.register(LedgerAccountTransfers)
# admin.site.register(TempSlips)
# admin.site.register(Invoices)
# admin.site.register(MatterEmails)
# admin.site.register(MatterLetters)
# admin.site.register(MatterAttendanceNotes)
# admin.site.register(Modifications)
from django.contrib import admin
from .models import (Memo, Modifications, ClientContactDetails, AuthorisedParties, OthersideDetails,
                     ClientKeyDocument, MatterKeyDate,
                     FileLocation, FileStatus, MatterType, WIP, NextWork, LastWork, PmtsSlips,
                     LedgerAccountTransfers, Policy, PolicyVersion, TempSlips, Invoices, MatterEmails, MatterLetters,
                     MatterAttendanceNotes, MatterEmailDraft, MatterEmailDraftAttachment,
                     MatterTimeEvent, MatterTimeSession,
                     RiskAssessment, OngoingMonitoring, Free30Mins, Free30MinsAttendees, Undertaking,
                     CreditNote, MatterFileReview, PricingItem,
                     Bundle, BundleSection, BundleDocument,
                     EstateAccount, EstateAccountFinanceLineOverride,
                     EstateAccountManualEntry, EstateAccountDistribution,
                     EstateAccountSigner)


@admin.register(Modifications)
class ModificationsAdmin(admin.ModelAdmin):
    list_display = ['id', 'modified_by',
                    'content_type', 'object_id', 'timestamp']


@admin.register(ClientContactDetails)
class ClientContactDetailsAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'is_business', 'dob', 'address_line1', 'address_line2', 'county', 'postcode',
                    'email', 'contact_number', 'date_of_last_aml', 'id_verified',
                    'terms_of_engagement_signed', 'ncba_signed', 'pep_signed',
                    'source_of_funds_signed', 'timestamp', 'created_by']


@admin.register(ClientKeyDocument)
class ClientKeyDocumentAdmin(admin.ModelAdmin):
    list_display = ['id', 'client', 'category', 'document_type', 'document_reference',
                    'issue_date', 'expiry_date', 'verified_on', 'verified_by', 'timestamp']
    list_filter = ['category', 'expiry_date', 'verified_on']
    search_fields = ['client__name', 'document_type', 'document_reference']


@admin.register(AuthorisedParties)
class AuthorisedPartiesAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'relationship_to_client', 'address_line1', 'address_line2', 'county',
                    'postcode', 'email', 'contact_number', 'id_check', 'date_of_id_check',
                    'date_of_last_aml', 'timestamp', 'created_by']


@admin.register(OthersideDetails)
class OthersideDetailsAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'address_line1', 'address_line2', 'county', 'postcode',
                    'email', 'contact_number', 'solicitors', 'solicitors_email', 'timestamp', 'created_by']


@admin.register(FileLocation)
class FileLocationAdmin(admin.ModelAdmin):
    list_display = ['id', 'location', 'created_by', 'timestamp']


@admin.register(FileStatus)
class FileStatusAdmin(admin.ModelAdmin):
    list_display = ['id', 'status', 'created_by', 'timestamp']


@admin.register(MatterType)
class MatterTypeAdmin(admin.ModelAdmin):
    list_display = ['id', 'type', 'created_by', 'timestamp']


@admin.register(PricingItem)
class PricingItemAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'category', 'matter_type', 'pricing_type', 'price', 'minimum_price', 'maximum_price', 'vat_treatment', 'manager_only',
                    'is_active', 'created_by', 'updated_by', 'updated_at']
    list_filter = ['category', 'pricing_type', 'vat_treatment', 'manager_only', 'is_active', 'matter_type']
    search_fields = ['name', 'matter_type__type', 'notes']
    ordering = ['category', 'matter_type__type', 'name']


@admin.register(WIP)
class WIPAdmin(admin.ModelAdmin):
    list_display = ['id', 'file_number', 'fee_earner', 'matter_description', 'client1', 'client2',
                    'matter_type', 'file_status', 'file_location', 'zdrive_location',
                    'other_side', 'timestamp', 'created_by']


@admin.register(MatterKeyDate)
class MatterKeyDateAdmin(admin.ModelAdmin):
    list_display = ['id', 'matter', 'date_type', 'title',
                    'date', 'time', 'location', 'created_by', 'timestamp']
    list_filter = ['date_type', 'date']
    search_fields = ['matter__file_number', 'title', 'location', 'notes']


@admin.register(NextWork)
class NextWorkAdmin(admin.ModelAdmin):
    list_display = ['id', 'file_number', 'person', 'task',
                    'date', 'completed', 'created_by', 'timestamp']


@admin.register(LastWork)
class LastWorkAdmin(admin.ModelAdmin):
    list_display = ['id', 'file_number', 'person',
                    'task', 'date', 'created_by', 'timestamp']


@admin.register(PmtsSlips)
class PmtsSlipsAdmin(admin.ModelAdmin):
    # Display settings
    list_display = [
        'id', 'file_number', 'ledger_account', 'mode_of_pmt', 'amount',
        'is_money_out', 'pmt_person', 'description', 'date',
        'amount_invoiced', 'amount_allocated', 'balance_left',
        'created_by', 'timestamp'
    ]
    list_display_links = ['id', 'file_number']

    # Filtering options
    list_filter = ['mode_of_pmt', 'is_money_out', 'created_by', 'date']
    search_fields = ['file_number', 'ledger_account', 'pmt_person']

    # Ordering and date hierarchy
    ordering = ['-timestamp']
    date_hierarchy = 'date'

    # Enable editing of the timestamp field
    readonly_fields = []

    # Adding save on top to avoid scrolling down to save for each edit
    save_on_top = True


@admin.register(LedgerAccountTransfers)
class LedgerAccountTransfersAdmin(admin.ModelAdmin):
    list_display = ['id', 'file_number_from', 'file_number_to', 'from_ledger_account', 'to_ledger_account', 'amount', 'date',
                    'description', 'amount_invoiced_from', 'balance_left_from', 'amount_invoiced_to', 'balance_left_to',
                    'is_cashier_co_transfer', 'is_bank_transfer_done', 'bank_transfer_done_on', 'bank_transfer_done_by', 'created_by', 'timestamp']


@admin.register(TempSlips)
class TempSlipsAdmin(admin.ModelAdmin):
    list_display = ['id', 'file_number', 'date', 'amount',
                    'description', 'created_by', 'timestamp']


@admin.register(Invoices)
class InvoicesAdmin(admin.ModelAdmin):
    list_display = ['id', 'invoice_number', 'state', 'file_number', 'date', 'payable_by',
                    'by_email', 'by_post', 'description', 'vat', 'total_due_left', 'created_by', 'timestamp']


@admin.register(CreditNote)
class CreditNoteAdmin(admin.ModelAdmin):
    list_display = ['id', 'invoice', 'file_number', 'date', 'amount',
                    'status', 'created_by', 'approved_by', 'approved_on', 'timestamp']


class MatterEmailDraftAttachmentInline(admin.TabularInline):
    model = MatterEmailDraftAttachment
    extra = 0
    readonly_fields = ['original_name', 'size', 'content_type', 'created_at']


@admin.register(MatterEmailDraft)
class MatterEmailDraftAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'file_number', 'user', 'subject', 'from_mailbox', 'updated_at',
    ]
    list_filter = ['updated_at']
    inlines = [MatterEmailDraftAttachmentInline]


@admin.register(MatterEmailDraftAttachment)
class MatterEmailDraftAttachmentAdmin(admin.ModelAdmin):
    list_display = ['id', 'draft', 'original_name', 'size', 'content_type', 'created_at']
    list_filter = ['created_at']


@admin.register(MatterEmails)
class MatterEmailsAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'file_number', 'subject', 'is_sent', 'time', 'fee_earner', 'units',
        'sent_via_app', 'request_read_receipt', 'request_delivery_receipt', 'link',
    ]
    list_filter = ['is_sent', 'sent_via_app']


@admin.register(MatterLetters)
class MatterLettersAdmin(admin.ModelAdmin):
    list_display = ['id', 'file_number', 'date', 'to_or_from', 'sent',
                    'subject_line', 'person_attended', 'is_charged', 'created_by', 'timestamp']


@admin.register(MatterAttendanceNotes)
class MatterAttendanceNotesAdmin(admin.ModelAdmin):
    list_display = ['id', 'file_number', 'start_time', 'finish_time', 'subject_line',
                    'content', 'is_charged', 'person_attended', 'date', 'unit', 'created_by', 'timestamp']


@admin.register(MatterTimeEvent)
class MatterTimeEventAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'file_number', 'user', 'description', 'activity_type',
        'units', 'is_charged', 'status', 'source', 'ended_at',
    ]
    list_filter = ['status', 'activity_type', 'source', 'is_charged']


@admin.register(MatterTimeSession)
class MatterTimeSessionAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'file_number', 'started_at', 'activity_type']


@admin.register(RiskAssessment)
class RiskAssessmentAdmin(admin.ModelAdmin):
    list_display = ['id', 'matter', 'client_source_of_funds', 'unusual_client', 'client_concerns', 'third_party_authority', 'concerns_about_parties', 'designated_person_entity', 'issues_identified_client_risks_sec',
                    'client_location', 'location_of_instruction_concerns', 'make_sense_location_of_instructions', 'overseas_elements', 'issues_identified_jurisdiction_risks_sec',
                    'meeting_in_person', 'who_they_are', 'due_diligence_review', 'adverse_media', 'beneficial_owners_details', 'ultimate_beneficial_owners', 'reportable_discrepancies',
                    'matter_description', 'matter_transaction_value', 'usual_work', 'complex_structure', 'cash_intensive_industry', 'high_risk_industry', 'proliferation_financing',
                    'other_risks', 'transactional_matter', 'movement_of_funds_assets', 'receiving_funds_from_overseas', 'receiving_funds_from_third_parties', 'consistent_with_client_profile',
                    'issues_identified_matter_risks_sec', 'makes_sense_for_client', 'product_service_risk_details', 'complex_structure_or_unusual', 'higher_risk_sector', 'cash_intensive_business_activity',
                    'high_risk_third_country_or_jurisdiction', 'politically_exposed_person', 'financial_sanctions', 'country_subject_to_sanctions', 'unusual_complex_transaction', 'unusual_pattern_of_transactions',
                    'lack_of_economic_or_legal_purpose', 'other_high_risk_factors', 'escalated_date', 'issues_identified_enhanced_due_dilligence', 'client_risk_level', 'matter_risk_level',
                    'evidence_of_source_of_wealth', 'source_of_wealth_correspondence', 'customer_due_diligence_level', 'due_diligence_date', 'due_diligence_signed_by']


class OngoingMonitoringAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'file_number',
        'any_changes_discovered',
        'updated_risk_level_matter',
        'updated_risk_level_client',
        'date_due_diligence_conducted',
        'signed_by',
        'created_by',
        'timestamp'
    )
    list_filter = (
        'any_changes_discovered',
        'updated_risk_level_matter',
        'updated_risk_level_client',
        'date_due_diligence_conducted',
        'signed_by',
        'created_by',
        'timestamp'
    )
    search_fields = (
        # Replace 'some_field_in_WIP_model' with actual field name to search in related WIP model
        'file_number__some_field_in_WIP_model',
        'how_was_monitioring_of_risks_coducted',
        'details_of_changes',
        'how_it_will_be_monitored',
        'signed_by__username',  # Assuming CustomUser has 'username' field
        'created_by__username'
    )
    ordering = ('-timestamp',)
    fieldsets = (
        (None, {
            'fields': (
                'file_number',
                'how_was_monitioring_of_risks_coducted',
                'any_changes_discovered',
                'details_of_changes'
            )
        }),
        ('Risk Levels', {
            'fields': (
                'updated_risk_level_matter',
                'updated_risk_level_client'
            )
        }),
        ('Additional Information', {
            'fields': (
                'how_it_will_be_monitored',
                'date_due_diligence_conducted',
                'signed_by',
                'created_by'
            )
        }),
        ('Timestamps', {
            'fields': ('timestamp',)
        }),
    )
    readonly_fields = ('timestamp',)


admin.site.register(OngoingMonitoring, OngoingMonitoringAdmin)


class Free30MinsAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'matter_type',
        'notes',
        'date',
        'start_time',
        'finish_time',
        'created_by',
        'timestamp'
    )
    search_fields = ('id', 'matter_type__name', 'notes')
    list_filter = ('date', 'matter_type', 'created_by', 'timestamp')


admin.site.register(Free30Mins, Free30MinsAdmin)


class Free30MinsAttendeesAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'address_line1',
        'address_line2',
        'county',
        'postcode',
        'email',
        'contact_number',
        'created_by',
        'timestamp'
    )
    search_fields = ('name', 'email', 'contact_number')
    list_filter = ('county', 'created_by', 'timestamp')


admin.site.register(Free30MinsAttendees, Free30MinsAttendeesAdmin)


@admin.register(Undertaking)
class UndertakingAdmin(admin.ModelAdmin):
    # List display for the admin list view
    list_display = ('id', 'file_number', 'date_given', 'given_to',
                    'given_by', 'date_discharged', 'discharged_by', 'timestamp')

    # Add search fields
    search_fields = ('file_number__file_number', 'given_to',
                     'description', 'given_by__username', 'discharged_by__username')

    # Add filters for fields
    list_filter = ('date_given', 'date_discharged',
                   'given_by', 'discharged_by')

    # Make the list ordered by timestamp by default
    ordering = ('-timestamp',)


@admin.register(MatterFileReview)
class MatterFileReviewAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'matter',
        'file_reviewed_by',
        'date_reviewed',
        'file_review_completed_by',
        'date_review_completed',
        'created_by',
        'timestamp',
    )
    search_fields = (
        'matter__file_number',
        'matter__matter_description',
        'file_reviewed_by__username',
        'file_reviewed_by__first_name',
        'file_reviewed_by__last_name',
        'file_review_completed_by__username',
        'file_review_completed_by__first_name',
        'file_review_completed_by__last_name',
        'supervisor',
    )
    list_filter = (
        'date_reviewed',
        'date_review_completed',
        'created_by',
        'timestamp',
    )
    ordering = ('-date_review_completed', '-date_reviewed', '-timestamp')


class PolicyVersionInline(admin.TabularInline):
    model = PolicyVersion
    fields = ('version_number', 'content', 'changes_by', 'timestamp')
    readonly_fields = ('version_number', 'changes_by', 'timestamp')
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Policy)
class PolicyAdmin(admin.ModelAdmin):
    list_display = ('id', 'description', 'latest_version')
    search_fields = ('description',)
    inlines = [PolicyVersionInline]

    def latest_version(self, obj):
        return obj.versions.order_by('-version_number').first().version_number if obj.versions.exists() else "N/A"
    latest_version.short_description = 'Latest Version'


@admin.register(PolicyVersion)
class PolicyVersionAdmin(admin.ModelAdmin):
    list_display = ('policy', 'version_number', 'changes_by', 'timestamp')
    list_filter = ('policy', 'changes_by')
    search_fields = ('policy__description', 'content')
    readonly_fields = ('version_number', 'policy', 'changes_by', 'timestamp')

    def has_add_permission(self, request):
        return False  # Disable adding PolicyVersion directly from admin

    def has_change_permission(self, request, obj=None):
        return False  # Disable editing PolicyVersion from admin


@admin.register(Memo)
class MemoAdmin(admin.ModelAdmin):
    list_display = ('id', 'date', 'is_final', 'created_by', 'timestamp')
    list_filter = ('is_final', 'date', 'created_by')
    search_fields = ('content', 'created_by__username')
    ordering = ('-timestamp',)
    readonly_fields = ('timestamp',)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related('created_by')


# Bundle Admin Classes
class BundleDocumentInline(admin.TabularInline):
    model = BundleDocument
    extra = 0
    readonly_fields = ('page_start', 'page_end', 'uploaded_at')
    fields = ('file', 'description', 'date', 'order', 'page_start', 'page_end')


class BundleSectionInline(admin.TabularInline):
    model = BundleSection
    extra = 0
    fields = ('heading', 'order')


@admin.register(Bundle)
class BundleAdmin(admin.ModelAdmin):
    list_display = ('name', 'file_number', 'created_by', 'pdf_generated_at', 'created_at')
    list_filter = ('created_at', 'created_by')
    search_fields = ('name', 'file_number__file_number', 'created_by__username')
    readonly_fields = ('created_at', 'updated_at', 'pdf_generated_at')
    inlines = [BundleSectionInline]
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('file_number', 'created_by')


@admin.register(BundleSection)
class BundleSectionAdmin(admin.ModelAdmin):
    list_display = ('heading', 'bundle', 'order', 'created_at')
    list_filter = ('bundle', 'created_at')
    search_fields = ('heading', 'bundle__name')
    readonly_fields = ('created_at',)
    inlines = [BundleDocumentInline]
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('bundle')


@admin.register(BundleDocument)
class BundleDocumentAdmin(admin.ModelAdmin):
    list_display = ('description', 'section', 'date', 'order', 'page_start', 'page_end', 'uploaded_at')
    list_filter = ('section__bundle', 'date', 'uploaded_at')
    search_fields = ('description', 'section__heading', 'section__bundle__name')
    readonly_fields = ('page_start', 'page_end', 'uploaded_at')
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('section__bundle')


@admin.register(EstateAccount)
class EstateAccountAdmin(admin.ModelAdmin):
    list_display = ('matter', 'status', 'deceased_name', 'account_date', 'updated_at')
    list_filter = ('status',)
    search_fields = ('matter__file_number', 'deceased_name')


@admin.register(EstateAccountManualEntry)
class EstateAccountManualEntryAdmin(admin.ModelAdmin):
    list_display = ('estate_account', 'section', 'description', 'amount', 'date', 'is_pending')


@admin.register(EstateAccountFinanceLineOverride)
class EstateAccountFinanceLineOverrideAdmin(admin.ModelAdmin):
    list_display = ('estate_account', 'source_type', 'source_id', 'is_excluded')


@admin.register(EstateAccountDistribution)
class EstateAccountDistributionAdmin(admin.ModelAdmin):
    list_display = ('estate_account', 'beneficiary_name', 'gross_amount', 'net_amount')


@admin.register(EstateAccountSigner)
class EstateAccountSignerAdmin(admin.ModelAdmin):
    list_display = ('estate_account', 'signer_name', 'sort_order')
