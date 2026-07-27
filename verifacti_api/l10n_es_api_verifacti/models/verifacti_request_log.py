# -*- coding: utf-8 -*-

import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

LOG_RETENTION_DAYS = 90
BODY_MAX_CHARS = 5000


class VerifactiRequestLog(models.Model):
    """Log de peticiones a la API del servidor VeriFactu."""

    _name = "l10n_es_verifacti.request.log"
    _description = "Log de peticiones API VeriFactu"
    _order = "id desc"

    endpoint = fields.Char(readonly=True, index=True)
    method = fields.Char(readonly=True)
    emisor_id = fields.Many2one("l10n_es_verifacti.emisor", readonly=True, index=True)
    api_key_prefix = fields.Char(readonly=True)
    remote_addr = fields.Char(readonly=True)
    status_code = fields.Integer(readonly=True)
    request_body = fields.Text(readonly=True)
    response_body = fields.Text(readonly=True)
    duration_ms = fields.Float(readonly=True)

    @api.model
    def log_request(self, endpoint, method, emisor, api_key, remote_addr,
                    status_code, request_body, response_body, duration_ms):
        try:
            self.sudo().create(
                {
                    "endpoint": endpoint,
                    "method": method,
                    "emisor_id": emisor.id if emisor else False,
                    "api_key_prefix": (api_key or "")[:8],
                    "remote_addr": remote_addr or "",
                    "status_code": status_code,
                    "request_body": (request_body or "")[:BODY_MAX_CHARS],
                    "response_body": (response_body or "")[:BODY_MAX_CHARS],
                    "duration_ms": duration_ms,
                }
            )
        except Exception:
            # El logging nunca debe romper la petición
            _logger.exception("No se pudo registrar el log de la petición %s", endpoint)

    @api.model
    def _cron_vacuum(self):
        limite = fields.Datetime.now() - timedelta(days=LOG_RETENTION_DAYS)
        registros = self.sudo().search([("create_date", "<", limite)])
        registros.unlink()
