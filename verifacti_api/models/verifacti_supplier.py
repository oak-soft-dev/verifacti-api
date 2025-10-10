# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class VerifactiSupplier(models.Model):
    """
    Proveedor emisor de facturas Verifacti

    NOTA: Este modelo ahora hereda de res.company.
    Los proveedores son compañías que tienen configuraciones de API Verifacti.
    """
    _name = 'verifacti.supplier'
    _description = 'Proveedor Verifacti'
    _inherits = {'res.company': 'company_id'}
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    # Referencia a la compañía base
    company_id = fields.Many2one(
        'res.company',
        string='Compañía',
        required=True,
        ondelete='cascade',
        help='Compañía que actúa como proveedor Verifacti'
    )

    # Los campos name, vat, email, phone, street, etc. se heredan de res.company via _inherits

    # Configuraciones de API (relación con el modelo de configuración)
    verifacti_api_config_ids = fields.One2many(
        related='company_id.verifacti_api_config_ids',
        string='Configuraciones API',
        readonly=True
    )

    verifacti_default_api_config_id = fields.Many2one(
        related='company_id.verifacti_default_api_config_id',
        string='Configuración API por Defecto',
        readonly=True
    )

    # Relaciones
    invoice_ids = fields.One2many(
        related='company_id.verifacti_supplier_invoice_ids',
        string='Facturas Emitidas'
    )

    invoice_count = fields.Integer(
        related='company_id.verifacti_supplier_invoice_count',
        string='Núm. Facturas'
    )

    # Estadísticas
    last_invoice_date = fields.Date(
        string='Última Factura',
        compute='_compute_statistics',
        store=True
    )

    total_invoices_sent = fields.Integer(
        string='Total Facturas Enviadas',
        compute='_compute_statistics',
        store=True
    )

    total_invoices_correct = fields.Integer(
        string='Facturas Correctas',
        compute='_compute_statistics',
        store=True
    )

    total_invoices_error = fields.Integer(
        string='Facturas con Error',
        compute='_compute_statistics',
        store=True
    )

    notes = fields.Text(string='Notas')

    _sql_constraints = [
        ('company_unique', 'unique(company_id)', 'Esta compañía ya está registrada como proveedor Verifacti'),
    ]

    @api.depends('invoice_ids.state', 'invoice_ids.fecha_expedicion')
    def _compute_statistics(self):
        for supplier in self:
            invoices = supplier.invoice_ids
            supplier.total_invoices_sent = len(invoices.filtered(
                lambda i: i.state in ['sent', 'pending', 'correct', 'error']
            ))
            supplier.total_invoices_correct = len(invoices.filtered(
                lambda i: i.state == 'correct'
            ))
            supplier.total_invoices_error = len(invoices.filtered(
                lambda i: i.state == 'error'
            ))

            last_invoice = invoices.sorted('fecha_expedicion', reverse=True)[:1]
            supplier.last_invoice_date = last_invoice.fecha_expedicion if last_invoice else False

    def action_manage_api_configs(self):
        """Gestionar configuraciones de API de este proveedor"""
        self.ensure_one()
        return self.company_id.action_view_verifacti_api_configs()

    def action_create_api_config(self):
        """Crear nueva configuración de API para este proveedor"""
        self.ensure_one()
        return self.company_id.action_create_verifacti_api_config()

    def action_view_invoices(self):
        """Abrir lista de facturas del proveedor"""
        self.ensure_one()
        return self.company_id.action_view_verifacti_supplier_invoices()

    def name_get(self):
        """Mostrar nombre de la compañía con VAT"""
        result = []
        for supplier in self:
            vat = supplier.vat or 'Sin VAT'
            name = f"{supplier.name} ({vat})"
            result.append((supplier.id, name))
        return result
