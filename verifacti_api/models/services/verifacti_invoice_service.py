# -*- coding: utf-8 -*-
"""
Servicio de Procesamiento de Facturas para VeriFactu
====================================================

Servicio especializado en preparar datos de facturas para envío a VeriFactu.

Responsabilidades:
- Preparar datos completos de factura para API
- Validar facturas antes de envío
- Normalizar líneas de factura
- Calcular totales con ajustes
- Agrupar líneas cuando superan límite
"""

from odoo import models, api, _
from odoo.exceptions import ValidationError
from odoo.tools import float_compare
import logging

_logger = logging.getLogger(__name__)

# Límites según normativa
MAX_LINES_BEFORE_GROUPING = 12  # Límite AEAT


class VerifactiInvoiceService(models.AbstractModel):
    """Servicio para procesar facturas para VeriFactu"""

    _name = 'verifacti.invoice.service'
    _description = 'Servicio de Procesamiento de Facturas VeriFactu'

    @api.model
    def prepare_invoice_for_api(self, invoice):
        """
        Preparar datos completos de factura para envío a API VeriFactu

        Args:
            invoice: Objeto account.move

        Returns:
            dict: Datos de factura formateados para API
        """
        invoice.ensure_one()

        # Validar antes de preparar
        self._validate_invoice(invoice)

        # Obtener servicios auxiliares
        api_client = self.env['verifacti.api.client']
        customer_processor = self.env['verifacti.customer.processor']

        # Preparar líneas de factura
        lineas, ajustes = self._prepare_invoice_lines(invoice, api_client)

        # Agrupar si supera límite
        if len(lineas) > MAX_LINES_BEFORE_GROUPING:
            lineas = self._group_lines_by_tax(lineas)
            invoice.message_post(
                body=_(
                    "ℹ️ <strong>Líneas agrupadas por impuesto</strong><br/>"
                    "Líneas originales: %s<br/>"
                    "Líneas agrupadas: %s"
                ) % (len(invoice.invoice_line_ids), len(lineas)),
                message_type="notification"
            )

        # Parsear número de factura
        serie, numero = self._parse_invoice_number(invoice)

        # Calcular importe total
        importe_total = self._calculate_total_with_adjustments(
            invoice, lineas, ajustes
        )

        # Obtener descripción
        descripcion = self._get_invoice_description(invoice)

        # Construir datos base de la factura
        invoice_data = {
            "serie": serie,
            "numero": numero,
            "fecha_expedicion": api_client.format_date(invoice.invoice_date),
            "tipo_factura": invoice.verifacti_tipo_factura,
            "descripcion": descripcion[:500] if descripcion else "Factura",
            "lineas": lineas,
            "importe_total": str(importe_total),
            "validar_destinatario": invoice.verifacti_validar_destinatario,
        }

        # Añadir datos del cliente
        customer_data = customer_processor.process_customer_for_invoice(invoice)
        invoice_data.update(customer_data)

        # Añadir datos específicos de facturas rectificativas
        if invoice.verifacti_tipo_factura in ['R1', 'R2', 'R3', 'R4', 'R5']:
            tipo_rect = invoice.verifacti_tipo_rectificativa or 'I'
            invoice_data["tipo_rectificativa"] = tipo_rect

        # Añadir incidencia si está marcada
        if invoice.verifacti_incidencia:
            invoice_data["incidencia"] = "S"

        _logger.debug(
            "Factura %s preparada para envío: %s líneas, %.2f€",
            invoice.name,
            len(lineas),
            importe_total
        )

        return invoice_data

    @api.model
    def _validate_invoice(self, invoice):
        """
        Validar factura antes de preparar para envío

        Raises:
            ValidationError: Si la factura no cumple los requisitos
        """
        errors = []

        # Validar estado
        if invoice.state != 'posted':
            errors.append("La factura debe estar publicada")

        # Validar tipo de factura
        invoice_type = invoice._get_invoice_type()
        if invoice_type not in ['out_invoice', 'out_refund']:
            errors.append(f"Tipo de documento inválido: {invoice_type}")

        # Validar líneas
        if not invoice.invoice_line_ids:
            errors.append("La factura debe tener al menos una línea")

        # Validar importe
        if invoice.amount_total <= 0:
            errors.append("El importe total debe ser mayor a 0")

        # Validar tipo VeriFactu
        if not invoice.verifacti_tipo_factura:
            errors.append("Debe seleccionar un tipo de factura VeriFactu (F1, F2, R1, etc.)")

        # Validar tipo rectificativa si aplica
        if invoice.verifacti_tipo_factura in ['R1', 'R2', 'R3', 'R4', 'R5']:
            if not invoice.verifacti_tipo_rectificativa:
                errors.append(
                    "Las facturas rectificativas requieren especificar el Tipo Rectificativa (S o I)"
                )

        # Validar límites según sector
        if invoice.verifacti_tipo_factura in ['F2', 'R5']:
            # Obtener sector especial desde configuración
            sector_especial = invoice._get_verifacti_config('sector_especial', False)
            limite = 3000.0 if sector_especial else 400.0
            if invoice.amount_total > limite:
                errors.append(
                    f"Tipo {invoice.verifacti_tipo_factura} no puede superar {limite:.0f}€. "
                    f"Importe actual: {invoice.amount_total:.2f}€"
                )

        # Validar datos del cliente (si no es simplificada)
        if invoice.verifacti_tipo_factura not in ['F2', 'R5']:
            customer_processor = self.env['verifacti.customer.processor']
            try:
                customer_processor.validate_customer_data(invoice)
            except ValidationError as e:
                errors.append(str(e))

        if errors:
            raise ValidationError(
                _("Errores en factura %s:\n\n• %s") % (
                    invoice.name or invoice.id,
                    "\n• ".join(errors)
                )
            )

        return True

    @api.model
    def _prepare_invoice_lines(self, invoice, api_client):
        """
        Preparar líneas de factura con normalización de impuestos

        Returns:
            tuple: (lineas, ajustes_realizados)
        """
        lineas = []
        ajustes_realizados = []

        for line in invoice.invoice_line_ids:
            # Saltar líneas de sección y nota
            if line.display_type in ('line_section', 'line_note'):
                continue

            base_imponible = line.price_subtotal
            tipo_impositivo_original = None
            cuota_repercutida_original = 0.0
            codigo_impuesto = '01'  # IVA por defecto

            # Procesar impuestos
            for tax in line.tax_ids:
                if tax.amount > 0:
                    tipo_impositivo_original = tax.amount
                    cuota_repercutida_original = line.price_total - line.price_subtotal
                    codigo_impuesto = self._detect_tax_code(tax)
                    break

            # Preparar línea base
            line_data = {
                "base_imponible": str(round(base_imponible, 2)),
                "impuesto": codigo_impuesto,
            }

            # Normalizar tipo impositivo
            if tipo_impositivo_original is not None:
                tipo_normalizado = api_client.normalize_tipo_impositivo(
                    tipo_impositivo_original
                )

                if tipo_normalizado is not None:
                    line_data["tipo_impositivo"] = str(tipo_normalizado)

                    # Si cambió el tipo, recalcular cuota
                    if float_compare(tipo_impositivo_original, tipo_normalizado, precision_digits=2) != 0:
                        cuota_recalculada = round(base_imponible * tipo_normalizado / 100, 2)
                        line_data["cuota_repercutida"] = str(cuota_recalculada)

                        ajustes_realizados.append({
                            "linea": line.name[:50] if line.name else "Sin descripción",
                            "base": base_imponible,
                            "tipo_original": tipo_impositivo_original,
                            "tipo_normalizado": tipo_normalizado,
                            "cuota_original": cuota_repercutida_original,
                            "cuota_recalculada": cuota_recalculada,
                            "diferencia": cuota_recalculada - cuota_repercutida_original,
                        })
                    else:
                        line_data["cuota_repercutida"] = str(round(cuota_repercutida_original, 2))

            # Valores por defecto si no hay impuesto
            if "tipo_impositivo" not in line_data:
                line_data["tipo_impositivo"] = "0.00"
            if "cuota_repercutida" not in line_data:
                line_data["cuota_repercutida"] = "0.00"

            lineas.append(line_data)

        return lineas, ajustes_realizados

    @api.model
    def _detect_tax_code(self, tax):
        """
        Detectar código de impuesto para VeriFactu

        Códigos:
        - 01: IVA
        - 02: IPSI (Ceuta y Melilla)
        - 03: IGIC (Canarias)
        """
        # Método 1: tax_scope (si existe en localización española)
        if hasattr(tax, 'tax_scope'):
            scope = tax.tax_scope
            if scope == 'consu':
                return '02'  # IPSI
            elif scope == 'igic':
                return '03'  # IGIC
            elif scope in ['vat', 'service']:
                return '01'  # IVA

        # Método 2: Fallback por nombre
        tax_name = (tax.name or '').upper()
        if 'IPSI' in tax_name:
            return '02'
        elif 'IGIC' in tax_name:
            return '03'

        # Por defecto: IVA
        return '01'

    @api.model
    def _group_lines_by_tax(self, lineas):
        """Agrupar líneas por tipo de impuesto cuando superan el límite"""
        from collections import defaultdict

        grupos = defaultdict(lambda: {'base_imponible': 0.0, 'cuota_repercutida': 0.0})

        for linea in lineas:
            key = (linea['impuesto'], linea.get('tipo_impositivo', '0.00'))
            grupos[key]['base_imponible'] += float(linea['base_imponible'])
            grupos[key]['cuota_repercutida'] += float(linea.get('cuota_repercutida', '0.00'))

        lineas_agrupadas = []
        for (codigo_impuesto, tipo_impositivo), valores in grupos.items():
            lineas_agrupadas.append({
                "base_imponible": str(round(valores['base_imponible'], 2)),
                "impuesto": codigo_impuesto,
                "tipo_impositivo": tipo_impositivo,
                "cuota_repercutida": str(round(valores['cuota_repercutida'], 2)),
            })

        return lineas_agrupadas

    @api.model
    def _calculate_total_with_adjustments(self, invoice, lineas, ajustes):
        """Calcular importe total y registrar ajustes si los hay"""
        importe_calculado = sum(
            float(linea['base_imponible']) + float(linea.get('cuota_repercutida', 0))
            for linea in lineas
        )
        importe_calculado = round(importe_calculado, 2)
        importe_original = round(invoice.amount_total, 2)

        diferencia = abs(importe_calculado - importe_original)

        # Usar importe calculado si la diferencia es significativa
        if diferencia > 0.10:
            _logger.warning(
                "Factura %s: Importe ajustado de %.2f€ a %.2f€ (diferencia: %.2f€)",
                invoice.name,
                importe_original,
                importe_calculado,
                diferencia
            )
            importe_final = importe_calculado
        else:
            importe_final = importe_original

        # Registrar ajustes en el chatter si los hay
        if ajustes:
            mensaje = _("⚠️ <strong>Ajustes en tipos impositivos:</strong><br/><br/>")
            for ajuste in ajustes:
                mensaje += _(
                    "• %s<br/>"
                    "  Base: %.2f€ | Tipo: %.2f%% → %.2f%% | "
                    "Cuota: %.2f€ → %.2f€ (dif: %.2f€)<br/>"
                ) % (
                    ajuste["linea"],
                    ajuste["base"],
                    ajuste["tipo_original"],
                    ajuste["tipo_normalizado"],
                    ajuste["cuota_original"],
                    ajuste["cuota_recalculada"],
                    ajuste["diferencia"],
                )

            mensaje += _("<br/>Importe total: %.2f€ → %.2f€") % (
                importe_original,
                importe_final
            )

            invoice.message_post(
                body=mensaje,
                subject=_("Ajustes VeriFactu"),
                message_type="notification"
            )

        return importe_final

    @api.model
    def _parse_invoice_number(self, invoice):
        """Parsear número de factura en serie y número"""
        if not invoice.name:
            return ("", "")

        parts = invoice.name.rsplit('/', 1)
        if len(parts) == 2:
            return (parts[0], parts[1])
        else:
            return ("", invoice.name)

    @api.model
    def _get_invoice_description(self, invoice):
        """Generar descripción automática para VeriFactu"""
        if not invoice.invoice_line_ids:
            return invoice.narration or "Factura"

        descriptions = [
            line.name
            for line in invoice.invoice_line_ids
            if line.display_type not in ('line_section', 'line_note') and line.name
        ]

        if not descriptions:
            return invoice.narration or "Factura"

        desc = ", ".join(descriptions[:3])
        if len(descriptions) > 3:
            desc += f" (+{len(descriptions) - 3} más)"

        return (desc[:497] + "...") if len(desc) > 500 else desc
