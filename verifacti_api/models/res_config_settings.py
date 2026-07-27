# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ResConfigSettings(models.TransientModel):
    """Configuración de Verifacti en Ajustes de Odoo - Por Compañía"""
    _inherit = 'res.config.settings'

    # Proveedor de la API VeriFactu
    verifacti_provider = fields.Selection(
        [
            ('verifacti', 'Verifacti (SaaS)'),
            ('propio', 'API VeriFactu propia (l10n_es_api_verifacti)'),
        ],
        string='Proveedor',
        default='verifacti',
        help='Backend que procesa las facturas VeriFactu: el SaaS de Verifacti '
             'o el servidor propio (módulo l10n_es_api_verifacti)'
    )

    # API Key de Verifacti
    verifacti_api_key = fields.Char(
        string='API Key',
        help='Tu API Key de Verifacti (pruebas o producción)'
    )

    verifacti_api_url = fields.Char(
        string='URL API',
        default='https://api.verifacti.com',
        help='URL base de la API'
    )

    # Credenciales del servidor propio (l10n_es_api_verifacti)
    verifacti_propio_api_url = fields.Char(
        string='URL API propia',
        default='http://localhost:8069',
        help='URL base del Odoo donde está instalado l10n_es_api_verifacti'
    )

    verifacti_propio_api_key = fields.Char(
        string='API Key propia',
        help='API Key del emisor configurado en l10n_es_api_verifacti '
             '(VeriFactu Server > Emisores)'
    )

    # Configuración de reintentos y timeout
    verifacti_max_retries = fields.Integer(
        string='Reintentos',
        default=3,
        help='Intentos en caso de error (1-10)'
    )

    verifacti_retry_delay = fields.Integer(
        string='Espera (segundos)',
        default=2,
        help='Segundos entre reintentos (1-30)'
    )

    verifacti_auto_send_enabled = fields.Boolean(
        string='Envío Automático',
        default=False,
        help='Si está activado, las facturas publicadas se enviarán automáticamente a VeriFactu cada minuto (límite AEAT)'
    )

    # Límite de operaciones masivas
    verifacti_max_bulk_limit = fields.Integer(
        string='Límite Operaciones Masivas sobre Facturas',
        default=10,
        help='Número máximo de facturas que se pueden procesar en operaciones masivas (enviar/verificar)'
    )

    # Control de carga del sistema
    verifacti_check_system_load = fields.Boolean(
        string='Control de Carga',
        default=True,
        help='Pausar envío si el sistema está muy cargado'
    )

    verifacti_max_system_load = fields.Float(
        string='Carga Máxima',
        default=4.0,
        help='Load average máximo permitido (recomendado: CPUs × 0.7)'
    )

    # Filtro de fecha mínima
    verifacti_min_invoice_date = fields.Date(
        string='Fecha Mínima Facturas',
        default='2025-01-01',
        help='El cron automático solo enviará facturas con fecha igual o posterior a esta.\n\n'
             'IMPORTANTE: VeriFactu NO es retroactivo. Las facturas anteriores a 2025 generalmente no necesitan enviarse.\n\n'
             'VeriFactu es obligatorio desde: 01/01/2026 (empresas) y 01/07/2026 (autónomos).\n'
             'Valor por defecto: 01/01/2025'
    )

    # Sector especial para límite de factura simplificada
    verifacti_sector_especial = fields.Boolean(
        string='Sector Especial (3.000€)',
        default=False,
        help='Marcar si la empresa pertenece a un sector especial según Art. 4.2 RD 1619/2012.\n\n'
             '✅ SECTORES ESPECIALES (límite 3.000€ para factura simplificada):\n'
             '  • Hostelería (restaurantes, bares, cafeterías)\n'
             '  • Ventas al por menor\n'
             '  • Servicios en ambulancias\n'
             '  • Uso de autopistas de peaje\n'
             '  • Salas de baile y discotecas\n'
             '  • Peluquerías e institutos de belleza\n'
             '  • Instalaciones deportivas\n'
             '  • Transporte de personas y equipajes\n'
             '  • Entregas a domicilio a particulares\n\n'
             '❌ OTROS SECTORES (límite estándar 400€ para factura simplificada):\n'
             '  • Servicios profesionales\n'
             '  • Comercio mayorista\n'
             '  • Industria\n'
             '  • Otros servicios\n\n'
             'Si NO está marcado: límite de 400€\n'
             'Si SÍ está marcado: límite de 3.000€'
    )

    # Estado de pausa (solo lectura)
    verifacti_auto_send_paused = fields.Boolean(
        string='Pausado',
        readonly=True,
        help='Envío pausado por carga alta'
    )

    verifacti_auto_send_paused_reason = fields.Text(
        string='Razón',
        readonly=True,
        help='Por qué se pausó'
    )

    verifacti_auto_send_paused_since = fields.Datetime(
        string='Desde',
        readonly=True,
        help='Cuándo se pausó'
    )

    @api.model
    def _get_param_key(self, company_id, param):
        """Generar clave de parámetro por compañía"""
        return f'verifacti_api.company_{company_id}.{param}'

    @api.model
    def get_values(self):
        """Obtener valores desde ir.config_parameter por compañía"""
        res = super(ResConfigSettings, self).get_values()

        company_id = self.env.company.id
        IrConfigParameter = self.env['ir.config_parameter'].sudo()

        res.update({
            'verifacti_provider': IrConfigParameter.get_param(
                self._get_param_key(company_id, 'provider'), default='verifacti'
            ),
            'verifacti_api_key': IrConfigParameter.get_param(
                self._get_param_key(company_id, 'api_key'), default=''
            ),
            'verifacti_api_url': IrConfigParameter.get_param(
                self._get_param_key(company_id, 'api_url'), default='https://api.verifacti.com'
            ),
            'verifacti_propio_api_url': IrConfigParameter.get_param(
                self._get_param_key(company_id, 'propio_api_url'), default='http://localhost:8069'
            ),
            'verifacti_propio_api_key': IrConfigParameter.get_param(
                self._get_param_key(company_id, 'propio_api_key'), default=''
            ),
            'verifacti_max_retries': int(IrConfigParameter.get_param(
                self._get_param_key(company_id, 'max_retries'), default='3'
            )),
            'verifacti_retry_delay': int(IrConfigParameter.get_param(
                self._get_param_key(company_id, 'retry_delay'), default='2'
            )),
            'verifacti_auto_send_enabled': IrConfigParameter.get_param(
                self._get_param_key(company_id, 'auto_send_enabled'), default='False'
            ) == 'True',
            'verifacti_max_bulk_limit': int(IrConfigParameter.get_param(
                self._get_param_key(company_id, 'max_bulk_limit'), default='10'
            )),
            'verifacti_check_system_load': IrConfigParameter.get_param(
                self._get_param_key(company_id, 'check_system_load'), default='True'
            ) == 'True',
            'verifacti_max_system_load': float(IrConfigParameter.get_param(
                self._get_param_key(company_id, 'max_system_load'), default='4.0'
            )),
            'verifacti_min_invoice_date': IrConfigParameter.get_param(
                self._get_param_key(company_id, 'min_invoice_date'), default='2025-01-01'
            ),
            'verifacti_sector_especial': IrConfigParameter.get_param(
                self._get_param_key(company_id, 'sector_especial'), default='False'
            ) == 'True',
            'verifacti_auto_send_paused': IrConfigParameter.get_param(
                self._get_param_key(company_id, 'auto_send_paused'), default='False'
            ) == 'True',
            'verifacti_auto_send_paused_reason': IrConfigParameter.get_param(
                self._get_param_key(company_id, 'auto_send_paused_reason'), default=''
            ),
        })

        # Convertir campo datetime desde string
        paused_since_str = IrConfigParameter.get_param(
            self._get_param_key(company_id, 'auto_send_paused_since'), default=''
        )
        if paused_since_str:
            try:
                res['verifacti_auto_send_paused_since'] = fields.Datetime.from_string(paused_since_str)
            except (ValueError, TypeError):
                res['verifacti_auto_send_paused_since'] = False
        else:
            res['verifacti_auto_send_paused_since'] = False

        return res

    def set_values(self):
        """Guardar valores en ir.config_parameter por compañía"""
        super(ResConfigSettings, self).set_values()

        company_id = self.env.company.id
        IrConfigParameter = self.env['ir.config_parameter'].sudo()

        IrConfigParameter.set_param(
            self._get_param_key(company_id, 'provider'),
            self.verifacti_provider or 'verifacti'
        )
        IrConfigParameter.set_param(
            self._get_param_key(company_id, 'api_key'),
            self.verifacti_api_key or ''
        )
        IrConfigParameter.set_param(
            self._get_param_key(company_id, 'propio_api_url'),
            self.verifacti_propio_api_url or 'http://localhost:8069'
        )
        IrConfigParameter.set_param(
            self._get_param_key(company_id, 'propio_api_key'),
            self.verifacti_propio_api_key or ''
        )
        IrConfigParameter.set_param(
            self._get_param_key(company_id, 'api_url'),
            self.verifacti_api_url or 'https://api.verifacti.com'
        )
        IrConfigParameter.set_param(
            self._get_param_key(company_id, 'max_retries'),
            str(self.verifacti_max_retries or 3)
        )
        IrConfigParameter.set_param(
            self._get_param_key(company_id, 'retry_delay'),
            str(self.verifacti_retry_delay or 2)
        )
        IrConfigParameter.set_param(
            self._get_param_key(company_id, 'auto_send_enabled'),
            str(self.verifacti_auto_send_enabled)
        )
        IrConfigParameter.set_param(
            self._get_param_key(company_id, 'max_bulk_limit'),
            str(self.verifacti_max_bulk_limit or 10)
        )
        IrConfigParameter.set_param(
            self._get_param_key(company_id, 'check_system_load'),
            str(self.verifacti_check_system_load)
        )
        IrConfigParameter.set_param(
            self._get_param_key(company_id, 'max_system_load'),
            str(self.verifacti_max_system_load or 4.0)
        )
        IrConfigParameter.set_param(
            self._get_param_key(company_id, 'min_invoice_date'),
            str(self.verifacti_min_invoice_date or '2025-01-01')
        )
        IrConfigParameter.set_param(
            self._get_param_key(company_id, 'sector_especial'),
            str(self.verifacti_sector_especial)
        )

    def action_resume_verifacti_auto_send(self):
        """Reanudar manualmente el envío automático"""
        self.ensure_one()

        company_id = self.env.company.id
        IrConfigParameter = self.env['ir.config_parameter'].sudo()

        # Verificar si está pausado
        is_paused = IrConfigParameter.get_param(
            self._get_param_key(company_id, 'auto_send_paused'), default='False'
        ) == 'True'

        if not is_paused:
            raise UserError(_('El envío automático no está pausado'))

        # Reanudar
        IrConfigParameter.set_param(self._get_param_key(company_id, 'auto_send_paused'), 'False')
        IrConfigParameter.set_param(self._get_param_key(company_id, 'auto_send_paused_reason'), '')
        IrConfigParameter.set_param(self._get_param_key(company_id, 'auto_send_paused_since'), '')

        # Log la reanudación manual
        self.env['verifacti.api.log'].sudo().create({
            'endpoint': '/manual/resume',
            'method': 'RESUME',
            'status_code': 200,
            'response_data': f'▶️ REANUDACIÓN MANUAL - {self.env.company.name}: Envío automático reanudado manualmente'
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Envío Reanudado'),
                'message': _('El envío automático ha sido reanudado correctamente'),
                'type': 'success',
                'sticky': False,
            }
        }
