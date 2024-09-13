from datetime import datetime
class InvoicesSerializer:
    def __init__(self, invoice_instance):
        self.invoice_instance = invoice_instance

    def to_dict(self):
        date_value = self.invoice_instance.date

        if isinstance(date_value, str):
            date_value = datetime.strptime(date_value, '%Y-%m-%d')
            
        formatted_date = date_value.strftime('%Y-%m-%d')
        return {
            'id': self.invoice_instance.id,
            'invoice_number': self.invoice_instance.invoice_number,
            'state': self.invoice_instance.state,
            'file_number_id': self.invoice_instance.file_number_id,
            'date': formatted_date,
            'payable_by': self.invoice_instance.payable_by,
            'by_email': self.invoice_instance.by_email,
            'by_post': self.invoice_instance.by_post,
            'description': self.invoice_instance.description,
            'our_costs_desc': self.invoice_instance.our_costs_desc,
            'our_costs': self.invoice_instance.our_costs,
            'disbs_ids': list(self.invoice_instance.disbs_ids.values_list('id', flat=True)),
            'moa_ids': list(self.invoice_instance.moa_ids.values_list('id', flat=True)),
            'cash_allocated_slips': list(self.invoice_instance.cash_allocated_slips.values_list('id', flat=True)),
            'green_slip_ids': list(self.invoice_instance.green_slip_ids.values_list('id', flat=True)),
            'total_due_left': str(self.invoice_instance.total_due_left),  # Convert to string
            'created_by_id': self.invoice_instance.created_by_id,
            'timestamp': self.invoice_instance.timestamp.strftime('%Y-%m-%d %H:%M:%S'),  # Convert to string
        }