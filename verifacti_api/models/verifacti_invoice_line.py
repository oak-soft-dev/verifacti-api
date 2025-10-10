# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class VerifactiInvoiceLine(models.Model):
    """Líneas de factura VeriFactu"""
    _name = 'verifacti.invoice.line'
    _description = 'Línea de Factura VeriFactu'
    _order = 'invoice_id, sequence, id'

    invoice_id = fields.Many2one(
        'verifacti.invoice',
        string='Factura',
        required=True,
        ondelete='cascade',
        index=True
    )

    sequence = fields.Integer(
        string='Secuencia',
        default=10,
        help='Secuencia para ordenar las líneas'
    )

    # Campos obligatorios según API Verifacti
    base_imponible = fields.Char(
        string='Base Imponible',
        required=True,
        help='Base imponible o importe no sujeto de la línea. Formato: +/-999999999999.99'
    )

    impuesto = fields.Selection(
        [('01', '01: IVA'),
         ('02', '02: IPSI'),
         ('03', '03: IGIC'),
         ('05', '05: Otros')],
        string='Tipo de Impuesto',
        default='01',
        required=True,
        help='Tipo de impuesto aplicable'
    )

    # Campos opcionales
    tipo_impositivo = fields.Char(
        string='Tipo Impositivo (%)',
        help='Tipo impositivo. Para IVA: 0, 2, 4, 5, 7.5, 10, 21. Formato: 999.99'
    )

    cuota_repercutida = fields.Char(
        string='Cuota Repercutida',
        help='Cuota repercutida de la línea. Formato: +/-999999999999.99'
    )

    calificacion_operacion = fields.Selection(
        [('S1', 'S1: Sujeta y no exenta - sin inversión'),
         ('S2', 'S2: Sujeta y no exenta - con inversión'),
         ('N1', 'N1: No sujeta (art. 7, 14, otros)'),
         ('N2', 'N2: No sujeta por reglas de localización')],
        string='Calificación Operación',
        default='S1',
        help='Calificación de la operación'
    )

    clave_regimen = fields.Selection(
        [('01', '01: Régimen general'),
         ('02', '02: Exportación'),
         ('03', '03: Bienes usados, arte, antigüedades'),
         ('04', '04: Oro de inversión'),
         ('05', '05: Agencias de viajes'),
         ('06', '06: Grupo de entidades'),
         ('07', '07: Criterio de caja'),
         ('08', '08: Operaciones sujetas IPSI/IVA/IGIC'),
         ('09', '09: Agencias de viaje mediadoras'),
         ('10', '10: Cobros por cuenta de terceros'),
         ('11', '11: Arrendamiento local de negocio'),
         ('14', '14: IVA/IGIC pendiente certificaciones obra'),
         ('15', '15: IVA/IGIC pendiente tracto sucesivo'),
         ('17', '17: OSS, IOSS o comerciante minorista'),
         ('18', '18: Recargo equivalencia o pequeño empresario'),
         ('19', '19: REAGYP o exentas art. 25 Ley 19/1994'),
         ('20', '20: Régimen simplificado')],
        string='Clave Régimen',
        default='01',
        help='Clave que identifica el tipo de régimen'
    )

    operacion_exenta = fields.Selection(
        [('E1', 'E1: Exenta por artículo 20'),
         ('E2', 'E2: Exenta por artículo 21'),
         ('E3', 'E3: Exenta por artículo 22'),
         ('E4', 'E4: Exenta por artículo 24'),
         ('E5', 'E5: Exenta por artículo 25'),
         ('E6', 'E6: Otros')],
        string='Operación Exenta',
        help='Tipo de operación exenta (BOE-A-1992-28740)'
    )

    base_imponible_a_coste = fields.Char(
        string='Base Imponible a Coste',
        help='Solo si clave_regimen = 06 o impuesto = 02/05. Formato: +/-999999999999.99'
    )

    tipo_recargo_equivalencia = fields.Char(
        string='Tipo Recargo Equivalencia (%)',
        help='Tipo de recargo de equivalencia. Formato: 999.99'
    )

    cuota_recargo_equivalencia = fields.Char(
        string='Cuota Recargo Equivalencia',
        help='Cuota recargo de equivalencia. Formato: +/-999999999999.99'
    )

    # Campos calculados para visualización
    currency_id = fields.Many2one(
        'res.currency',
        related='invoice_id.currency_id',
        string='Moneda',
        readonly=True
    )

    @api.constrains('tipo_impositivo')
    def _check_tipo_impositivo(self):
        """Validar tipo impositivo para IVA"""
        for line in self:
            if line.impuesto == '01' and line.tipo_impositivo:
                try:
                    tipo = float(line.tipo_impositivo)
                    valid_types = [0, 2, 4, 5, 7.5, 10, 21]
                    if tipo not in valid_types:
                        raise ValidationError(_(
                            'Para IVA, el tipo impositivo debe ser uno de: 0, 2, 4, 5, 7.5, 10, 21'
                        ))
                except ValueError:
                    raise ValidationError(_('El tipo impositivo debe ser un número válido'))

    @api.constrains('operacion_exenta', 'tipo_impositivo', 'cuota_repercutida',
                    'tipo_recargo_equivalencia', 'cuota_recargo_equivalencia')
    def _check_operacion_exenta(self):
        """Validar que operación exenta no tenga impuestos"""
        for line in self:
            if line.operacion_exenta:
                if any([line.tipo_impositivo, line.cuota_repercutida,
                       line.tipo_recargo_equivalencia, line.cuota_recargo_equivalencia]):
                    raise ValidationError(_(
                        'Si la operación es exenta, no puede tener tipo impositivo, '
                        'cuota repercutida ni recargo de equivalencia'
                    ))

    @api.onchange('impuesto')
    def _onchange_impuesto(self):
        """Limpiar clave_regimen si no es IVA o IGIC"""
        if self.impuesto not in ['01', '03']:
            self.clave_regimen = False
