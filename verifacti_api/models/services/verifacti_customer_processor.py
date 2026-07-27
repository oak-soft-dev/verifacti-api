# -*- coding: utf-8 -*-
"""
Procesador de Datos de Clientes para VeriFactu
===============================================

Servicio especializado en procesar y preparar datos de clientes
según la normativa VeriFactu de la AEAT.

Responsabilidades:
- Validar datos obligatorios del cliente
- Procesar VAT/NIF según tipo de factura
- Formatear datos para API VeriFactu
- Gestionar clientes españoles vs extranjeros
- Gestionar facturas simplificadas (sin datos de cliente)
"""

from odoo import models, api, _
from odoo.exceptions import ValidationError
import logging

from ..utils.vat_parser import VatParser

_logger = logging.getLogger(__name__)


class VerifactiCustomerProcessor(models.AbstractModel):
    """Servicio para procesar datos de clientes para VeriFactu"""

    _name = 'verifacti.customer.processor'
    _description = 'Procesador de Clientes VeriFactu'

    @api.model
    def process_customer_for_invoice(self, invoice):
        """
        Procesar datos del cliente para una factura

        Args:
            invoice: Objeto account.move

        Returns:
            dict: Datos del cliente formateados para API VeriFactu
                {
                    'nombre': str,        # Nombre del cliente (opcional si simplificada)
                    'nif': str,          # NIF español (opcional si simplificada o extranjero)
                    'id_otro': dict      # Datos extranjeros (opcional)
                }

        Nota:
            Las facturas simplificadas (F2, R5) NO incluyen datos del cliente
        """
        invoice.ensure_one()

        # Verificar si es factura simplificada
        if self._is_simplified_invoice(invoice):
            return self._process_simplified_invoice(invoice)

        # Facturas normales: datos del cliente OBLIGATORIOS
        return self._process_normal_invoice(invoice)

    @api.model
    def _is_simplified_invoice(self, invoice):
        """Verificar si es factura simplificada (F2 o R5)"""
        return invoice.verifacti_tipo_factura in ['F2', 'R5']

    @api.model
    def _process_simplified_invoice(self, invoice):
        """
        Procesar factura simplificada (F2, R5)

        Según normativa AEAT:
        - Las facturas simplificadas son ANÓNIMAS
        - NO se deben enviar datos del cliente
        - La API rechazará la factura si se incluyen

        Returns:
            dict: Diccionario vacío (no se envían datos)
        """
        _logger.debug(
            "Factura simplificada ID %s (%s): No se envían datos del cliente",
            invoice.id,
            invoice.verifacti_tipo_factura
        )

        # Registrar en chatter si el cliente tiene datos
        if invoice.partner_id and invoice.partner_id.vat:
            invoice.message_post(
                body=_(
                    "ℹ️ <strong>Factura Simplificada (%s)</strong><br/>"
                    "Según normativa VeriFactu, no se envían datos del cliente.<br/>"
                    "Cliente interno: %s"
                ) % (invoice.verifacti_tipo_factura, invoice.partner_id.name),
                message_type="comment"
            )

        # NO retornar ningún dato de cliente
        return {}

    @api.model
    def _process_normal_invoice(self, invoice):
        """
        Procesar factura normal (F1, R1-R4, F3)

        Para facturas normales los datos del cliente son OBLIGATORIOS:
        - Nombre
        - NIF (español o extranjero)

        Returns:
            dict: Datos del cliente formateados
        """
        # Validar que existe cliente
        if not invoice.partner_id:
            raise ValidationError(_(
                "La factura tipo %s debe tener un cliente asignado"
            ) % invoice.verifacti_tipo_factura)

        customer_data = {}

        # 1. NOMBRE (obligatorio)
        customer_data['nombre'] = self._get_customer_name(invoice.partner_id)

        # 2. VAT/NIF (obligatorio)
        vat_data = self._process_customer_vat(invoice)

        # Añadir datos de VAT al resultado
        customer_data.update(vat_data)

        return customer_data

    @api.model
    def _get_customer_name(self, partner):
        """Obtener y validar nombre del cliente"""
        if not partner.name:
            raise ValidationError(_(
                "El cliente debe tener un nombre configurado"
            ))

        return partner.name

    @api.model
    def _process_customer_vat(self, invoice):
        """
        Procesar VAT del cliente y formatear para VeriFactu

        Returns:
            dict: {'nif': str} para españoles
                  {'id_otro': {...}} para extranjeros
        """
        partner = invoice.partner_id

        # Validar que tiene VAT
        if not partner.vat:
            raise ValidationError(_(
                'El cliente "%s" debe tener un NIF/CIF configurado.\n\n'
                'Para facturas tipo %s el NIF es OBLIGATORIO según normativa VeriFactu.'
            ) % (partner.name, invoice.verifacti_tipo_factura))

        # Parsear VAT usando VatParser
        try:
            vat_result = VatParser.format_for_verifacti(
                partner.vat,
                partner.country_id.code if partner.country_id else None
            )

            # Log según tipo
            if 'nif' in vat_result:
                _logger.debug(
                    "Factura %s: Cliente español - NIF: %s",
                    invoice.name,
                    vat_result['nif']
                )
            else:
                _logger.debug(
                    "Factura %s: Cliente extranjero - País: %s, ID: %s",
                    invoice.name,
                    vat_result['id_otro']['codigo_pais'],
                    vat_result['id_otro']['id']
                )

                # Registrar en chatter para clientes extranjeros
                id_type_desc = (
                    "UE" if vat_result['id_otro']['id_type'] == '02' else "No-UE"
                )
                invoice.message_post(
                    body=_(
                        "ℹ️ <strong>Cliente Extranjero</strong><br/>"
                        "País: %s<br/>"
                        "Tipo: %s<br/>"
                        "ID: %s"
                    ) % (
                        partner.country_id.name if partner.country_id else vat_result['id_otro']['codigo_pais'],
                        id_type_desc,
                        vat_result['id_otro']['id']
                    ),
                    message_type="comment"
                )

            return vat_result

        except ValidationError as e:
            # Re-lanzar con contexto adicional
            raise ValidationError(_(
                "Error procesando VAT del cliente '%s':\n\n%s"
            ) % (partner.name, str(e)))

    @api.model
    def validate_customer_data(self, invoice):
        """
        Validar que los datos del cliente son correctos antes de enviar

        Args:
            invoice: Objeto account.move

        Raises:
            ValidationError: Si los datos no son válidos

        Returns:
            bool: True si es válido
        """
        # Facturas simplificadas no necesitan validación de cliente
        if self._is_simplified_invoice(invoice):
            return True

        # Validar que existe partner
        if not invoice.partner_id:
            raise ValidationError(_(
                "La factura %s (tipo %s) debe tener un cliente asignado"
            ) % (invoice.name or invoice.id, invoice.verifacti_tipo_factura))

        # Validar nombre
        if not invoice.partner_id.name:
            raise ValidationError(_(
                "El cliente de la factura %s debe tener un nombre"
            ) % (invoice.name or invoice.id))

        # Validar VAT
        if not invoice.partner_id.vat:
            raise ValidationError(_(
                "El cliente '%s' de la factura %s debe tener un NIF/CIF.\n\n"
                "El NIF es obligatorio para facturas tipo %s según normativa VeriFactu."
            ) % (
                invoice.partner_id.name,
                invoice.name or invoice.id,
                invoice.verifacti_tipo_factura
            ))

        # Intentar parsear VAT para validar formato
        try:
            VatParser.parse(
                invoice.partner_id.vat,
                invoice.partner_id.country_id.code if invoice.partner_id.country_id else None
            )
        except ValidationError as e:
            raise ValidationError(_(
                "VAT inválido para cliente '%s' en factura %s:\n\n%s"
            ) % (
                invoice.partner_id.name,
                invoice.name or invoice.id,
                str(e)
            ))

        return True
