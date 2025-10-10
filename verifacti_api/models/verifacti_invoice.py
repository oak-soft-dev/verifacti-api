# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class VerifactiInvoice(models.Model):
    """Modelo para gestión de facturas VeriFactu mediante API Verifacti"""
    _name = 'verifacti.invoice'
    _description = 'Factura VeriFactu (API Verifacti)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'fecha_expedicion desc, id desc'

    name = fields.Char(
        string='Número de Factura',
        required=True,
        index=True,
        copy=False
    )

    # Identificación de la factura
    serie = fields.Char(
        string='Serie',
        default='',
        help='Serie de la factura. Dejar vacío si no se quiere serie.'
    )

    numero = fields.Char(
        string='Número',
        required=True,
        help='Número de la factura'
    )

    # Relaciones
    supplier_id = fields.Many2one(
        'res.company',
        string='Proveedor Emisor',
        required=True,
        ondelete='restrict',
        tracking=True,
        help='Compañía que emite la factura'
    )

    customer_id = fields.Many2one(
        'verifacti.customer',
        string='Cliente',
        ondelete='restrict',
        help='Cliente destinatario de la factura (opcional para facturas simplificadas)'
    )

    # Fechas
    fecha_expedicion = fields.Date(
        string='Fecha de Expedición',
        required=True,
        default=fields.Date.context_today,
        help='Fecha de emisión de la factura'
    )

    fecha_operacion = fields.Date(
        string='Fecha de Operación',
        help='Fecha de la operación (si es diferente de la expedición)'
    )

    # Tipo de factura
    tipo_factura = fields.Selection(
        [('F1', 'F1: Factura'),
         ('F2', 'F2: Factura simplificada'),
         ('R1', 'R1: Rectificativa (Art 80.1, 80.2)'),
         ('R2', 'R2: Rectificativa (Art. 80.3)'),
         ('R3', 'R3: Rectificativa (Art. 80.4)'),
         ('R4', 'R4: Rectificativa (Resto)'),
         ('R5', 'R5: Rectificativa simplificada'),
         ('F3', 'F3: Sustitución de simplificadas')],
        string='Tipo de Factura',
        required=True,
        default='F1'
    )

    descripcion = fields.Text(
        string='Descripción',
        required=True,
        help='Descripción de la operación (máx 500 caracteres)'
    )

    # Moneda
    currency_id = fields.Many2one(
        'res.currency',
        string='Moneda',
        default=lambda self: self.env.company.currency_id,
        required=True
    )

    # Importes
    importe_total = fields.Monetary(
        string='Importe Total',
        currency_field='currency_id',
        compute='_compute_amounts',
        store=True,
        help='Importe total de la factura (base + IVA + recargo)'
    )

    # Líneas
    line_ids = fields.One2many(
        'verifacti.invoice.line',
        'invoice_id',
        string='Líneas de Factura',
        copy=True
    )

    line_count = fields.Integer(
        string='Núm. Líneas',
        compute='_compute_line_count'
    )

    # Cliente (campos duplicados para facilitar uso)
    customer_nif = fields.Char(
        string='NIF Cliente',
        related='customer_id.nif',
        readonly=True
    )

    customer_name = fields.Char(
        string='Nombre Cliente',
        related='customer_id.name',
        readonly=True
    )

    # Validación de destinatario
    validar_destinatario = fields.Boolean(
        string='Validar Destinatario en AEAT',
        default=True,
        help='Validar que el NIF del destinatario está censado en AEAT antes de enviar'
    )

    # Campos para facturas rectificativas
    tipo_rectificativa = fields.Selection(
        [('S', 'Sustitución'),
         ('I', 'Diferencia')],
        string='Tipo Rectificativa',
        help='Requerido solo para facturas rectificativas (R1-R5)'
    )

    # Incidencia
    incidencia = fields.Boolean(
        string='Indicador de Incidencia',
        default=False,
        help='Marcar si ha ocurrido alguna incidencia'
    )

    # Estado VeriFactu/API
    state = fields.Selection(
        [('draft', 'Borrador'),
         ('sent', 'Enviado'),
         ('pending', 'Pendiente'),
         ('correct', 'Correcto'),
         ('error', 'Error'),
         ('cancelled', 'Anulado')],
        string='Estado',
        default='draft',
        readonly=True,
        tracking=True
    )

    # Respuesta de Verifacti API
    uuid = fields.Char(
        string='UUID',
        readonly=True,
        help='Identificador único del registro en Verifacti'
    )

    registration_status = fields.Char(
        string='Estado Registro',
        readonly=True,
        help='Estado del registro de facturación'
    )

    verifacti_url = fields.Char(
        string='URL Verificación',
        readonly=True,
        help='URL de verificación del código QR'
    )

    verifacti_qr = fields.Binary(
        string='Código QR',
        attachment=True,
        readonly=True,
        help='Código QR en base64'
    )

    verifacti_huella = fields.Char(
        string='Huella',
        readonly=True,
        help='Huella o hash del registro'
    )

    error_code = fields.Char(
        string='Código Error',
        readonly=True
    )

    error_message = fields.Text(
        string='Mensaje Error',
        readonly=True
    )

    # XMLs
    xml_request = fields.Text(
        string='XML Petición',
        readonly=True,
        help='XML enviado a la AEAT'
    )

    xml_response = fields.Text(
        string='XML Respuesta',
        readonly=True,
        help='XML recibido de la AEAT'
    )

    # Respuesta completa de la API
    api_response = fields.Text(
        string='Respuesta API',
        readonly=True
    )

    # Fechas
    created_at = fields.Datetime(
        string='Fecha Creación',
        default=fields.Datetime.now,
        readonly=True
    )

    updated_at = fields.Datetime(
        string='Última Actualización',
        default=fields.Datetime.now,
        readonly=True
    )

    _sql_constraints = [
        ('serie_numero_fecha_supplier_unique',
         'unique(supplier_id, serie, numero, fecha_expedicion)',
         'Ya existe una factura de este proveedor con la misma serie, número y fecha de expedición'),
    ]

    @api.depends('line_ids')
    def _compute_line_count(self):
        for invoice in self:
            invoice.line_count = len(invoice.line_ids)

    @api.depends('line_ids.base_imponible', 'line_ids.cuota_repercutida',
                 'line_ids.cuota_recargo_equivalencia')
    def _compute_amounts(self):
        for invoice in self:
            total = 0.0
            for line in invoice.line_ids:
                base = float(line.base_imponible) if line.base_imponible else 0.0
                cuota = float(line.cuota_repercutida) if line.cuota_repercutida else 0.0
                recargo = float(line.cuota_recargo_equivalencia) if line.cuota_recargo_equivalencia else 0.0
                total += base + cuota + recargo
            invoice.importe_total = total

    @api.model
    def create(self, vals):
        # Generar nombre automáticamente si no se proporciona
        if not vals.get('name'):
            serie = vals.get('serie', '')
            numero = vals.get('numero', '')
            vals['name'] = f"{serie}{numero}" if serie else numero

        vals['created_at'] = fields.Datetime.now()
        vals['updated_at'] = fields.Datetime.now()
        return super(VerifactiInvoice, self).create(vals)

    def write(self, vals):
        # Regenerar nombre si cambia serie o número
        if 'serie' in vals or 'numero' in vals:
            for invoice in self:
                serie = vals.get('serie', invoice.serie) or ''
                numero = vals.get('numero', invoice.numero) or ''
                vals['name'] = f"{serie}{numero}" if serie else numero

        vals['updated_at'] = fields.Datetime.now()
        return super(VerifactiInvoice, self).write(vals)

    @api.constrains('line_ids')
    def _check_lines_count(self):
        """Validar que no se exceda el límite de 12 líneas"""
        for invoice in self:
            if len(invoice.line_ids) > 12:
                raise ValidationError(_(
                    'La API de la AEAT solo permite hasta 12 líneas por factura. '
                    'Por favor agrupe líneas con el mismo tipo de IVA.'
                ))

    @api.constrains('descripcion')
    def _check_descripcion_length(self):
        """Validar longitud de descripción"""
        for invoice in self:
            if invoice.descripcion and len(invoice.descripcion) > 500:
                raise ValidationError(_(
                    'La descripción no puede exceder 500 caracteres'
                ))

    def action_send_to_verifacti(self):
        """Enviar factura a Verifacti API"""
        self.ensure_one()

        if not self.line_ids:
            raise UserError(_('La factura debe tener al menos una línea'))

        if self.state not in ['draft', 'error']:
            raise UserError(_('Solo se pueden enviar facturas en estado borrador o error'))

        if not self.supplier_id:
            raise UserError(_('Debe especificar el proveedor emisor'))

        # Obtener configuración API
        api_config = self._get_api_config()

        api_client = self.env['verifacti.api.client']

        try:
            # Preparar datos de la factura
            invoice_data = self._prepare_verifacti_invoice_data()

            # Enviar a Verifacti API usando la configuración de API
            response = api_client.with_context(
                verifacti_api_config_id=api_config.id
            ).create_invoice(invoice_data)

            # Procesar respuesta
            self._process_verifacti_response(response)

            # Incrementar contador de uso de la configuración
            api_config.increment_usage()

            # Programar verificación periódica del estado
            self.env.ref('verifacti_api.ir_cron_check_registration_status').sudo()._trigger()

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Factura Enviada'),
                    'message': _('La factura ha sido enviada correctamente a Verifacti'),
                    'type': 'success',
                    'sticky': False,
                }
            }

        except Exception as e:
            self.write({
                'state': 'error',
                'error_message': str(e)
            })
            raise UserError(_('Error al enviar factura: %s') % str(e))

    def action_check_registration_status(self):
        """Verificar estado del registro de facturación"""
        self.ensure_one()

        if not self.uuid:
            raise UserError(_('No hay un UUID asociado a esta factura'))

        api_config = self._get_api_config()
        api_client = self.env['verifacti.api.client']

        try:
            response = api_client.with_context(
                verifacti_api_config_id=api_config.id
            ).get_registration_status(self.uuid)
            self._process_registration_status(response)

            return True

        except Exception as e:
            raise UserError(_('Error al verificar estado: %s') % str(e))

    def action_check_invoice_status(self):
        """Verificar estado de la factura en AEAT"""
        self.ensure_one()

        api_config = self._get_api_config()
        api_client = self.env['verifacti.api.client']

        try:
            fecha_exp = api_client.format_date(self.fecha_expedicion)
            fecha_op = api_client.format_date(self.fecha_operacion) if self.fecha_operacion else None

            response = api_client.with_context(
                verifacti_api_config_id=api_config.id
            ).get_invoice_status(
                self.serie,
                self.numero,
                fecha_exp,
                fecha_op
            )

            self._process_invoice_status(response)

            return True

        except Exception as e:
            raise UserError(_('Error al verificar estado en AEAT: %s') % str(e))

    def action_download_xmls(self):
        """Descargar XMLs de la factura"""
        self.ensure_one()

        api_config = self._get_api_config()
        api_client = self.env['verifacti.api.client']

        try:
            response = api_client.with_context(
                verifacti_api_config_id=api_config.id
            ).download_xml(self.serie, self.numero)

            if response:
                # Tomar el primer resultado (puede haber varios si hay anulaciones)
                xml_data = response[0] if isinstance(response, list) else response

                self.write({
                    'xml_request': xml_data.get('xml_req', ''),
                    'xml_response': xml_data.get('xml_res', ''),
                })

                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('XMLs Descargados'),
                        'message': _('Los XMLs han sido descargados correctamente'),
                        'type': 'success',
                        'sticky': False,
                    }
                }

        except Exception as e:
            raise UserError(_('Error al descargar XMLs: %s') % str(e))

    def action_cancel_invoice(self):
        """Anular factura en Verifacti"""
        self.ensure_one()

        if self.state == 'cancelled':
            raise UserError(_('La factura ya está anulada'))

        api_config = self._get_api_config()
        api_client = self.env['verifacti.api.client']

        try:
            fecha_exp = api_client.format_date(self.fecha_expedicion)

            response = api_client.with_context(
                verifacti_api_config_id=api_config.id
            ).cancel_invoice(
                self.serie,
                self.numero,
                fecha_exp,
                rechazo_previo='N',
                sin_registro_previo='N',
                incidencia='S' if self.incidencia else None
            )

            # Crear nuevo registro con estado de anulación
            self.write({
                'state': 'cancelled',
                'api_response': str(response)
            })

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Factura Anulada'),
                    'message': _('La factura ha sido anulada correctamente'),
                    'type': 'success',
                    'sticky': False,
                }
            }

        except Exception as e:
            raise UserError(_('Error al anular factura: %s') % str(e))

    def action_reset_to_draft(self):
        """Resetear factura a borrador"""
        self.ensure_one()
        self.write({'state': 'draft'})

    def _get_api_config(self):
        """
        Obtener configuración de API para esta factura
        (usa la configuración por defecto del proveedor/compañía)

        :return: registro de verifacti.api.config
        """
        self.ensure_one()

        if not self.supplier_id:
            raise UserError(_('Debe especificar el proveedor emisor'))

        return self.supplier_id.get_verifacti_api_config()

    def _prepare_verifacti_invoice_data(self):
        """Preparar estructura de datos para Verifacti API"""
        self.ensure_one()

        api_client = self.env['verifacti.api.client']

        # Preparar líneas
        lineas = []
        for line in self.line_ids:
            line_data = {
                'base_imponible': line.base_imponible,
                'impuesto': line.impuesto,
            }

            if line.tipo_impositivo:
                line_data['tipo_impositivo'] = line.tipo_impositivo
            if line.cuota_repercutida:
                line_data['cuota_repercutida'] = line.cuota_repercutida
            if line.calificacion_operacion:
                line_data['calificacion_operacion'] = line.calificacion_operacion
            if line.clave_regimen:
                line_data['clave_regimen'] = line.clave_regimen
            if line.operacion_exenta:
                line_data['operacion_exenta'] = line.operacion_exenta
            if line.base_imponible_a_coste:
                line_data['base_imponible_a_coste'] = line.base_imponible_a_coste
            if line.tipo_recargo_equivalencia:
                line_data['tipo_recargo_equivalencia'] = line.tipo_recargo_equivalencia
            if line.cuota_recargo_equivalencia:
                line_data['cuota_recargo_equivalencia'] = line.cuota_recargo_equivalencia

            lineas.append(line_data)

        # Estructura básica
        invoice_data = {
            'serie': self.serie or '',
            'numero': self.numero,
            'fecha_expedicion': api_client.format_date(self.fecha_expedicion),
            'tipo_factura': self.tipo_factura,
            'descripcion': self.descripcion,
            'lineas': lineas,
            'importe_total': str(self.importe_total),
            'validar_destinatario': self.validar_destinatario,
        }

        # Fecha de operación si es diferente
        if self.fecha_operacion:
            invoice_data['fecha_operacion'] = api_client.format_date(self.fecha_operacion)

        # Datos del cliente (solo para facturas no simplificadas)
        if self.tipo_factura not in ['F2', 'R5']:
            if self.customer_id and self.customer_id.nif:
                invoice_data['nif'] = self.customer_id.nif
            if self.customer_id:
                invoice_data['nombre'] = self.customer_id.name

        # Tipo rectificativa
        if self.tipo_rectificativa:
            invoice_data['tipo_rectificativa'] = self.tipo_rectificativa

        # Incidencia
        if self.incidencia:
            invoice_data['incidencia'] = 'S'

        return invoice_data

    def _process_verifacti_response(self, response):
        """Procesar respuesta de creación de factura"""
        self.ensure_one()

        import base64

        vals = {
            'uuid': response.get('uuid'),
            'registration_status': response.get('estado', 'Pendiente'),
            'verifacti_url': response.get('url'),
            'verifacti_huella': response.get('huella'),
            'api_response': str(response),
            'state': 'pending'
        }

        # Decodificar QR de base64
        if response.get('qr'):
            vals['verifacti_qr'] = response.get('qr')

        self.write(vals)

    def _process_registration_status(self, response):
        """Procesar respuesta de estado de registro"""
        self.ensure_one()

        vals = {
            'registration_status': response.get('estado'),
            'api_response': str(response)
        }

        estado = response.get('estado')

        # Actualizar estado según respuesta
        if estado == 'Correcto':
            vals['state'] = 'correct'
        elif estado == 'Pendiente':
            vals['state'] = 'pending'
        elif estado in ['Incorrecto', 'No registrado']:
            vals['state'] = 'error'
            vals['error_code'] = response.get('codigo_error')
            vals['error_message'] = response.get('mensaje_error')
        elif estado == 'Anulado':
            vals['state'] = 'cancelled'

        self.write(vals)

    def _process_invoice_status(self, response):
        """Procesar respuesta de estado de factura en AEAT"""
        self.ensure_one()

        vals = {
            'api_response': str(response)
        }

        estado = response.get('estado')

        if estado == 'Correcta':
            vals['state'] = 'correct'
        elif estado == 'AceptadaConErrores':
            vals['state'] = 'error'
            vals['error_message'] = 'Factura aceptada con errores. Debe ser subsanada.'
        elif estado == 'Anulada':
            vals['state'] = 'cancelled'

        # Actualizar huella si viene
        if response.get('huella'):
            vals['verifacti_huella'] = response.get('huella')

        self.write(vals)

    @api.model
    def cron_check_pending_registrations(self):
        """Cron para verificar estado de facturas pendientes"""
        invoices = self.search([
            ('state', 'in', ['pending', 'sent']),
            ('uuid', '!=', False),
            ('supplier_id', '!=', False)
        ])

        api_client = self.env['verifacti.api.client']

        for invoice in invoices:
            try:
                # Obtener configuración API de esta factura
                api_config = invoice._get_api_config()

                response = api_client.with_context(
                    verifacti_api_config_id=api_config.id
                ).get_registration_status(invoice.uuid)
                invoice._process_registration_status(response)
            except Exception as e:
                # Registrar error pero continuar con las demás
                self.env['verifacti.api.log'].sudo().create({
                    'endpoint': f'/verifacti/status?uuid={invoice.uuid}',
                    'method': 'GET',
                    'status_code': 0,
                    'error': str(e)
                })
                continue
