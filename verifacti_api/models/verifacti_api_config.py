# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class VerifactiApiConfig(models.Model):
    """Configuración de API Key para Verifacti"""
    _name = 'verifacti.api.config'
    _description = 'Configuración API Key Verifacti'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(
        string='Nombre Configuración',
        required=True,
        tracking=True,
        help='Nombre descriptivo de esta configuración (ej: Desarrollo, Producción, Testing)'
    )

    api_key = fields.Char(
        string='API Key',
        required=True,
        tracking=True,
        help='Token de API obtenido de Verifacti para esta configuración'
    )

    company_id = fields.Many2one(
        'res.company',
        string='Compañía',
        required=True,
        ondelete='cascade',
        tracking=True,
        help='Compañía propietaria de esta configuración de API'
    )

    api_url = fields.Char(
        string='URL de la API',
        default='https://api.verifacti.com',
        required=True,
        help='URL base de la API de Verifacti (normalmente no requiere cambios)'
    )

    environment = fields.Selection([
        ('test', 'Pruebas'),
        ('production', 'Producción'),
    ], string='Entorno', default='test', required=True, tracking=True,
        help='Entorno al que pertenece esta configuración')

    active = fields.Boolean(
        string='Activo',
        default=True,
        tracking=True
    )

    is_default = fields.Boolean(
        string='Configuración por Defecto',
        default=False,
        tracking=True,
        help='Si está marcada, será la configuración utilizada por defecto para esta compañía'
    )

    # Estadísticas de uso
    last_used_date = fields.Datetime(
        string='Último Uso',
        readonly=True,
        help='Fecha y hora del último uso de esta configuración'
    )

    usage_count = fields.Integer(
        string='Número de Usos',
        readonly=True,
        default=0,
        help='Contador de veces que se ha utilizado esta configuración'
    )

    notes = fields.Text(
        string='Notas',
        help='Notas adicionales sobre esta configuración'
    )

    # Relaciones
    # Nota: Las facturas ahora se relacionan con la compañía, no directamente con la configuración API
    # La configuración se obtiene a través de company_id.verifacti_default_api_config_id

    invoice_count = fields.Integer(
        string='Núm. Facturas',
        compute='_compute_invoice_count',
        help='Número de facturas emitidas por la compañía de esta configuración'
    )

    _sql_constraints = [
        ('name_company_unique',
         'unique(name, company_id)',
         'Ya existe una configuración con este nombre para esta compañía'),
    ]

    @api.depends('company_id.verifacti_supplier_invoice_ids')
    def _compute_invoice_count(self):
        """Contar facturas emitidas por la compañía de esta configuración"""
        for config in self:
            # Contar facturas de la compañía
            config.invoice_count = len(config.company_id.verifacti_supplier_invoice_ids)

    @api.constrains('is_default')
    def _check_single_default(self):
        """Asegurar que solo hay una configuración por defecto por compañía"""
        for config in self:
            if config.is_default:
                other_defaults = self.search([
                    ('company_id', '=', config.company_id.id),
                    ('is_default', '=', True),
                    ('id', '!=', config.id)
                ])
                if other_defaults:
                    raise ValidationError(
                        _('Solo puede haber una configuración por defecto por compañía. '
                          'La configuración "%s" ya está marcada como predeterminada.') %
                        other_defaults[0].name
                    )

    @api.constrains('api_key')
    def _check_api_key(self):
        """Validación básica de API Key"""
        for config in self:
            if config.api_key:
                api_key = config.api_key.strip()
                if len(api_key) < 20:
                    raise ValidationError(_('La API Key parece inválida (muy corta)'))

    def action_test_connection(self):
        """Probar conexión con la API usando esta configuración"""
        self.ensure_one()

        if not self.api_key:
            raise UserError(_('Debe configurar la API Key'))

        api_client = self.env['verifacti.api.client']

        try:
            # Pasar la configuración de API específica
            response = api_client.with_context(
                verifacti_api_config_id=self.id
            ).health_check()

            if response.get('estado') == 'OK':
                # Registrar uso
                self.sudo().write({
                    'last_used_date': fields.Datetime.now(),
                    'usage_count': self.usage_count + 1
                })

                # Registrar mensaje en el chatter
                self.message_post(
                    body=_('Prueba de conexión exitosa\nNIF: %s\nEstado: %s') % (
                        response.get('nif', 'N/A'),
                        response.get('estado', 'N/A')
                    ),
                    subject=_('Conexión Exitosa'),
                    message_type='notification'
                )

                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Conexión Exitosa'),
                        'message': _('Conectado correctamente a Verifacti API\nNIF: %s\nEntorno: %s') % (
                            response.get('nif', 'N/A'),
                            dict(self._fields['environment'].selection).get(self.environment)
                        ),
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                raise UserError(_('Respuesta inesperada de la API'))

        except Exception as e:
            error_msg = str(e)
            # Registrar error en el chatter
            self.message_post(
                body=_('Error en prueba de conexión: %s') % error_msg,
                subject=_('Error de Conexión'),
                message_type='notification'
            )

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Error de Conexión'),
                    'message': error_msg,
                    'type': 'danger',
                    'sticky': True,
                }
            }

    def action_set_as_default(self):
        """Marcar esta configuración como predeterminada"""
        self.ensure_one()

        # Desmarcar otras configuraciones por defecto de la misma compañía
        other_defaults = self.search([
            ('company_id', '=', self.company_id.id),
            ('is_default', '=', True),
            ('id', '!=', self.id)
        ])
        other_defaults.write({'is_default': False})

        # Marcar esta como predeterminada
        self.write({'is_default': True})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Configuración Actualizada'),
                'message': _('Esta configuración se ha marcado como predeterminada'),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_view_invoices(self):
        """Ver facturas emitidas por la compañía de esta configuración"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Facturas de %s') % self.company_id.name,
            'res_model': 'verifacti.invoice',
            'view_mode': 'tree,form',
            'domain': [('supplier_id', '=', self.company_id.id)],
            'context': {
                'default_supplier_id': self.company_id.id,
            }
        }

    def increment_usage(self):
        """Incrementar contador de uso (llamado al usar la API)"""
        self.ensure_one()
        self.sudo().write({
            'last_used_date': fields.Datetime.now(),
            'usage_count': self.usage_count + 1
        })

    def name_get(self):
        """Mostrar nombre con compañía y entorno"""
        result = []
        for config in self:
            env_label = dict(config._fields['environment'].selection).get(config.environment, '')
            name = f"{config.name} ({config.company_id.name} - {env_label})"
            if config.is_default:
                name += " [Default]"
            result.append((config.id, name))
        return result
