# -*- coding: utf-8 -*-

from odoo import models, fields, api
import json


class VerifactiApiLog(models.Model):
    """Log de llamadas a la API de Verifacti"""
    _name = 'verifacti.api.log'
    _description = 'Log API de Verifacti'
    _order = 'create_date desc'

    name = fields.Char(
        string='Nombre',
        compute='_compute_name',
        store=True
    )

    endpoint = fields.Char(
        string='Endpoint',
        required=True,
        index=True
    )

    method = fields.Selection(
        [('GET', 'GET'),
         ('POST', 'POST'),
         ('PUT', 'PUT'),
         ('DELETE', 'DELETE')],
        string='Método',
        required=True
    )

    request_data = fields.Text(
        string='Datos Request',
        help='Datos enviados en la petición'
    )

    response_data = fields.Text(
        string='Datos Response',
        help='Datos recibidos en la respuesta'
    )

    status_code = fields.Integer(
        string='Código Estado',
        help='Código de estado HTTP'
    )

    error = fields.Text(
        string='Error',
        help='Mensaje de error si lo hubo'
    )

    duration = fields.Float(
        string='Duración (ms)',
        help='Duración de la llamada en milisegundos'
    )

    create_date = fields.Datetime(
        string='Fecha',
        readonly=True
    )

    @api.depends('method', 'endpoint', 'create_date')
    def _compute_name(self):
        for log in self:
            log.name = f"{log.method} {log.endpoint} - {log.create_date}"

    @api.model
    def log_api_call(self, endpoint, method, request_data=None, response_data=None,
                    status_code=0, error=None, duration=0):
        """Crear registro de log de llamada API"""

        # Convertir datos a JSON string si es necesario
        if request_data and isinstance(request_data, dict):
            request_data = json.dumps(request_data, indent=2)

        if response_data and isinstance(response_data, dict):
            response_data = json.dumps(response_data, indent=2)

        return self.create({
            'endpoint': endpoint,
            'method': method,
            'request_data': request_data,
            'response_data': response_data,
            'status_code': status_code,
            'error': error,
            'duration': duration,
        })
