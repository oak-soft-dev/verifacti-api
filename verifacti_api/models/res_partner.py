# -*- coding: utf-8 -*-

from odoo import models, fields


class ResPartner(models.Model):
    """Extend res.partner para marcar clientes VeriFactu"""
    _inherit = 'res.partner'

    is_verifacti_customer = fields.Boolean(
        string='Cliente VeriFactu',
        help='Marcar si este contacto es un cliente para facturas VeriFactu'
    )

    verifacti_invoice_count = fields.Integer(
        string='Núm. Facturas VeriFactu',
        compute='_compute_verifacti_invoice_count'
    )

    def _compute_verifacti_invoice_count(self):
        for partner in self:
            partner.verifacti_invoice_count = self.env['verifacti.invoice'].search_count([
                ('customer_id', '=', partner.id)
            ])

    def action_view_verifacti_invoices(self):
        """Abrir lista de facturas VeriFactu del cliente"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Facturas VeriFactu',
            'res_model': 'verifacti.invoice',
            'view_mode': 'tree,form',
            'domain': [('customer_id', '=', self.id)],
            'context': {'default_customer_id': self.id}
        }
