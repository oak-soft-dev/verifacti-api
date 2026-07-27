# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare
import os
import re
import logging
import json

_logger = logging.getLogger(__name__)

# ============================================
# CONSTANTES
# ============================================
MAX_LINES_BEFORE_GROUPING = 12  # Límite AEAT para líneas de factura
BATCH_SIZE = 50  # Límite API para envío en lote


class AccountMove(models.Model):
    """Extensión de account.move para integración con Verifacti API"""

    _inherit = "account.move"

    # ============================================
    # HELPER METHODS
    # ============================================

    @api.model
    def _get_param_key(self, company_id, param):
        """Generar clave de parámetro por compañía"""
        return f'verifacti_api.company_{company_id}.{param}'

    def _get_verifacti_config(self, param, default=None):
        """Obtener configuración de Verifacti desde ir.config_parameter"""
        IrConfigParameter = self.env['ir.config_parameter'].sudo()
        company_id = self.company_id.id if hasattr(self, 'company_id') else self.env.company.id

        value = IrConfigParameter.get_param(
            self._get_param_key(company_id, param),
            default=str(default) if default is not None else ''
        )

        # Convertir a tipo apropiado
        if param in ['auto_send_enabled', 'sector_especial', 'check_system_load', 'auto_send_paused']:
            return value == 'True'
        elif param in ['max_retries', 'retry_delay', 'max_bulk_limit']:
            return int(value) if value else (default or 0)
        elif param == 'max_system_load':
            return float(value) if value else (default or 0.0)
        else:
            return value

    # ============================================
    # CAMPOS VERIFACTU
    # ============================================

    # Estado VeriFactu/API
    verifacti_state = fields.Selection(
        [
            ("draft", "Borrador"),
            ("sent", "Enviado"),
            ("pending", "Pendiente"),
            ("correct", "Correcto"),
            ("error", "Error"),
            ("cancelled", "Anulado"),
        ],
        string="Estado VeriFactu",
        default="draft",
        readonly=True,
        tracking=True,
        help="Estado del envío a VeriFactu",
    )

    # Respuesta de Verifacti API
    verifacti_uuid = fields.Char(
        string="UUID VeriFactu",
        readonly=True,
        copy=False,
        help="Identificador único del registro en Verifacti",
    )

    verifacti_registration_status = fields.Char(
        string="Estado Registro",
        readonly=True,
        copy=False,
        help="Estado del registro de facturación",
    )

    verifacti_url = fields.Char(
        string="URL Verificación",
        readonly=True,
        copy=False,
        help="URL de verificación del código QR",
    )

    verifacti_qr = fields.Binary(
        string="Código QR VeriFactu",
        attachment=True,
        readonly=True,
        copy=False,
        help="Código QR en base64",
    )

    verifacti_huella = fields.Char(
        string="Huella VeriFactu",
        readonly=True,
        copy=False,
        help="Huella o hash del registro",
    )

    verifacti_error_code = fields.Char(string="Código Error", readonly=True, copy=False)

    verifacti_error_message = fields.Text(
        string="Mensaje Error", readonly=True, copy=False
    )

    verifacti_error_summary = fields.Char(
        string="Error",
        compute="_compute_verifacti_error_summary",
        store=False,
        help="Resumen corto del error para mostrar en listas",
    )

    verifacti_error_solution = fields.Text(
        string="Solución",
        compute="_compute_verifacti_error_solution",
        store=False,
        help="Pasos sugeridos para resolver el error",
    )

    # XMLs
    verifacti_xml_request = fields.Text(
        string="XML Petición", readonly=True, copy=False, help="XML enviado a la AEAT"
    )

    verifacti_xml_response = fields.Text(
        string="XML Respuesta",
        readonly=True,
        copy=False,
        help="XML recibido de la AEAT",
    )

    # Respuesta completa de la API
    verifacti_api_response = fields.Text(
        string="Respuesta API VeriFactu", readonly=True, copy=False
    )

    # Configuración VeriFactu
    verifacti_tipo_factura = fields.Selection(
        [
            ("F1", "F1: Factura"),
            ("F2", "F2: Factura simplificada"),
            ("R1", "R1: Rectificativa (Art 80.1, 80.2)"),
            ("R2", "R2: Rectificativa (Art. 80.3)"),
            ("R3", "R3: Rectificativa (Art. 80.4)"),
            ("R4", "R4: Rectificativa (Resto)"),
            ("R5", "R5: Rectificativa simplificada"),
            ("F3", "F3: Sustitución de simplificadas"),
        ],
        string="Tipo Factura VeriFactu",
        default="F1",
        help="Tipo de factura según normativa VeriFactu",
    )

    verifacti_validar_destinatario = fields.Boolean(
        string="Validar Destinatario en AEAT",
        default=False,
        help="Validar que el NIF del destinatario está censado en AEAT",
    )

    verifacti_tipo_rectificativa = fields.Selection(
        [("S", "Sustitución"), ("I", "Diferencia")],
        string="Tipo Rectificativa",
        default="I",
        help="I (Diferencia): Envía solo el ajuste (más común). "
        "S (Sustitución): Reemplaza factura completa. "
        "Se asigna automáticamente según el tipo de factura.",
    )

    verifacti_incidencia = fields.Boolean(
        string="Indicador de Incidencia",
        default=False,
        help="Marcar si ha ocurrido alguna incidencia",
    )

    verifacti_sent_at = fields.Datetime(
        string="Enviado en",
        readonly=True,
        help="Fecha y hora del envío inicial (para calcular delays)",
    )

    verifacti_http_status = fields.Integer(string="HTTP Status", readonly=True)

    verifacti_retry_count = fields.Integer(
        string="Intentos de Reenvío",
        default=0,
        readonly=True,
        help="Número de veces que se ha intentado reenviar esta factura",
    )

    verifacti_check_status_failed = fields.Boolean(
        string="Consulta de Estado Fallida",
        default=False,
        readonly=True,
        help="Marca facturas cuyo UUID no existe en la API (404/400) para no volver a consultar",
    )

    # ============================================
    # COMPATIBILIDAD ENTRE VERSIONES
    # ============================================

    def _get_invoice_type(self):
        """Obtener tipo de factura de forma compatible entre versiones"""
        
        # Lista de tipos VÁLIDOS
        VALID_TYPES = ["out_invoice", "out_refund", "in_invoice", "in_refund"]
        
        # Primero intentar move_type (Odoo 14+)
        move_type = getattr(self, "move_type", None)
        if move_type in VALID_TYPES:
            return move_type
        
        # Luego intentar type (Odoo 13)
        invoice_type = getattr(self, "type", None)
        if invoice_type in VALID_TYPES:
            return invoice_type
        
        # Si no hay tipo válido, inferir del diario
        if hasattr(self, "journal_id") and self.journal_id:
            journal_type = self.journal_id.type
            if journal_type == "sale":
                return "out_invoice"
            elif journal_type == "purchase":
                return "in_invoice"
        
        return None

    # ============================================
    # COMPUTES
    # ============================================

    @api.depends("verifacti_error_message", "verifacti_error_code")
    def _compute_verifacti_error_summary(self):
        """Generar resumen corto del error"""
        for move in self:
            error_msg = move.verifacti_error_message
            move.verifacti_error_summary = (
                error_msg[:80] + ("..." if error_msg and len(error_msg) > 80 else "")
                if error_msg
                else ""
            )

    @api.depends("verifacti_error_message", "verifacti_error_code")
    def _compute_verifacti_error_solution(self):
        """Mostrar solución sugerida basada en el error"""
        for move in self:
            move.verifacti_error_solution = (
                "Revise el mensaje de error de la API para más detalles."
                if move.verifacti_error_message
                else ""
            )

    def _get_verifacti_tipo_sugerido(self):
        """Obtener tipo de factura VeriFactu sugerido

        - Facturas normales (out_invoice) → F1 por defecto (SIEMPRE)
        - Facturas rectificativas (out_refund) → R1 por defecto (SIEMPRE)

        NOTA: El tipo puede cambiarse manualmente después:
        - Rectificativas: R1-R5 disponibles
        - Normales sin sector y bajo umbral: F1-F3 disponibles
        - Normales con sector o sobre umbral: solo F1 permitido
        """
        self.ensure_one()

        try:
            invoice_type = self._get_invoice_type()
            if not invoice_type or invoice_type not in ["out_invoice", "out_refund"]:
                return "F1"

            # Facturas rectificativas → R1 por defecto (siempre)
            if invoice_type == "out_refund":
                return "R1"
            # Facturas normales → F1 por defecto (siempre)
            else:
                return "F1"

        except Exception as e:
            _logger.warning("Error al sugerir tipo factura para ID %s: %s", self.id, e)
            return "F1"

    # ============================================
    # VALIDACIONES
    # ============================================

    def _validate_verifacti_normativa(self):
        """Validar cumplimiento normativo VeriFactu"""
        self.ensure_one()
        errors = []

        try:
            tipo = self.verifacti_tipo_factura
            amount_total = abs(self.amount_total or 0.0)
            invoice_type = self._get_invoice_type()
            limite = (
                3000.0
                if self._get_verifacti_config("sector_especial", False)
                else 400.0
            )

            if not tipo:
                errors.append("El tipo de factura VeriFactu es obligatorio")

            if tipo in ["F2", "R5"] and amount_total > limite:
                errors.append(
                    f"Tipo {tipo} no puede superar {limite:.0f}€. "
                    f"Importe: {amount_total:.2f}€. Use {'F1' if tipo == 'F2' else 'R1'}."
                )

            # Validar que facturas con sector o sobre umbral DEBEN usar F1
            if invoice_type == "out_invoice" and tipo in ["F2", "F3"]:
                tiene_sector = self._get_verifacti_config("sector_especial", False)
                if tiene_sector or amount_total > limite:
                    razon = "tiene sector especial" if tiene_sector else f"supera {limite:.0f}€"
                    errors.append(
                        f"Esta factura {razon}, por lo que DEBE usar tipo F1, no {tipo}"
                    )

            if invoice_type == "out_refund" and tipo not in [
                "R1",
                "R2",
                "R3",
                "R4",
                "R5",
            ]:
                errors.append(f"Nota de crédito debe usar R1-R5, no {tipo}")
            elif invoice_type == "out_invoice" and tipo in [
                "R1",
                "R2",
                "R3",
                "R4",
                "R5",
            ]:
                errors.append(f"Factura normal debe usar F1-F3, no {tipo}")

            if self.state != "posted":
                errors.append("La factura debe estar publicada")

            if not self.invoice_line_ids:
                errors.append("Debe tener al menos una línea")

            if amount_total <= 0:
                errors.append("El importe debe ser mayor a 0")

            # VALIDACIÓN FACTURAS RECTIFICATIVAS
            if tipo in ["R1", "R2", "R3", "R4", "R5"]:
                if not self.verifacti_tipo_rectificativa:
                    errors.append(
                        f"Las facturas rectificativas (tipo {tipo}) requieren seleccionar "
                        "el Tipo Rectificativa: S (Sustitución) o I (Diferencia)"
                    )
                elif self.verifacti_tipo_rectificativa not in ["S", "I"]:
                    errors.append(
                        f"Tipo Rectificativa debe ser 'S' (Sustitución) o 'I' (Diferencia), "
                        f"no '{self.verifacti_tipo_rectificativa}'"
                    )

            if errors:
                raise ValidationError(
                    f"Factura {getattr(self, 'name', self.id)} - Errores:\n• "
                    + "\n• ".join(errors)
                )

            return True

        except ValidationError:
            raise
        except Exception as e:
            _logger.error("Error validando factura ID %s: %s", self.id, e)
            return True

    # ============================================
    # ONCHANGE
    # ============================================

    @api.model_create_multi
    def create(self, vals_list):
        """Override create para asignar tipo VeriFactu automáticamente

        OPTIMIZACIÓN: Actualiza múltiples facturas en un solo write() batch
        para evitar bloqueos con grandes volúmenes.
        """
        records = super(AccountMove, self).create(vals_list)

        if not records:
            return records

        # Identificar facturas con tipo manual (viene explícito en vals_list)
        manual_ids = set()
        for vals in vals_list:
            if vals.get("verifacti_tipo_factura"):
                # Buscar el ID del record creado
                matching = records.filtered(
                    lambda r: r.name == vals.get("name")
                    or (not vals.get("name") and r.id)
                )
                if matching:
                    manual_ids.add(matching[0].id)

        # Agrupar facturas por tipo sugerido para write masivo
        updates_by_tipo = {}  # {tipo_sugerido: recordset}

        for record in records:
            # Skip si no es factura de cliente o tiene tipo manual
            invoice_type = record._get_invoice_type()
            if invoice_type not in ["out_invoice", "out_refund"]:
                continue
            if record.id in manual_ids:
                continue
            if record.verifacti_tipo_factura != "F1":
                continue

            # NUEVA LÓGICA:
            # - Rectificativas: R1 por defecto (SIEMPRE)
            # - Normales: F1 por defecto (SIEMPRE)
            if invoice_type == "out_refund":
                tipo_sugerido = "R1"
            else:
                tipo_sugerido = "F1"

            # Solo actualizar si cambió
            if tipo_sugerido != record.verifacti_tipo_factura:
                if tipo_sugerido not in updates_by_tipo:
                    updates_by_tipo[tipo_sugerido] = self.env["account.move"]
                updates_by_tipo[tipo_sugerido] |= record

        # Ejecutar writes en batch (1 write por cada tipo único)
        for tipo_sugerido, recordset in updates_by_tipo.items():
            try:
                recordset.write({"verifacti_tipo_factura": tipo_sugerido})
                _logger.debug(
                    "Asignado tipo %s a %s facturas en batch",
                    tipo_sugerido,
                    len(recordset),
                )
            except Exception as e:
                _logger.warning(
                    "Error asignando tipo %s a batch de %s facturas: %s",
                    tipo_sugerido,
                    len(recordset),
                    e,
                )

        return records

    @api.onchange(
        "amount_total", "invoice_line_ids", "verifacti_tipo_factura", "move_type"
    )
    def _onchange_suggest_verifacti_tipo_factura(self):
        """Asignar automáticamente tipo de factura según out_invoice/out_refund

        NUEVA LÓGICA:
        - Rectificativas: R1 por defecto, R1-R5 disponibles
        - Normales: F1 por defecto
          - Si hay sector O supera umbral: SOLO F1 (forzar)
          - Si NO hay sector Y NO supera umbral: F1-F3 disponibles
        """
        try:
            invoice_type = self._get_invoice_type()
            if invoice_type not in ["out_invoice", "out_refund"]:
                return

            amount_total = abs(self.amount_total or 0.0)
            tipo = self.verifacti_tipo_factura
            tiene_sector = self._get_verifacti_config("sector_especial", False)
            limite = 3000.0 if tiene_sector else 400.0
            supera_umbral = amount_total > limite

            tipo_correcto = None
            mensaje = None

            # CORRECCIÓN 1: Factura normal con tipo rectificativo → Cambiar a F1
            if invoice_type == "out_invoice" and tipo in ["R1", "R2", "R3", "R4", "R5"]:
                tipo_correcto = "F1"
                mensaje = "⚠️ Las facturas normales deben usar tipos F1-F3. Cambiado automáticamente a F1."

            # CORRECCIÓN 2: Factura rectificativa con tipo normal → Cambiar a R1
            elif invoice_type == "out_refund" and tipo in ["F1", "F2", "F3"]:
                tipo_correcto = "R1"
                mensaje = "⚠️ Las facturas rectificativas deben usar tipos R1-R5. Cambiado automáticamente a R1."

            # NUEVA CORRECCIÓN 3: Factura normal con sector O sobre umbral → DEBE ser F1
            elif invoice_type == "out_invoice" and tipo in ["F2", "F3"]:
                if tiene_sector or supera_umbral:
                    tipo_correcto = "F1"
                    razon = "tiene sector especial" if tiene_sector else f"supera el umbral de {limite:.0f}€"
                    mensaje = f"⚠️ Esta factura {razon}, por lo que DEBE ser tipo F1. Cambiado automáticamente."

            # CORRECCIÓN 4: R5 supera límite → Cambiar a R1
            elif tipo == "R5" and supera_umbral:
                tipo_correcto = "R1"
                mensaje = f"⚠️ Tipo R5 no permitido para importes > {limite:.0f}€. Cambiado automáticamente a R1."

            # ASIGNACIÓN INICIAL: Si no tiene tipo, asignar el sugerido
            elif not tipo:
                tipo_correcto = self._get_verifacti_tipo_sugerido()

            # Aplicar corrección si es necesario
            if tipo_correcto and tipo_correcto != tipo:
                self.verifacti_tipo_factura = tipo_correcto

                if mensaje:
                    return {
                        "warning": {
                            "title": "Tipo de Factura Corregido",
                            "message": mensaje,
                        }
                    }

        except Exception as e:
            _logger.debug("Error en onchange tipo factura ID %s: %s", self.id, e)

    # ============================================
    # ACCIONES
    # ============================================

    def action_send_to_verifacti(self):
        """Enviar factura a Verifacti API con mejor manejo de errores"""
        self.ensure_one()

        # Validaciones básicas
        invoice_type = self._get_invoice_type()
        
        if invoice_type not in ["out_invoice", "out_refund"]:
            # Obtener información adicional para el mensaje
            move_type = getattr(self, "move_type", None)
            type_field = getattr(self, "type", None)
            journal_name = self.journal_id.name if hasattr(self, "journal_id") and self.journal_id else "Sin diario"
            journal_type = self.journal_id.type if hasattr(self, "journal_id") and self.journal_id else "N/A"
            
            raise UserError(_(
                "❌ Solo se pueden enviar facturas de cliente a Verifacti\n\n"
                "Factura: %s\n"
                "Tipo detectado: %s\n"
                "Diario: %s (tipo: %s)\n\n"
                "ℹ️ Información técnica:\n"
                "• move_type: %s\n"
                "• type: %s\n\n"
                "✅ Tipos válidos para Verifacti:\n"
                "• out_invoice → Factura de cliente\n"
                "• out_refund → Nota de crédito de cliente\n\n"
                "💡 Posibles soluciones:\n"
                "• Si es factura de cliente: Revise que el diario sea de tipo 'Ventas'\n"
                "• Si es factura de proveedor: No se puede enviar a Verifacti\n"
                "• Si es asiento contable: Use una factura en lugar de un asiento manual\n\n"
                "Si el problema persiste, contacte con soporte técnico."
            ) % (
                self.name,
                invoice_type or "No detectado",
                journal_name,
                journal_type,
                move_type or "vacío",
                type_field or "vacío"
            ))
           
        if self.state != "posted":
            raise UserError(_("Solo se pueden enviar facturas publicadas"))

        # VALIDACIÓN CORRECTA: Solo draft o error se pueden enviar
        if self.verifacti_state not in ["draft", "error"]:
            raise UserError(
                _(
                    "Esta factura ya fue enviada a Verifacti (estado: %s).\n\n"
                    "❌ No se puede reenviar una factura ya procesada.\n\n"
                    "Si necesita corregirla:\n"
                    "• Cree una factura rectificativa (Botón 'Agregar nota de crédito')\n"
                    "• O contacte con soporte si fue un error del sistema"
                ) % self.verifacti_state
            )

        # Para rectificativas: validar que la ORIGINAL esté enviada
        if self.reversed_entry_id:
            if self.reversed_entry_id.verifacti_state != "correct":
                raise UserError(
                    _(
                        "⚠️ La factura original debe estar enviada a Verifacti primero.\n\n"
                        "Factura original: %s\n"
                        "Estado actual: %s\n\n"
                        "Envíe primero la factura original y luego la rectificativa."
                    ) % (
                        self.reversed_entry_id.name,
                        self.reversed_entry_id.verifacti_state or 'Sin enviar'
                    )
                )
            
            _logger.info(
                "Enviando factura rectificativa %s que rectifica %s (UUID: %s)",
                self.name,
                self.reversed_entry_id.name,
                self.reversed_entry_id.verifacti_uuid
            )

        # Si está en error, limpiar automáticamente antes de reenviar
        if self.verifacti_state == "error":
            self.write({
                "verifacti_retry_count": 0,
                "verifacti_error_message": False,
                "verifacti_error_code": False,
                "verifacti_http_status": False,
                "verifacti_check_status_failed": False,
            })
            _logger.info(
                "Factura ID %s (%s) en estado error - Limpiando errores antes de reenviar",
                self.id,
                self.name,
            )

        # Validaciones de normativa
        self._validate_verifacti_normativa()

        api_client = self.env["verifacti.api.client"]

        try:
            invoice_data = self._prepare_verifacti_invoice_data()

            # Log de datos enviados (para debugging)
            _logger.debug(
                "Enviando factura %s (ID: %s) a VeriFactu:\n%s",
                self.name,
                self.id,
                json.dumps(invoice_data, indent=2, ensure_ascii=False),
            )

            response = api_client.with_context(
                verifacti_company_id=self.company_id.id
            ).create_invoice(invoice_data)

            self._process_verifacti_response(response)

            # Mensaje de éxito
            url_link = (
                f'<br/>🔗 <a href="{response.get("url")}" target="_blank">Verificar</a>'
                if response.get("url")
                else ""
            )

            qr_status = (
                "<br/>✅ Código QR generado y disponible"
                if response.get("qr")
                else "<br/>⏳ Código QR pendiente"
            )

            self.message_post(
                body=_(
                    "<strong>✅ Enviada a Verifacti</strong><br/>UUID: %s | Estado: %s%s%s"
                ) % (
                    response.get("uuid", "N/A"),
                    response.get("estado", "Pendiente"),
                    url_link,
                    qr_status,
                ),
                message_type="notification",
            )

            return True

        except Exception as e:
            error_msg = str(e)

            # Guardar error en la factura
            self.write({
                "verifacti_state": "error",
                "verifacti_error_message": error_msg
            })

            # Log detallado
            _logger.error(
                "Error enviando factura a VeriFactu\n"
                "ID: %s | Nombre: %s\n"
                "Error: %s\n"
                "Datos enviados: %s",
                self.id,
                self.name or "Sin número",
                error_msg,
                (
                    json.dumps(invoice_data, indent=2, ensure_ascii=False)
                    if "invoice_data" in locals()
                    else "N/A"
                ),
            )

            # Mensaje al usuario con información útil
            raise UserError(
                _(
                    "❌ Error al enviar factura a VeriFactu\n\n"
                    "Factura: %s\n"
                    "Error: %s\n\n"
                    "💡 Revise:\n"
                    "• Datos del cliente (NIF, nombre)\n"
                    "• Tipo de factura (F1, F2, R1...)\n"
                    "• Líneas de factura (impuestos, importes)\n"
                    "• Pestaña VeriFactu → Respuesta API para más detalles"
                ) % (self.name or f"ID {self.id}", error_msg)
            )

    def action_check_verifacti_status(self):
        """Verificar estado del registro de facturación"""
        if len(self) == 1 and not self.verifacti_uuid:
            raise UserError(_("No hay un UUID asociado a esta factura"))

        max_limit = self[0]._get_verifacti_config("max_bulk_limit", 10)
        invoices_to_check = self[:max_limit] if len(self) > max_limit else self
        limited = len(self) > max_limit

        api_client = self.env["verifacti.api.client"]
        success_count = 0
        error_count = 0

        for invoice in invoices_to_check:
            if not invoice.verifacti_uuid:
                error_count += 1
                continue

            try:
                response = api_client.with_context(
                    verifacti_company_id=invoice.company_id.id
                ).get_registration_status(invoice.verifacti_uuid)
                invoice._process_registration_status(response)
                success_count += 1
            except Exception as e:
                _logger.error(
                    "Error verificando estado UUID %s: %s", invoice.verifacti_uuid, e
                )
                invoice.message_post(body=_("Error al verificar estado: %s") % str(e))
                error_count += 1

        message = _("Verificadas: %s | Errores: %s") % (success_count, error_count)
        if limited:
            message = _("⚠️ Limitado a %s facturas (se seleccionaron %s)\n%s") % (
                max_limit,
                len(self),
                message,
            )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Verificación Completada"),
                "message": message,
                "type": "warning" if limited or error_count > 0 else "success",
                "sticky": limited,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def action_download_verifacti_xmls(self):
        """Descargar XMLs de la factura"""
        self.ensure_one()

        if not self.name:
            raise UserError(_("La factura debe tener un número"))

        try:
            serie, numero = self._parse_invoice_number()

            response = (
                self.env["verifacti.api.client"]
                .with_context(verifacti_company_id=self.company_id.id)
                .download_xml(serie, numero)
            )

            if not response:
                raise UserError(_("No se recibió respuesta de la API"))

            xml_data = response[0] if isinstance(response, list) else response
            xml_peticion = xml_data.get("xml_req", "")
            xml_respuesta = xml_data.get("xml_res", "")

            if not xml_peticion and not xml_respuesta:
                raise UserError(_("No se recibieron XMLs en la respuesta"))

            self.write(
                {
                    "verifacti_xml_request": xml_peticion,
                    "verifacti_xml_response": xml_respuesta,
                }
            )

            import base64
            import zipfile
            from io import BytesIO

            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                safe_name = f"{serie}_{numero}".replace("/", "_")

                if xml_peticion:
                    zip_file.writestr(f"{safe_name}_peticion.xml", xml_peticion)
                if xml_respuesta:
                    zip_file.writestr(f"{safe_name}_respuesta.xml", xml_respuesta)

            zip_buffer.seek(0)
            zip_content = base64.b64encode(zip_buffer.read())

            attachment = self.env["ir.attachment"].create(
                {
                    "name": f"VeriFactu_{serie}_{numero}.zip".replace("/", "_"),
                    "type": "binary",
                    "datas": zip_content,
                    "res_model": self._name,
                    "res_id": self.id,
                    "mimetype": "application/zip",
                }
            )

            return {
                "type": "ir.actions.act_url",
                "url": f"/web/content/{attachment.id}?download=true",
                "target": "self",
            }

        except UserError:
            raise
        except Exception as e:
            _logger.error("Error descargando XMLs para factura ID %s: %s", self.id, e)
            raise UserError(_("Error al descargar XMLs: %s") % str(e))

    def action_cancel_verifacti(self):
        """Anular factura en Verifacti"""
        self.ensure_one()

        if self.verifacti_state == "cancelled":
            raise UserError(_("La factura ya está anulada en VeriFactu"))

        try:
            serie, numero = self._parse_invoice_number()
            api_client = self.env["verifacti.api.client"]
            fecha_exp = api_client.format_date(self.invoice_date)

            response = api_client.with_context(
                verifacti_company_id=self.company_id.id
            ).cancel_invoice(
                serie,
                numero,
                fecha_exp,
                rechazo_previo="N",
                sin_registro_previo="N",
                incidencia="S" if self.verifacti_incidencia else None,
            )

            self.write(
                {
                    "verifacti_state": "cancelled",
                    "verifacti_api_response": str(response),
                }
            )

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Factura Anulada"),
                    "message": _(
                        "La factura ha sido anulada correctamente en VeriFactu"
                    ),
                    "type": "success",
                    "sticky": False,
                },
            }
        except Exception as e:
            _logger.error("Error anulando factura ID %s: %s", self.id, e)
            raise UserError(_("Error al anular factura: %s") % str(e))

    def action_bulk_send_to_verifacti(self):
        """Enviar múltiples facturas a Verifacti API"""
        if not self:
            raise UserError(_("No hay facturas seleccionadas"))

        invoices_to_send = self.filtered(
            lambda inv: inv.state == "posted"
            and inv.verifacti_state in ["draft", "error"]
        )

        if not invoices_to_send:
            raise UserError(_("Ninguna de las facturas seleccionadas puede enviarse"))

        # Obtener límite desde ir.config_parameter
        max_limit = int(
            invoices_to_send[0]._get_verifacti_config("max_bulk_limit", 10)
        )
        original_count = len(invoices_to_send)

        if len(invoices_to_send) > max_limit:
            invoices_to_send = invoices_to_send[:max_limit]
            limited = True
        else:
            limited = False

        success_count = 0
        error_count = 0

        for invoice in invoices_to_send:
            try:
                invoice.action_send_to_verifacti()
                success_count += 1
            except Exception as e:
                _logger.error("Error enviando factura ID %s: %s", invoice.id, e)
                invoice.write(
                    {"verifacti_state": "error", "verifacti_error_message": str(e)}
                )
                error_count += 1

        message = _("Enviadas: %s | Errores: %s") % (success_count, error_count)
        if limited:
            message = _("⚠️ Limitado a %s facturas (se seleccionaron %s)\n%s") % (
                max_limit,
                original_count,
                message,
            )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Envío Masivo Completado"),
                "message": message,
                "type": "warning" if limited or error_count > 0 else "success",
                "sticky": True,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    # ============================================
    # MÉTODOS PRIVADOS
    # ============================================

    def _parse_invoice_number(self):
        """Parsear número de factura para obtener serie y número"""
        self.ensure_one()

        if not self.name:
            return ("", "")

        parts = self.name.rsplit("/", 1)
        if len(parts) == 2:
            return (parts[0], parts[1])
        else:
            return ("", self.name)

    def _get_verifacti_descripcion(self):
        """Generar descripción automática para VeriFactu"""
        self.ensure_one()

        if not self.invoice_line_ids:
            return self.narration or "Factura"

        descriptions = [
            line.name
            for line in self.invoice_line_ids
            if line.display_type not in ("line_section", "line_note") and line.name
        ]

        if not descriptions:
            return self.narration or "Factura"

        desc = ", ".join(descriptions[:3])
        if len(descriptions) > 3:
            desc += f" (+{len(descriptions) - 3} más)"

        return (desc[:497] + "..." if len(desc) > 500 else desc) or "Factura"

    def _add_customer_data(self, invoice_data):
        """Añadir datos del cliente a la factura según normativa VeriFactu

        DEPRECADO: Este método se mantiene por compatibilidad pero ahora
        delega al CustomerProcessor. Se recomienda usar directamente
        verifacti.customer.processor.process_customer_for_invoice()

        El procesamiento ahora se hace en prepare_invoice_for_api()
        """
        self.ensure_one()

        # Delegar al servicio especializado para mantener compatibilidad
        customer_processor = self.env['verifacti.customer.processor']
        customer_data = customer_processor.process_customer_for_invoice(self)

        # Actualizar el diccionario pasado por referencia
        invoice_data.update(customer_data)

    def _prepare_verifacti_invoice_data(self):
        """Preparar estructura de datos para Verifacti API

        REFACTORIZADO: Ahora usa VerifactiInvoiceService
        """
        self.ensure_one()

        # Delegar a servicio especializado
        invoice_service = self.env['verifacti.invoice.service']
        return invoice_service.prepare_invoice_for_api(self)

    def _prepare_invoice_lines(self, api_client):
        """Preparar líneas de factura con normalización de impuestos"""
        lineas = []
        ajustes_realizados = []

        for line in self.invoice_line_ids:
            if line.display_type in ("line_section", "line_note"):
                continue

            base_imponible = line.price_subtotal
            tipo_impositivo_original = None
            cuota_repercutida_original = 0.0
            codigo_impuesto = "01"

            for tax in line.tax_ids:
                if tax.amount > 0:
                    tipo_impositivo_original = tax.amount
                    cuota_repercutida_original = line.price_total - line.price_subtotal
                    codigo_impuesto = self._detect_tax_code(tax)
                    break

            line_data = {
                "base_imponible": str(round(base_imponible, 2)),
                "impuesto": codigo_impuesto,
            }

            if tipo_impositivo_original is not None:
                tipo_normalizado = api_client.normalize_tipo_impositivo(
                    tipo_impositivo_original
                )

                if tipo_normalizado is not None:
                    line_data["tipo_impositivo"] = str(tipo_normalizado)

                    if (
                        float_compare(
                            tipo_impositivo_original,
                            tipo_normalizado,
                            precision_digits=2,
                        )
                        != 0
                    ):
                        cuota_recalculada = round(
                            base_imponible * tipo_normalizado / 100, 2
                        )
                        line_data["cuota_repercutida"] = str(cuota_recalculada)

                        ajustes_realizados.append(
                            {
                                "linea": line.name[:50],
                                "base": base_imponible,
                                "tipo_original": tipo_impositivo_original,
                                "tipo_normalizado": tipo_normalizado,
                                "cuota_original": cuota_repercutida_original,
                                "cuota_recalculada": cuota_recalculada,
                                "diferencia": cuota_recalculada
                                - cuota_repercutida_original,
                            }
                        )
                    else:
                        line_data["cuota_repercutida"] = str(
                            round(cuota_repercutida_original, 2)
                        )

            if "tipo_impositivo" not in line_data:
                line_data["tipo_impositivo"] = "0.00"
            if "cuota_repercutida" not in line_data:
                line_data["cuota_repercutida"] = "0.00"

            lineas.append(line_data)

        return lineas, ajustes_realizados

    def _group_lines_by_tax(self, lineas):
        """Agrupar líneas por tipo de impuesto cuando hay más de 12 líneas"""
        from collections import defaultdict

        grupos = defaultdict(lambda: {"base_imponible": 0.0, "cuota_repercutida": 0.0})

        for linea in lineas:
            key = (linea["impuesto"], linea.get("tipo_impositivo", "0.00"))
            grupos[key]["base_imponible"] += float(linea["base_imponible"])
            grupos[key]["cuota_repercutida"] += float(
                linea.get("cuota_repercutida", "0.00")
            )

        lineas_agrupadas = []
        for (codigo_impuesto, tipo_impositivo), valores in grupos.items():
            linea_agrupada = {
                "base_imponible": str(round(valores["base_imponible"], 2)),
                "impuesto": codigo_impuesto,
                "tipo_impositivo": tipo_impositivo,
                "cuota_repercutida": str(round(valores["cuota_repercutida"], 2)),
            }
            lineas_agrupadas.append(linea_agrupada)

        return lineas_agrupadas

    def _detect_tax_code(self, tax):
        """Detectar código de impuesto según el tax_scope del impuesto

        Prioriza el campo tax_scope si existe (método estándar de Odoo para l10n_es).
        Si no existe, usa detección por nombre como fallback.

        Códigos VeriFactu:
        - 01: IVA (Península y Baleares)
        - 02: IPSI (Ceuta y Melilla)
        - 03: IGIC (Canarias)
        """
        # Método 1: Usar tax_scope si existe (estándar Odoo l10n_es)
        if hasattr(tax, "tax_scope"):
            tax_scope = tax.tax_scope
            if tax_scope == "consu":  # Impuesto de Consumo (IPSI)
                return "02"
            elif tax_scope == "igic":  # IGIC
                return "03"
            elif tax_scope in ["vat", "service"]:  # IVA
                return "01"

        # Método 2: Fallback por nombre (menos confiable pero compatible)
        tax_name_upper = (tax.name or "").upper()

        if "IPSI" in tax_name_upper:
            return "02"
        elif "IGIC" in tax_name_upper:
            return "03"

        # Por defecto: IVA
        return "01"

    def _calculate_total_with_adjustments(self, lineas, ajustes_realizados):
        """Calcular importe total ajustado y registrar ajustes"""
        importe_total_calculado = sum(
            float(linea["base_imponible"]) + float(linea.get("cuota_repercutida", 0))
            for linea in lineas
        )
        importe_total_calculado = round(importe_total_calculado, 2)
        importe_total_original = round(self.amount_total, 2)

        diferencia_total = abs(importe_total_calculado - importe_total_original)

        if diferencia_total > 0.10:
            _logger.warning(
                "Factura ID %s (%s): Importe ajustado de %.2f€ a %.2f€ (diferencia: %.2f€)",
                self.id,
                self.name,
                importe_total_original,
                importe_total_calculado,
                diferencia_total,
            )
            importe_total_enviar = importe_total_calculado
        else:
            importe_total_enviar = importe_total_original

        if ajustes_realizados:
            mensaje = _("⚠️ Ajustes en tipos impositivos:\n\n")
            for ajuste in ajustes_realizados:
                mensaje += _(
                    "• Línea: %s | Base: %.2f€ | Tipo: %.2f%% → %.2f%% | "
                    "Cuota: %.2f€ → %.2f€ (dif: %.2f€)\n"
                ) % (
                    ajuste["linea"],
                    ajuste["base"],
                    ajuste["tipo_original"],
                    ajuste["tipo_normalizado"],
                    ajuste["cuota_original"],
                    ajuste["cuota_recalculada"],
                    ajuste["diferencia"],
                )

            mensaje += _("\nImporte total: %.2f€ → %.2f€") % (
                importe_total_original,
                importe_total_enviar,
            )
            self.message_post(body=mensaje, subject=_("Ajustes VeriFactu"))

        return importe_total_enviar

    def _process_verifacti_response(self, response):
        """Procesar respuesta de creación de factura"""
        self.ensure_one()

        # Validar si es string (error directo)
        if isinstance(response, str):
            vals = {
                "verifacti_state": "error",
                "verifacti_error_message": response,
                "verifacti_sent_at": fields.Datetime.now(),
            }
            self.write(vals)
            return

        if not response:
            raise UserError(_("No se recibió respuesta de la API"))

        status_code = response.get("status_code", 200)

        # Errores 4xx: NO reintentar nunca (error de cliente)
        if 400 <= status_code < 500:
            # MEJORADO: Extraer mensaje detallado de la API
            error_message = self._extract_detailed_error_message(response)

            vals = {
                "verifacti_http_status": status_code,
                "verifacti_state": "error",
                "verifacti_error_message": error_message,
                "verifacti_error_code": str(status_code),
                "verifacti_sent_at": fields.Datetime.now(),
                "verifacti_retry_count": 999,  # Nunca reintentar
                "verifacti_api_response": str(response),  # Guardar respuesta completa
            }
            self.write(vals)

            # Log detallado para debugging
            _logger.error(
                "Error HTTP %s en factura %s (ID: %s)\n"
                "Mensaje API: %s\n"
                "Respuesta completa: %s",
                status_code,
                self.name,
                self.id,
                error_message,
                response,
            )
            return

        # Errores 5xx: Permitir reintentos (error de servidor)
        if status_code >= 500:
            error_message = (
                response.get("mensaje") or response.get("error") or "Error del servidor"
            )

            vals = {
                "verifacti_http_status": status_code,
                "verifacti_state": "error",
                "verifacti_error_message": error_message,
                "verifacti_error_code": str(status_code),
                "verifacti_sent_at": fields.Datetime.now(),
                "verifacti_api_response": str(response),
            }
            self.write(vals)
            return

        # Éxito (2xx)
        vals = {
            "verifacti_uuid": response.get("uuid"),
            "verifacti_registration_status": response.get("estado", "Pendiente"),
            "verifacti_url": response.get("url"),
            "verifacti_huella": response.get("huella"),
            "verifacti_api_response": str(response),
            "verifacti_state": "pending",
            "verifacti_sent_at": fields.Datetime.now(),
            "verifacti_http_status": status_code,
        }

        # Guardar QR si viene en la respuesta
        if response.get("qr"):
            vals["verifacti_qr"] = response.get("qr")
            _logger.info(
                "QR guardado para factura %s (UUID: %s)",
                self.name,
                response.get("uuid"),
            )

        self.write(vals)

    def _extract_detailed_error_message(self, response):
        """Extraer mensaje de error detallado de la respuesta de la API

        La API puede devolver errores en diferentes formatos:
        - {"mensaje": "...", "detalles": {...}}
        - {"error": "...", "errores": [...]}
        - {"mensaje": "...", "campo": "valor"}
        """

        # Intentar extraer el mensaje principal
        error_msg = (
            response.get("mensaje") or response.get("error") or "Error en petición"
        )

        # Añadir detalles adicionales si existen
        additional_info = []

        # Detalles específicos de campos
        if "detalles" in response and isinstance(response["detalles"], dict):
            for campo, detalle in response["detalles"].items():
                additional_info.append(f"• {campo}: {detalle}")

        # Lista de errores
        if "errores" in response and isinstance(response["errores"], list):
            for error in response["errores"]:
                if isinstance(error, dict):
                    campo = error.get("campo", "")
                    mensaje = error.get("mensaje", str(error))
                    additional_info.append(
                        f"• {campo}: {mensaje}" if campo else f"• {mensaje}"
                    )
                else:
                    additional_info.append(f"• {error}")

        # Campos específicos que suelen causar problemas
        problematic_fields = [
            "nif",
            "nombre",
            "tipo_factura",
            "lineas",
            "importe_total",
        ]
        for field in problematic_fields:
            if field in response and field not in ["mensaje", "error"]:
                additional_info.append(f"• {field}: {response[field]}")

        # Construir mensaje final
        if additional_info:
            full_message = f"{error_msg}\n\nDetalles:\n" + "\n".join(additional_info)
        else:
            full_message = error_msg

        return full_message

    # ============================================
    # CRON JOBS
    # ============================================

    @api.model
    def cron_send_pending_invoices_to_verifacti(self):
        """Cron para enviar automáticamente facturas pendientes a VeriFactu

        LÍMITES DE SEGURIDAD:
        - Usa 'verifacti_max_bulk_limit' de la compañía (default: 10 facturas/minuto)
        - Límite horario: verifacti_max_bulk_limit × 60 (ej: 10×60 = 600/hora)
        - Envío individual (no lotes) para mejor trazabilidad
        - No reintenta errores 4xx (errores de cliente)
        - Reintenta errores 5xx máximo 3 veces con 15 min entre intentos
        """
        from datetime import timedelta

        IrConfigParameter = self.env['ir.config_parameter'].sudo()

        # Obtener todas las compañías y filtrar las que tienen auto_send habilitado
        all_companies = self.env["res.company"].search([])
        companies_with_auto_send = all_companies.filtered(
            lambda c: (
                IrConfigParameter.get_param(f"verifacti_api.company_{c.id}.api_key", default="") and
                IrConfigParameter.get_param(f"verifacti_api.company_{c.id}.auto_send_enabled", default="False") == "True"
            )
        )

        if not companies_with_auto_send:
            return  # Salir sin log si no hay compañías configuradas

        api_client = self.env["verifacti.api.client"]
        total_sent = 0
        total_errors = 0
        total_skipped = 0
        skipped_companies = []
        error_details = []

        for company in companies_with_auto_send:
            # Límites configurables por compañía
            MAX_PER_EXECUTION = int(IrConfigParameter.get_param(f"verifacti_api.company_{company.id}.max_bulk_limit", default="10"))
            MAX_PER_HOUR = MAX_PER_EXECUTION * 60  # 10/min = 600/hora (ajustable)
            # ============================================
            # 1. VERIFICAR CARGA DEL SISTEMA
            # ============================================
            load_status = self._check_system_load_status(company)

            if not load_status["can_process"]:
                was_paused = IrConfigParameter.get_param(f"verifacti_api.company_{company.id}.auto_send_paused", default="False") == "True"

                # Guardar estado de pausa en ir.config_parameter
                IrConfigParameter.set_param(f"verifacti_api.company_{company.id}.auto_send_paused", "True")
                IrConfigParameter.set_param(f"verifacti_api.company_{company.id}.auto_send_paused_reason", load_status["reason"])

                if not was_paused:
                    IrConfigParameter.set_param(
                        f"verifacti_api.company_{company.id}.auto_send_paused_since",
                        str(fields.Datetime.now())
                    )

                skipped_companies.append(
                    {
                        "company": company.name,
                        "reason": load_status["reason"],
                        "was_paused": was_paused,
                    }
                )

                if not was_paused:
                    _logger.info(
                        "Envío automático pausado para %s: %s",
                        company.name,
                        load_status["reason"],
                    )
                continue

            # Si estaba pausado y ahora puede procesar, reanudar
            if IrConfigParameter.get_param(f"verifacti_api.company_{company.id}.auto_send_paused", default="False") == "True":
                paused_since_str = IrConfigParameter.get_param(
                    f"verifacti_api.company_{company.id}.auto_send_paused_since",
                    default=""
                )

                pause_minutes = 0
                if paused_since_str:
                    paused_since = fields.Datetime.from_string(paused_since_str)
                    pause_duration = fields.Datetime.now() - paused_since
                    pause_minutes = int(pause_duration.total_seconds() / 60)

                # Limpiar estado de pausa en ir.config_parameter
                IrConfigParameter.set_param(f"verifacti_api.company_{company.id}.auto_send_paused", "False")
                IrConfigParameter.set_param(f"verifacti_api.company_{company.id}.auto_send_paused_reason", "")
                IrConfigParameter.set_param(f"verifacti_api.company_{company.id}.auto_send_paused_since", "")

                _logger.info(
                    "Envío automático reanudado para %s después de %s minutos",
                    company.name,
                    pause_minutes,
                )

            # ============================================
            # 2. VERIFICAR LÍMITE HORARIO (100/hora)
            # ============================================
            now = fields.Datetime.now()
            one_hour_ago = now - timedelta(hours=1)

            sent_last_hour = self.search_count(
                [
                    ("company_id", "=", company.id),
                    ("verifacti_sent_at", ">=", one_hour_ago),
                    ("verifacti_sent_at", "<=", now),
                ]
            )

            if sent_last_hour >= MAX_PER_HOUR:
                remaining_minutes = 60 - int((now - one_hour_ago).total_seconds() / 60)
                skipped_companies.append(
                    {
                        "company": company.name,
                        "reason": f"Límite horario alcanzado ({sent_last_hour}/{MAX_PER_HOUR}). "
                        f"Reintentar en {remaining_minutes} min",
                        "was_paused": False,
                    }
                )
                _logger.info(
                    "Límite horario alcanzado para %s: %s/%s facturas enviadas. "
                    "Próxima ventana en %s min",
                    company.name,
                    sent_last_hour,
                    MAX_PER_HOUR,
                    remaining_minutes,
                )
                continue

            # Calcular cuántas facturas puede enviar en esta ejecución
            remaining_quota = MAX_PER_HOUR - sent_last_hour
            limit_this_execution = min(MAX_PER_EXECUTION, remaining_quota)

            # ============================================
            # 3. BUSCAR FACTURAS PENDIENTES
            # ============================================
            retry_threshold = now - timedelta(minutes=15)

            domain = [
                ("state", "=", "posted"),
                ("move_type", "in", ["out_invoice", "out_refund"]),
                ("company_id", "=", company.id),
                "|",
                ("verifacti_state", "=", "draft"),
                "&",
                "&",
                "&",
                "&",
                ("verifacti_state", "=", "error"),
                ("verifacti_http_status", ">=", 500),
                ("verifacti_http_status", "<", 600),
                ("verifacti_retry_count", "<", 3),
                ("verifacti_sent_at", "<=", retry_threshold),
            ]

            if IrConfigParameter.get_param(f"verifacti_api.company_{company.id}.min_invoice_date", default="2025-01-01"):
                domain.append(
                    ("invoice_date", ">=", IrConfigParameter.get_param(f"verifacti_api.company_{company.id}.min_invoice_date", default="2025-01-01"))
                )

            # Buscar solo las facturas que vamos a procesar
            company_invoices = self.search(
                domain,
                limit=limit_this_execution,
                order="invoice_date asc, id asc",  # Más antiguas primero
            )

            if not company_invoices:
                continue  # No hay facturas pendientes para esta compañía

            # ============================================
            # 4. ENVIAR FACTURAS INDIVIDUALMENTE
            # ============================================
            sent_count = 0
            error_count = 0

            _logger.info(
                "Procesando %s facturas para %s (cuota restante: %s/%s, límite config: %s/min)",
                len(company_invoices),
                company.name,
                remaining_quota,
                MAX_PER_HOUR,
                MAX_PER_EXECUTION,
            )

            for invoice in company_invoices:
                try:
                    with self.env.cr.savepoint():
                        # Preparar datos
                        invoice_data = invoice._prepare_verifacti_invoice_data()

                        # Enviar individualmente
                        response = api_client.with_context(
                            verifacti_company_id=company.id
                        ).create_invoice(invoice_data)

                        # Procesar respuesta
                        invoice._process_verifacti_response(response)

                        # Incrementar contador de reintentos si era un reintento
                        if invoice.verifacti_retry_count > 0:
                            invoice.write(
                                {
                                    "verifacti_retry_count": invoice.verifacti_retry_count
                                    + 1
                                }
                            )

                        sent_count += 1

                        _logger.debug(
                            "✅ Factura %s enviada correctamente (UUID: %s)",
                            invoice.name,
                            response.get("uuid", "N/A"),
                        )

                except Exception as e:
                    error_count += 1
                    error_msg = str(e)

                    # Determinar si es reintentable
                    is_retryable = "5" in error_msg or "timeout" in error_msg.lower()
                    retry_count = (
                        invoice.verifacti_retry_count + 1 if is_retryable else 999
                    )

                    invoice.write(
                        {
                            "verifacti_state": "error",
                            "verifacti_error_message": error_msg,
                            "verifacti_retry_count": retry_count,
                            "verifacti_sent_at": fields.Datetime.now(),
                        }
                    )

                    error_details.append(
                        {
                            "invoice": invoice.name or f"ID {invoice.id}",
                            "company": company.name,
                            "error": error_msg[:200],
                            "retryable": is_retryable,
                        }
                    )

                    _logger.error(
                        "❌ Error enviando factura %s (ID: %s): %s",
                        invoice.name,
                        invoice.id,
                        error_msg,
                    )

            total_sent += sent_count
            total_errors += error_count

            # Log resumen por compañía
            if sent_count > 0 or error_count > 0:
                _logger.info(
                    "Compañía %s: Enviadas=%s, Errores=%s, Cuota usada=%s/%s",
                    company.name,
                    sent_count,
                    error_count,
                    sent_last_hour + sent_count,
                    MAX_PER_HOUR,
                )

        # ============================================
        # 5. LOG RESUMEN GLOBAL
        # ============================================
        if total_sent > 0 or total_errors > 0 or skipped_companies:
            summary = f"✅ Enviadas: {total_sent} | ❌ Errores: {total_errors}"

            # Detalles de errores
            if error_details:
                summary += f"\n\n❌ ERRORES ({len(error_details)}):"
                retryable = [e for e in error_details if e.get("retryable")]
                permanent = [e for e in error_details if not e.get("retryable")]

                if retryable:
                    summary += f"\n  Reintentables: {len(retryable)}"
                if permanent:
                    summary += f"\n  Permanentes: {len(permanent)}"

            # Compañías pausadas/limitadas
            if skipped_companies:
                summary += f"\n\n⏸️ Compañías omitidas: {len(skipped_companies)}"
                for skip_info in skipped_companies[:3]:  # Mostrar máximo 3
                    summary += f"\n  • {skip_info['company']}: {skip_info['reason']}"

                if len(skipped_companies) > 3:
                    summary += f"\n  ... y {len(skipped_companies) - 3} más"

            _logger.info("Cron VeriFactu completado: %s", summary)

    @api.model
    def cron_check_pending_verifacti_registrations(self):
        """Cron para verificar estado de facturas pendientes en VeriFactu

        REGLAS:
        - Esperar mínimo 3 minutos después de enviar
        - Solo consultar estados "Pendiente" o "Error servidor AEAT"
        - Si recibe 400/404, marcar para no volver a consultar
        """

        from datetime import timedelta

        now = fields.Datetime.now()
        min_wait = now - timedelta(minutes=3)  # Mínimo 3 minutos

        # Solo consultar facturas que pueden cambiar de estado
        invoices = self.search(
            [
                ("verifacti_state", "=", "pending"),
                (
                    "verifacti_registration_status",
                    "in",
                    ["Pendiente", "Error servidor AEAT"],
                ),
                ("verifacti_uuid", "!=", False),
                ("verifacti_sent_at", "!=", False),
                ("verifacti_sent_at", "<=", min_wait),
                (
                    "verifacti_check_status_failed",
                    "!=",
                    True,
                ),  # No consultar si ya falló
            ],
            limit=50,
        )

        if not invoices:
            return

        api_client = self.env["verifacti.api.client"]
        checked_count = 0
        updated_count = 0
        skipped_count = 0
        companies_processed = set()

        for invoice in invoices:
            try:
                # Obtener API key desde ir.config_parameter
                IrConfigParameter = self.env['ir.config_parameter'].sudo()
                api_key = IrConfigParameter.get_param(
                    f"verifacti_api.company_{invoice.company_id.id}.api_key",
                    default=""
                )

                if not api_key:
                    skipped_count += 1
                    continue

                if invoice.company_id.id not in companies_processed:
                    load_status = self._check_system_load_status(invoice.company_id)

                    if not load_status["can_process"]:
                        skipped_for_company = invoices.filtered(
                            lambda inv: inv.company_id.id == invoice.company_id.id
                        )
                        skipped_count += len(skipped_for_company)
                        companies_processed.add(invoice.company_id.id)
                        _logger.info(
                            "Verificación pausada para %s: carga alta",
                            invoice.company_id.name,
                        )
                        continue

                    companies_processed.add(invoice.company_id.id)

                old_status = invoice.verifacti_registration_status

                with self.env.cr.savepoint():
                    try:
                        response = api_client.with_context(
                            verifacti_company_id=invoice.company_id.id
                        ).get_registration_status(invoice.verifacti_uuid)
                        invoice._process_registration_status(response)
                        checked_count += 1

                        if old_status != invoice.verifacti_registration_status:
                            updated_count += 1

                    except UserError as e:
                        error_msg = str(e)
                        status_code = None

                        # Extraer status code si está en el mensaje
                        if "404" in error_msg:
                            status_code = 404
                        elif "400" in error_msg:
                            status_code = 400

                        # Si es 404 o 400, marcar para NO volver a consultar
                        if status_code in [400, 404]:
                            invoice.write(
                                {
                                    "verifacti_check_status_failed": True,
                                    "verifacti_state": "error",
                                    "verifacti_error_message": f"UUID no encontrado (HTTP {status_code})",
                                    "verifacti_error_code": str(status_code),
                                }
                            )
                            _logger.warning(
                                "UUID %s no encontrado (HTTP %s) - No se volverá a consultar",
                                invoice.verifacti_uuid,
                                status_code,
                            )
                            checked_count += 1  # Contar como procesada
                        else:
                            # Otros errores: loggear pero no marcar como failed
                            _logger.error(
                                "Error consultando UUID %s: %s",
                                invoice.verifacti_uuid,
                                error_msg,
                            )

            except Exception as e:
                _logger.error("Error procesando UUID %s: %s", invoice.verifacti_uuid, e)
                continue

        if checked_count > 0 or skipped_count > 0:
            _logger.info(
                "Verificación: Chequeadas=%s, Actualizadas=%s, Saltadas=%s",
                checked_count,
                updated_count,
                skipped_count,
            )

    def _process_registration_status(self, response):
        """Procesar respuesta de estado de registro

        IMPORTANTE: Según documentación API, si el estado NO es "Pendiente"
        o "Error servidor AEAT", el estado NUNCA cambiará → no consultar más.
        """
        self.ensure_one()

        if not response:
            _logger.warning(
                "No se recibió respuesta de estado para UUID %s", self.verifacti_uuid
            )
            return

        vals = {
            "verifacti_registration_status": response.get("estado"),
            "verifacti_api_response": str(response),
        }

        estado = response.get("estado")

        if estado == "Correcto":
            vals["verifacti_state"] = "correct"
            if response.get("qr"):
                vals["verifacti_qr"] = response.get("qr")
            # Estado final - no volver a consultar

        elif estado == "Pendiente":
            vals["verifacti_state"] = "pending"
            # Puede seguir consultándose

        elif estado == "Error servidor AEAT":
            vals["verifacti_state"] = "pending"  # Mantener pending, puede cambiar
            # Puede seguir consultándose

        elif estado in ["Incorrecto", "No registrado"]:
            vals["verifacti_state"] = "error"
            vals["verifacti_error_code"] = response.get("codigo_error")
            vals["verifacti_error_message"] = response.get("mensaje_error")
            vals["verifacti_qr"] = False
            # Estado final - no volver a consultar

        elif estado == "Anulado":
            vals["verifacti_state"] = "cancelled"
            vals["verifacti_qr"] = False
            # Estado final - no volver a consultar

        self.write(vals)

    # ============================================
    # CONTROL DE CARGA
    # ============================================

    @api.model
    def _get_system_load(self):
        """Obtener carga del sistema (load average)

        Returns:
            tuple: (load_1min, load_5min, load_15min) o None si no disponible
        """
        try:
            return os.getloadavg()
        except (AttributeError, OSError):
            return None

    @api.model
    def _check_system_load_status(self, company):
        """Verificar si el sistema puede procesar facturas según carga del CPU
        
        Args:
            company: Objeto res.company con la configuración
            
        Returns:
            dict: {
                'can_process': bool,
                'reason': str,
                'system_load': float,
                'max_load': float
            }
        """
        # Obtener IrConfigParameter
        IrConfigParameter = self.env['ir.config_parameter'].sudo()
        
        # Obtener parámetros una sola vez
        max_load_param = IrConfigParameter.get_param(
            f"verifacti_api.company_{company.id}.max_system_load", 
            default="4.0"
        )
        max_load = float(max_load_param)
        
        check_load_param = IrConfigParameter.get_param(
            f"verifacti_api.company_{company.id}.check_system_load", 
            default="True"
        )
        
        result = {
            "can_process": True,
            "reason": "Sistema con carga normal",
            "system_load": None,
            "max_load": max_load,
        }
        
        if check_load_param != "True":
            result["reason"] = "Verificación de carga deshabilitada"
            return result
        
        load_avg = self._get_system_load()
        if load_avg:
            current_load = load_avg[0]
            result["system_load"] = current_load
            
            if current_load > max_load:
                result["can_process"] = False
                result["reason"] = f"Carga alta: {current_load:.2f} > {max_load:.2f}"
        
        return result
