# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ResCompany(models.Model):
    """Extender res.company para gestionar proveedores Verifacti"""
    _inherit = 'res.company'

    # Configuraciones de API Verifacti
    verifacti_api_config_ids = fields.One2many(
        'verifacti.api.config',
        'company_id',
        string='Configuraciones API Verifacti',
        help='Configuraciones de API Key de Verifacti para esta compañía'
    )

    verifacti_api_config_count = fields.Integer(
        string='Núm. Configuraciones API',
        compute='_compute_verifacti_api_config_count'
    )

    verifacti_default_api_config_id = fields.Many2one(
        'verifacti.api.config',
        string='Configuración API por Defecto',
        compute='_compute_default_api_config',
        store=True,
        help='Configuración de API marcada como predeterminada para esta compañía'
    )

    # Facturas emitidas como proveedor
    verifacti_supplier_invoice_ids = fields.One2many(
        'verifacti.invoice',
        'supplier_id',
        string='Facturas Emitidas (Verifacti)',
        help='Facturas emitidas por esta compañía a través de Verifacti'
    )

    verifacti_supplier_invoice_count = fields.Integer(
        string='Núm. Facturas Emitidas',
        compute='_compute_verifacti_supplier_invoice_count'
    )

    # Indicador de si es proveedor Verifacti
    is_verifacti_supplier = fields.Boolean(
        string='Es Proveedor Verifacti',
        compute='_compute_is_verifacti_supplier',
        store=True,
        help='Indica si esta compañía tiene configuraciones de API Verifacti activas'
    )

    @api.depends('verifacti_api_config_ids')
    def _compute_verifacti_api_config_count(self):
        for company in self:
            company.verifacti_api_config_count = len(company.verifacti_api_config_ids)

    @api.depends('verifacti_api_config_ids.is_default')
    def _compute_default_api_config(self):
        for company in self:
            default_config = company.verifacti_api_config_ids.filtered('is_default')
            company.verifacti_default_api_config_id = default_config[:1] if default_config else False

    @api.depends('verifacti_supplier_invoice_ids')
    def _compute_verifacti_supplier_invoice_count(self):
        for company in self:
            company.verifacti_supplier_invoice_count = len(company.verifacti_supplier_invoice_ids)

    @api.depends('verifacti_api_config_ids.active')
    def _compute_is_verifacti_supplier(self):
        for company in self:
            company.is_verifacti_supplier = bool(
                company.verifacti_api_config_ids.filtered('active')
            )

    def action_view_verifacti_api_configs(self):
        """Abrir lista de configuraciones API de esta compañía"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Configuraciones API Verifacti - %s') % self.name,
            'res_model': 'verifacti.api.config',
            'view_mode': 'tree,form',
            'domain': [('company_id', '=', self.id)],
            'context': {
                'default_company_id': self.id,
            }
        }

    def action_create_verifacti_api_config(self):
        """Crear nueva configuración API para esta compañía"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Nueva Configuración API - %s') % self.name,
            'res_model': 'verifacti.api.config',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_company_id': self.id,
            }
        }

    def action_view_verifacti_supplier_invoices(self):
        """Abrir lista de facturas emitidas por esta compañía"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Facturas Emitidas - %s') % self.name,
            'res_model': 'verifacti.invoice',
            'view_mode': 'tree,form',
            'domain': [('supplier_id', '=', self.id)],
            'context': {
                'default_supplier_id': self.id,
                'search_default_this_month': 1,
            }
        }

    def get_verifacti_api_config(self, config_name=None):
        """
        Obtener configuración de API para esta compañía

        :param config_name: Nombre de la configuración específica (opcional)
        :return: registro de verifacti.api.config
        """
        self.ensure_one()

        if config_name:
            # Buscar configuración por nombre
            config = self.verifacti_api_config_ids.filtered(
                lambda c: c.name == config_name and c.active
            )
            if not config:
                raise UserError(
                    _('No se encontró una configuración activa con el nombre "%s" para la compañía %s') %
                    (config_name, self.name)
                )
            return config[:1]
        else:
            # Usar configuración por defecto
            if not self.verifacti_default_api_config_id:
                raise UserError(
                    _('No hay una configuración API por defecto para la compañía %s.\n'
                      'Por favor, configure al menos una configuración de API y márquela como predeterminada.') %
                    self.name
                )
            return self.verifacti_default_api_config_id
