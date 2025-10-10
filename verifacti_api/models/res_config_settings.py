# -*- coding: utf-8 -*-

from odoo import models, fields, api, _


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # Configuración API Verifacti - Solo referencia a la configuración por defecto de la compañía
    verifacti_api_config_id = fields.Many2one(
        'verifacti.api.config',
        string='Configuración API Verifacti',
        related='company_id.verifacti_default_api_config_id',
        readonly=False,
        help='Configuración de API Verifacti por defecto para esta compañía. '
             'Puede gestionar todas las configuraciones desde el menú de Configuraciones API.'
    )

    def action_open_verifacti_api_configs(self):
        """Abrir lista de configuraciones API de Verifacti"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Configuraciones API Verifacti'),
            'res_model': 'verifacti.api.config',
            'view_mode': 'tree,form',
            'domain': [('company_id', '=', self.company_id.id)],
            'context': {
                'default_company_id': self.company_id.id,
            }
        }
