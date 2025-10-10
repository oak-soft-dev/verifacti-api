# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class VerifactiCustomer(models.Model):
    """Cliente VeriFactu - Destinatario de facturas que emites"""
    _name = 'verifacti.customer'
    _description = 'Cliente VeriFactu'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(
        string='Nombre',
        required=True,
        tracking=True,
        help='Nombre o razón social del cliente'
    )

    nif = fields.Char(
        string='NIF/CIF',
        tracking=True,
        help='NIF/CIF del cliente (opcional para facturas simplificadas)'
    )

    # Información de contacto
    email = fields.Char(
        string='Email',
        help='Email de contacto del cliente'
    )

    phone = fields.Char(
        string='Teléfono',
        help='Teléfono de contacto del cliente'
    )

    # Dirección
    street = fields.Char(string='Calle')
    street2 = fields.Char(string='Calle 2')
    city = fields.Char(string='Ciudad')
    zip = fields.Char(string='Código Postal')
    state_id = fields.Many2one('res.country.state', string='Provincia')
    country_id = fields.Many2one(
        'res.country',
        string='País',
        default=lambda self: self.env.ref('base.es', raise_if_not_found=False)
    )

    # Relación con contacto de Odoo (opcional)
    partner_id = fields.Many2one(
        'res.partner',
        string='Contacto Relacionado',
        help='Contacto de Odoo asociado a este cliente VeriFactu'
    )

    active = fields.Boolean(
        string='Activo',
        default=True,
        tracking=True
    )

    # Relaciones
    invoice_ids = fields.One2many(
        'verifacti.invoice',
        'customer_id',
        string='Facturas Emitidas',
        readonly=True
    )

    invoice_count = fields.Integer(
        string='Núm. Facturas',
        compute='_compute_invoice_count'
    )

    # Estadísticas
    last_invoice_date = fields.Date(
        string='Última Factura',
        compute='_compute_statistics',
        store=True
    )

    total_invoices = fields.Integer(
        string='Total Facturas',
        compute='_compute_statistics',
        store=True
    )

    total_amount = fields.Monetary(
        string='Importe Total',
        currency_field='currency_id',
        compute='_compute_statistics',
        store=True
    )

    currency_id = fields.Many2one(
        'res.currency',
        string='Moneda',
        default=lambda self: self.env.company.currency_id
    )

    notes = fields.Text(string='Notas')

    _sql_constraints = [
        ('nif_unique', 'unique(nif)', 'Ya existe un cliente con este NIF'),
    ]

    @api.depends('invoice_ids')
    def _compute_invoice_count(self):
        for customer in self:
            customer.invoice_count = len(customer.invoice_ids)

    @api.depends('invoice_ids', 'invoice_ids.importe_total', 'invoice_ids.fecha_expedicion')
    def _compute_statistics(self):
        for customer in self:
            invoices = customer.invoice_ids.filtered(lambda i: i.state == 'correct')
            customer.total_invoices = len(invoices)
            customer.total_amount = sum(invoices.mapped('importe_total'))

            last_invoice = invoices.sorted('fecha_expedicion', reverse=True)[:1]
            customer.last_invoice_date = last_invoice.fecha_expedicion if last_invoice else False

    @api.constrains('nif')
    def _check_nif(self):
        """Validación básica de NIF"""
        for customer in self:
            if customer.nif:
                nif = customer.nif.strip().upper()
                if len(nif) < 9:
                    raise ValidationError(_('El NIF debe tener al menos 9 caracteres'))

    def action_view_invoices(self):
        """Abrir lista de facturas del cliente"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Facturas de %s') % self.name,
            'res_model': 'verifacti.invoice',
            'view_mode': 'tree,form',
            'domain': [('customer_id', '=', self.id)],
            'context': {
                'default_customer_id': self.id,
                'search_default_this_month': 1,
            }
        }

    def name_get(self):
        """Mostrar NIF junto al nombre si existe"""
        result = []
        for customer in self:
            if customer.nif:
                name = f"{customer.name} ({customer.nif})"
            else:
                name = customer.name
            result.append((customer.id, name))
        return result
