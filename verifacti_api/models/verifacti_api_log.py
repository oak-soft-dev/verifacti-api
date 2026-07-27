# -*- coding: utf-8 -*-

from odoo import models, fields, api
import json


class VerifactiApiLog(models.Model):
    """Log de llamadas a la API de Verifacti"""

    _name = "verifacti.api.log"
    _description = "Log API de Verifacti"
    _order = "create_date desc"

    name = fields.Char(string="Nombre", compute="_compute_name", store=True)

    endpoint = fields.Char(string="Endpoint", required=True, index=True)

    method = fields.Selection(
        [
            ("GET", "GET"),
            ("POST", "POST"),
            ("PUT", "PUT"),
            ("DELETE", "DELETE"),
            ("PATCH", "PATCH"),
            ("INFO", "INFO"),
            ("PREPARE", "PREPARE"),
            ("PAUSE", "PAUSE"),
            ("RESUME", "RESUME"),
        ],
        string="Método",
        required=True,
    )

    request_data = fields.Text(
        string="Datos Request", help="Datos enviados en la petición"
    )

    response_data = fields.Text(
        string="Datos Response", help="Datos recibidos en la respuesta"
    )

    status_code = fields.Integer(
        string="Código Estado", help="Código de estado HTTP", index=True
    )

    error = fields.Text(string="Error", help="Mensaje de error si lo hubo")

    duration = fields.Float(
        string="Duración (ms)", help="Duración de la llamada en milisegundos"
    )

    create_date = fields.Datetime(string="Fecha", readonly=True, index=True)

    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        index=True,
        help="Compañía relacionada con la llamada",
    )

    log_type = fields.Selection(
        [
            ("api", "API"),
            ("cron", "Cron"),
            ("manual", "Manual"),
            ("system", "Sistema"),
        ],
        string="Tipo de Log",
        default="api",
        required=True,
        index=True,
        help="Tipo de operación registrada",
    )

    @api.depends("method", "endpoint", "create_date")
    def _compute_name(self):
        for log in self:
            if log.create_date:
                date_str = log.create_date.strftime("%Y-%m-%d %H:%M:%S")
                log.name = f"{log.method} {log.endpoint} - {date_str}"
            else:
                log.name = f"{log.method} {log.endpoint}"

    @api.model
    def log_api_call(
        self,
        endpoint,
        method,
        request_data=None,
        response_data=None,
        status_code=0,
        error=None,
        duration=0,
        company_id=None,
        log_type="api",
    ):
        """Crear registro de log de llamada API

        Args:
            endpoint: Ruta del endpoint
            method: Método HTTP (GET, POST, PUT, DELETE, PATCH)
            request_data: Datos de la petición (dict o str)
            response_data: Datos de la respuesta (dict o str)
            status_code: Código de estado HTTP
            error: Mensaje de error
            duration: Duración en milisegundos
            company_id: ID de la compañía
            log_type: Tipo de log (api, cron, manual, system)
        """
        # Convertir datos a JSON string si es necesario
        if request_data and isinstance(request_data, dict):
            request_data = json.dumps(request_data, indent=2, ensure_ascii=False)

        if response_data and isinstance(response_data, dict):
            response_data = json.dumps(response_data, indent=2, ensure_ascii=False)

        return self.create(
            {
                "endpoint": endpoint,
                "method": method,
                "request_data": request_data,
                "response_data": response_data,
                "status_code": status_code,
                "error": error,
                "duration": duration,
                "company_id": company_id,
                "log_type": log_type,
            }
        )

    @api.model
    def log_cron_execution(
        self, action, message, status_code=200, error=None, details=None
    ):
        """Método específico para logs de cron

        Args:
            action: Acción del cron (send_pending, check_status, pause, resume, etc.)
            message: Mensaje descriptivo
            status_code: Código de estado (200=OK, 207=Parcial, 500=Error)
            error: Mensaje de error si lo hubo
            details: Detalles adicionales (dict)
        """
        # Preparar datos de respuesta
        response_data = {"message": message}
        if details:
            response_data.update(details)

        return self.create(
            {
                "endpoint": f"/cron/{action}",
                "method": "POST",
                "response_data": json.dumps(
                    response_data, indent=2, ensure_ascii=False
                ),
                "status_code": status_code,
                "error": error,
                "duration": 0.0,
                "log_type": "cron",
            }
        )

    @api.model
    def cleanup_old_logs(self, days=30):
        """Limpiar logs antiguos para evitar acumulación

        Args:
            days: Número de días a mantener (por defecto 30)
        """
        domain = [
            ("create_date", "<", fields.Datetime.now() - fields.timedelta(days=days))
        ]
        old_logs = self.search(domain)
        count = len(old_logs)
        old_logs.unlink()
        return count

    def action_view_details(self):
        """Acción para ver detalles del log en una vista formulario"""
        self.ensure_one()
        return {
            "name": "Detalles del Log",
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }
