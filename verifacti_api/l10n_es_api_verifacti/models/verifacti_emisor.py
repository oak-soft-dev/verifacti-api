# -*- coding: utf-8 -*-

import hashlib
import hmac
import secrets

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..verifactu import constants


class VerifactiEmisor(models.Model):
    """Emisor (obligado a expedir factura) con su API key y certificado."""

    _name = "l10n_es_verifacti.emisor"
    _description = "Emisor VeriFactu"
    _inherit = ["mail.thread"]
    _rec_name = "nombre_razon"

    active = fields.Boolean(default=True)
    nif = fields.Char(string="NIF", required=True, size=9, tracking=True)
    nombre_razon = fields.Char(string="Nombre / Razón social", required=True, tracking=True)
    api_key = fields.Char(
        string="API Key",
        required=True,
        index=True,
        copy=False,
        default=lambda self: self._generate_api_key(),
        help="Clave Bearer que usa el cliente (mínimo 20 caracteres)",
    )
    entorno = fields.Selection(
        [("test", "Test (preproducción AEAT)"), ("produccion", "Producción")],
        required=True,
        default="test",
        tracking=True,
    )
    certificate_id = fields.Many2one(
        "certificate.certificate",
        string="Certificado (PKCS#12)",
        help="Certificado de sello/representante del emisor para el envío mTLS a la AEAT",
    )

    # Datos del bloque SistemaInformatico (declaración responsable)
    si_nombre_razon = fields.Char(string="SI: Nombre productor", required=True, default="ISN")
    si_nif = fields.Char(string="SI: NIF productor", size=9)
    si_nombre_sistema = fields.Char(string="SI: Nombre sistema", required=True, default="l10n_es_api_verifacti")
    si_id_sistema = fields.Char(string="SI: Id sistema", required=True, size=2, default="01")
    si_version = fields.Char(string="SI: Versión", required=True, default="1.0")
    si_numero_instalacion = fields.Char(
        string="SI: Nº instalación",
        required=True,
        default=lambda self: self._default_numero_instalacion(),
    )
    si_solo_verifactu = fields.Selection([("S", "S"), ("N", "N")], required=True, default="S")
    si_multi_ot = fields.Selection([("S", "S"), ("N", "N")], required=True, default="S")
    si_indicador_multiples_ot = fields.Selection([("S", "S"), ("N", "N")], required=True, default="S")

    # Encadenamiento y control de flujo
    chain_sequence_id = fields.Many2one("ir.sequence", readonly=True, copy=False)
    last_registro_id = fields.Many2one("l10n_es_verifacti.registro", readonly=True, copy=False)
    next_batch_time = fields.Datetime(
        string="Próximo envío AEAT",
        copy=False,
        help="Momento a partir del cual se puede volver a enviar a la AEAT (TiempoEsperaEnvio)",
    )

    registro_count = fields.Integer(compute="_compute_registro_count")

    _sql_constraints = [
        ("nif_uniq", "unique(nif)", "Ya existe un emisor con ese NIF"),
        ("api_key_uniq", "unique(api_key)", "Ya existe un emisor con esa API key"),
    ]

    @api.model
    def _generate_api_key(self):
        return secrets.token_hex(24)  # 48 caracteres hex

    def _default_numero_instalacion(self):
        database_uuid = self.env["ir.config_parameter"].sudo().get_param("database.uuid") or ""
        return hashlib.sha256(database_uuid.encode("utf-8")).hexdigest().upper()

    def _compute_registro_count(self):
        counts = dict(
            self.env["l10n_es_verifacti.registro"]._read_group(
                [("emisor_id", "in", self.ids)], groupby=["emisor_id"], aggregates=["__count"]
            )
        )
        for emisor in self:
            registro = counts.get(emisor)
            emisor.registro_count = registro or 0

    def action_regenerate_api_key(self):
        for emisor in self:
            emisor.api_key = self._generate_api_key()

    def action_view_registros(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Registros de %s", self.nombre_razon),
            "res_model": "l10n_es_verifacti.registro",
            "view_mode": "list,form",
            "domain": [("emisor_id", "=", self.id)],
        }

    @api.model
    def _find_by_api_key(self, api_key):
        """Buscar emisor activo por API key (comparación en tiempo constante)."""
        if not api_key:
            return self.browse()
        for emisor in self.sudo().search([]):
            if hmac.compare_digest(emisor.api_key or "", api_key):
                return emisor
        return self.browse()

    def _get_endpoints(self):
        self.ensure_one()
        return constants.ENDPOINTS[self.entorno]

    def _get_chain_sequence(self):
        self.ensure_one()
        if not self.chain_sequence_id:
            self_sudo = self.sudo()
            self_sudo.chain_sequence_id = self_sudo.env["ir.sequence"].create(
                {
                    "name": f"Cadena VeriFactu emisor {self.nif}",
                    "code": f"l10n_es_verifacti.registro.{self.id}",
                    "implementation": "no_gap",
                }
            )
        return self.chain_sequence_id

    def _lock(self):
        """Serializar la generación de registros del emisor (integridad de la cadena)."""
        self.ensure_one()
        self.env.cr.execute(
            "SELECT id FROM l10n_es_verifacti_emisor WHERE id = %s FOR UPDATE", (self.id,)
        )

    def _get_sistema_informatico(self):
        self.ensure_one()
        if not self.si_nif:
            raise UserError(_("Configure el NIF del productor del sistema informático en el emisor %s", self.nombre_razon))
        return {
            "nombre_razon": self.si_nombre_razon,
            "nif": self.si_nif.upper().strip(),
            "nombre_sistema": self.si_nombre_sistema[:30],
            "id_sistema": self.si_id_sistema,
            "version": self.si_version,
            "numero_instalacion": self.si_numero_instalacion[:100],
            "solo_verifactu": self.si_solo_verifactu,
            "multi_ot": self.si_multi_ot,
            "indicador_multiples_ot": self.si_indicador_multiples_ot,
        }

