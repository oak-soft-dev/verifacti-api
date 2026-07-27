# -*- coding: utf-8 -*-

import json
import logging
import uuid as uuid_lib
from datetime import datetime, timedelta

from lxml import etree
from pytz import timezone

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..verifactu import constants, qr, soap_client, validation, xml_builder

_logger = logging.getLogger(__name__)

MADRID = timezone("Europe/Madrid")

# Backoff de reintentos para errores de servidor AEAT (segundos)
RETRY_BACKOFF_MIN = 60
RETRY_BACKOFF_MAX = 1800
RETRY_ALERT_COUNT = 48

# Margen del error AEAT 2004 (FechaHoraHusoGenRegistro > 240s)
INCIDENT_SECONDS = 240


class VerifactiRegistro(models.Model):
    """Registro de facturación VeriFactu (alta o anulación).

    Los registros forman una cadena por emisor (huella SHA-256 encadenada) y
    no pueden borrarse una vez encadenados (conservación legal).
    """

    _name = "l10n_es_verifacti.registro"
    _description = "Registro de facturación VeriFactu"
    _order = "chain_index desc, id desc"

    uuid = fields.Char(required=True, readonly=True, index=True, copy=False,
                       default=lambda self: uuid_lib.uuid4().hex)
    emisor_id = fields.Many2one("l10n_es_verifacti.emisor", required=True, readonly=True, index=True)
    tipo_registro = fields.Selection(
        [("alta", "Alta"), ("anulacion", "Anulación")], required=True, readonly=True, default="alta"
    )

    # Identificación de la factura
    serie = fields.Char(readonly=True)
    numero = fields.Char(required=True, readonly=True)
    num_serie = fields.Char(string="NumSerieFactura", required=True, readonly=True, index=True)
    fecha_expedicion = fields.Date(required=True, readonly=True)
    fecha_expedicion_str = fields.Char(string="Fecha expedición (DD-MM-YYYY)", required=True, readonly=True)
    tipo_factura = fields.Char(readonly=True)
    descripcion = fields.Char(readonly=True)
    importe_total = fields.Char(readonly=True)
    cuota_total = fields.Char(readonly=True)
    payload_json = fields.Text(string="Payload original", readonly=True)
    linea_ids = fields.One2many("l10n_es_verifacti.registro.linea", "registro_id", readonly=True)

    # Flags de subsanación / anulación
    subsanacion = fields.Char(readonly=True)
    rechazo_previo = fields.Char(readonly=True)
    sin_registro_previo = fields.Char(readonly=True)
    incidencia = fields.Char(readonly=True)
    anulada = fields.Boolean(
        readonly=True, help="El alta fue anulada posteriormente por un registro de anulación aceptado"
    )

    # Artefactos VeriFactu
    chain_index = fields.Integer(readonly=True, copy=False)
    huella = fields.Char(readonly=True, copy=False)
    huella_anterior = fields.Char(readonly=True, copy=False)
    fecha_hora_huso_gen = fields.Char(readonly=True, copy=False)
    qr_url = fields.Char(readonly=True, copy=False)
    qr_png = fields.Binary(string="QR", readonly=True, copy=False, attachment=False)
    xml_registro = fields.Text(string="XML del registro", readonly=True, copy=False)
    xml_soap_request = fields.Text(string="XML petición AEAT", readonly=True, copy=False)
    xml_soap_response = fields.Text(string="XML respuesta AEAT", readonly=True, copy=False)
    response_csv = fields.Char(string="CSV AEAT", readonly=True, copy=False)

    # Ciclo de vida
    state = fields.Selection(
        [
            ("pending", "Pendiente"),
            ("accepted", "Aceptado"),
            ("accepted_errors", "Aceptado con errores"),
            ("rejected", "Rechazado"),
            ("aeat_error", "Error servidor AEAT"),
        ],
        required=True,
        default="pending",
        readonly=True,
        index=True,
        copy=False,
    )
    error_code = fields.Char(readonly=True, copy=False)
    error_message = fields.Text(readonly=True, copy=False)
    retry_count = fields.Integer(readonly=True, copy=False)
    next_retry_time = fields.Datetime(readonly=True, copy=False)

    _sql_constraints = [
        ("uuid_uniq", "unique(uuid)", "UUID duplicado"),
    ]

    @api.ondelete(at_uninstall=False)
    def _never_unlink_chained(self):
        if any(registro.chain_index for registro in self):
            raise UserError(
                _("No se pueden eliminar registros de facturación encadenados (obligación de conservación).")
            )

    # ------------------------------------------------------------------
    # Helpers de estado (API Verifacti)
    # ------------------------------------------------------------------

    def _verifacti_estado(self):
        """Estado del registro en el enum de la API Verifacti."""
        self.ensure_one()
        if self.tipo_registro == "alta" and self.anulada and self.state in ("accepted", "accepted_errors"):
            return "Anulado"
        if self.tipo_registro == "anulacion" and self.state in ("accepted", "accepted_errors"):
            return "Anulado"
        return constants.ESTADO_VERIFACTI[self.state]

    def _to_status_response(self):
        """Shape del GET /verifactu/status de Verifacti (+ uuid extra)."""
        self.ensure_one()
        response = {
            "uuid": self.uuid,
            "nif": self.emisor_id.nif,
            "serie": self.serie or "",
            "numero": self.numero,
            "fecha_expedicion": self.fecha_expedicion_str,
            "operacion": "Alta" if self.tipo_registro == "alta" else "Anulacion",
            "estado": self._verifacti_estado(),
        }
        if self.qr_url:
            response["url"] = self.qr_url
        if self.qr_png:
            response["qr"] = self.qr_png.decode("ascii") if isinstance(self.qr_png, bytes) else self.qr_png
        if self.error_code:
            response["codigo_error"] = self.error_code
        if self.error_message:
            response["mensaje_error"] = self.error_message
        return response

    def _to_detail_response(self):
        """Shape del POST /verifactu/status de Verifacti (detalle del registro)."""
        self.ensure_one()
        payload = json.loads(self.payload_json or "{}")
        response = {
            "uuid": self.uuid,
            "nif_emisor": self.emisor_id.nif,
            "num_serie": self.num_serie,
            "fecha_expedicion": self.fecha_expedicion_str,
            "operacion": "Alta" if self.tipo_registro == "alta" else "Anulacion",
            "subsanacion": self.subsanacion or "N",
            "rechazo_previo": self.rechazo_previo or "N",
            "estado": self._verifacti_estado(),
        }
        if self.tipo_registro == "alta":
            response.update(
                {
                    "tipo_factura": self.tipo_factura,
                    "descripcion": self.descripcion,
                    "lineas": [
                        {
                            "base_imponible": linea.base_imponible,
                            "tipo_impositivo": linea.tipo_impositivo,
                            "cuota_repercutida": linea.cuota_repercutida,
                            "calificacion_operacion": linea.calificacion_operacion
                            or ("" if linea.operacion_exenta else "S1"),
                            "operacion_exenta": linea.operacion_exenta,
                            "clave_regimen": linea.clave_regimen or "01",
                        }
                        for linea in self.linea_ids
                    ],
                    "importe_total": self.importe_total,
                    "cuota_total": self.cuota_total,
                }
            )
            for linea in response["lineas"]:
                # No emitir claves vacías (mismo estilo que Verifacti)
                for clave in list(linea):
                    if not linea[clave]:
                        del linea[clave]
            if payload.get("nif"):
                response["nif_destinatario"] = payload["nif"]
            if payload.get("nombre"):
                response["nombre_destinatario"] = payload["nombre"]
            if payload.get("id_otro"):
                response["id_otro_destinatario"] = payload["id_otro"]
        previo = self.sudo().search(
            [("emisor_id", "=", self.emisor_id.id), ("chain_index", "=", self.chain_index - 1)],
            limit=1,
        )
        if previo:
            response["encadenamiento"] = {
                "nif_emisor": self.emisor_id.nif,
                "num_serie": previo.num_serie,
                "fecha_expedicion": previo.fecha_expedicion_str,
                "huella": previo.huella,
            }
        else:
            response["encadenamiento"] = {"primer_registro": "S"}
        response["huella"] = self.huella
        response["ultima_modificacion"] = (
            timezone("UTC").localize(self.write_date).astimezone(MADRID).isoformat(timespec="seconds")
        )
        if self.qr_url:
            response["url"] = self.qr_url
        if self.qr_png:
            response["qr"] = self.qr_png.decode("ascii") if isinstance(self.qr_png, bytes) else self.qr_png
        if self.error_code:
            response["codigo_error"] = self.error_code
        if self.error_message:
            response["mensaje_error"] = self.error_message
        return response

    def _to_create_response(self):
        self.ensure_one()
        qr_value = self.qr_png.decode("ascii") if isinstance(self.qr_png, bytes) else self.qr_png
        return {
            "uuid": self.uuid,
            "estado": self._verifacti_estado(),
            "url": self.qr_url,
            "huella": self.huella,
            "qr": qr_value,
        }

    # Estados femeninos (consulta AEAT / listado de Verifacti)
    ESTADO_SF = {
        "pending": "Pendiente",
        "accepted": "Correcta",
        "accepted_errors": "AceptadaConErrores",
        "rejected": "Incorrecta",
        "aeat_error": "Error servidor AEAT",
    }

    def _to_list_item(self):
        """Shape de los elementos de data[] del POST /verifactu/list de Verifacti."""
        self.ensure_one()
        item = self._to_detail_response()
        if (self.tipo_registro == "alta" and self.anulada) or (
            self.tipo_registro == "anulacion" and self.state in ("accepted", "accepted_errors")
        ):
            item["estado"] = "Anulada"
        else:
            item["estado"] = self.ESTADO_SF[self.state]
        item.pop("qr", None)
        return item

    # ------------------------------------------------------------------
    # Creación (pipeline bajo lock del emisor)
    # ------------------------------------------------------------------

    @api.model
    def _now_madrid(self):
        return datetime.now(MADRID)

    @api.model
    def _previous_identifier(self, emisor):
        """Datos del RegistroAnterior para el encadenamiento (o None)."""
        previo = emisor.last_registro_id
        if not previo:
            return None
        return {
            "IDEmisorFactura": emisor.nif,
            "NumSerieFactura": previo.num_serie,
            "FechaExpedicionFactura": previo.fecha_expedicion_str,
            "Huella": previo.huella,
        }

    @api.model
    def create_alta_from_payload(self, emisor, payload, subsanacion=None, rechazo_previo=None):
        """Crear un registro de alta desde un payload validado de la API.

        Debe llamarse dentro de la transacción con `emisor._lock()` tomado.
        Devuelve el dict de respuesta de la API (shape /verifactu/create).
        Lanza UserError con errores de negocio (duplicado, etc.).
        """
        num_serie = xml_builder.num_serie_factura(payload)
        if not subsanacion:
            duplicado = self.sudo().search_count(
                [
                    ("emisor_id", "=", emisor.id),
                    ("tipo_registro", "=", "alta"),
                    ("num_serie", "=", num_serie),
                    ("fecha_expedicion_str", "=", payload["fecha_expedicion"]),
                    ("state", "not in", ("rejected",)),
                ],
                limit=1,
            )
            if duplicado:
                raise UserError(
                    _("Ya existe un registro de alta para la factura %s con fecha %s",
                      num_serie, payload["fecha_expedicion"])
                )

        fecha_hora = self._now_madrid().isoformat(timespec="seconds")
        previo = self._previous_identifier(emisor)
        registro_uuid = uuid_lib.uuid4().hex

        registro_xml, huella_valor, cuota_total, importe_total = xml_builder.build_registro_alta(
            {
                "payload": payload,
                "emisor_nif": emisor.nif,
                "emisor_nombre": emisor.nombre_razon,
                "sistema_informatico": emisor._get_sistema_informatico(),
                "fecha_hora_huso_gen": fecha_hora,
                "previo": previo,
                "subsanacion": subsanacion,
                "rechazo_previo": rechazo_previo,
                "ref_externa": registro_uuid,
            }
        )

        xsd_errors = xml_builder.validate_registro_xsd(registro_xml)
        if xsd_errors:
            _logger.error("XML de alta inválido contra XSD: %s", xsd_errors)
            raise UserError(_("El registro generado no cumple el esquema AEAT:\n%s", "\n".join(xsd_errors)))

        url = qr.qr_url(emisor.entorno, emisor.nif, num_serie, payload["fecha_expedicion"], importe_total)
        qr_png = qr.qr_png_base64(url)

        chain_index = int(emisor._get_chain_sequence().next_by_id())
        registro = self.sudo().create(
            {
                "uuid": registro_uuid,
                "emisor_id": emisor.id,
                "tipo_registro": "alta",
                "serie": payload.get("serie") or "",
                "numero": payload["numero"],
                "num_serie": num_serie,
                "fecha_expedicion": datetime.strptime(payload["fecha_expedicion"], "%d-%m-%Y").date(),
                "fecha_expedicion_str": payload["fecha_expedicion"],
                "tipo_factura": payload["tipo_factura"],
                "descripcion": payload["descripcion"],
                "importe_total": importe_total,
                "cuota_total": cuota_total,
                "payload_json": json.dumps(payload, ensure_ascii=False),
                "subsanacion": subsanacion or "",
                "rechazo_previo": rechazo_previo or "",
                "incidencia": payload.get("incidencia") or "",
                "chain_index": chain_index,
                "huella": huella_valor,
                "huella_anterior": previo["Huella"] if previo else "",
                "fecha_hora_huso_gen": fecha_hora,
                "qr_url": url,
                "qr_png": qr_png.encode("ascii"),
                "xml_registro": etree.tostring(registro_xml, encoding="unicode"),
                "linea_ids": [
                    (0, 0, {
                        "base_imponible": str(linea.get("base_imponible", "")),
                        "impuesto": linea.get("impuesto") or "01",
                        "tipo_impositivo": str(linea.get("tipo_impositivo") or ""),
                        "cuota_repercutida": str(linea.get("cuota_repercutida") or ""),
                        "calificacion_operacion": linea.get("calificacion_operacion") or "",
                        "operacion_exenta": linea.get("operacion_exenta") or "",
                        "clave_regimen": linea.get("clave_regimen") or "",
                    })
                    for linea in payload["lineas"]
                ],
            }
        )
        emisor.sudo().last_registro_id = registro
        self._trigger_send_cron()
        return registro._to_create_response()

    @api.model
    def create_anulacion_from_payload(self, emisor, payload):
        """Crear un registro de anulación (POST /verifactu/cancel)."""
        num_serie = xml_builder.num_serie_factura(payload)

        # Verifacti acepta anular facturas registradas fuera de este sistema:
        # no se exige alta previa (la AEAT validará el registro de anulación).
        fecha_hora = self._now_madrid().isoformat(timespec="seconds")
        previo = self._previous_identifier(emisor)
        registro_uuid = uuid_lib.uuid4().hex

        registro_xml, huella_valor = xml_builder.build_registro_anulacion(
            {
                "payload": payload,
                "emisor_nif": emisor.nif,
                "sistema_informatico": emisor._get_sistema_informatico(),
                "fecha_hora_huso_gen": fecha_hora,
                "previo": previo,
                "ref_externa": registro_uuid,
            }
        )

        xsd_errors = xml_builder.validate_registro_xsd(registro_xml)
        if xsd_errors:
            _logger.error("XML de anulación inválido contra XSD: %s", xsd_errors)
            raise UserError(_("El registro generado no cumple el esquema AEAT:\n%s", "\n".join(xsd_errors)))

        chain_index = int(emisor._get_chain_sequence().next_by_id())
        registro = self.sudo().create(
            {
                "uuid": registro_uuid,
                "emisor_id": emisor.id,
                "tipo_registro": "anulacion",
                "serie": payload.get("serie") or "",
                "numero": payload["numero"],
                "num_serie": num_serie,
                "fecha_expedicion": datetime.strptime(payload["fecha_expedicion"], "%d-%m-%Y").date(),
                "fecha_expedicion_str": payload["fecha_expedicion"],
                "payload_json": json.dumps(payload, ensure_ascii=False),
                "rechazo_previo": payload.get("rechazo_previo") or "N",
                "sin_registro_previo": payload.get("sin_registro_previo") or "N",
                "incidencia": payload.get("incidencia") or "",
                "chain_index": chain_index,
                "huella": huella_valor,
                "huella_anterior": previo["Huella"] if previo else "",
                "fecha_hora_huso_gen": fecha_hora,
                "xml_registro": etree.tostring(registro_xml, encoding="unicode"),
            }
        )
        emisor.sudo().last_registro_id = registro
        self._trigger_send_cron()
        return {
            "uuid": registro.uuid,
            "estado": registro._verifacti_estado(),
            "huella": registro.huella,
        }

    # ------------------------------------------------------------------
    # Envío asíncrono a la AEAT
    # ------------------------------------------------------------------

    @api.model
    def _trigger_send_cron(self):
        cron = self.env.ref("l10n_es_api_verifacti.ir_cron_send_pending", raise_if_not_found=False)
        if cron:
            cron.sudo()._trigger()

    @api.model
    def _cron_send_pending(self):
        """Enviar a la AEAT los registros pendientes, por emisor y en orden de cadena."""
        now = fields.Datetime.now()
        domain = [
            ("state", "in", ("pending", "aeat_error")),
            "|", ("next_retry_time", "=", False), ("next_retry_time", "<=", now),
        ]
        grupos = self.sudo()._read_group(domain, groupby=["emisor_id"], aggregates=["id:recordset"])

        next_trigger = None
        for emisor, registros in grupos:
            if not emisor.active:
                continue
            if not emisor.certificate_id:
                _logger.warning("Emisor %s sin certificado: no se envía a la AEAT", emisor.nif)
                continue
            if emisor.next_batch_time and now < emisor.next_batch_time:
                next_trigger = min(next_trigger or datetime.max, emisor.next_batch_time)
                continue
            try:
                # Serializar con los create de la API (misma fila de emisor):
                # sin este lock, un create concurrente provoca un
                # SerializationFailure al escribir next_batch_time DESPUÉS de
                # haber enviado el sobre → rollback → reenvío → error AEAT 3000.
                emisor._lock()
                self._send_batch_for_emisor(emisor, registros.sorted("chain_index")[: constants.BATCH_LIMIT])
            except Exception:
                _logger.exception("Error enviando lote VeriFactu del emisor %s", emisor.nif)
            if not self.env.registry.in_test_mode():
                self.env.cr.commit()

        # Reprogramar si quedó algo pendiente por tiempo de espera
        pendientes = self.sudo().search_count([("state", "in", ("pending", "aeat_error"))], limit=1)
        if pendientes:
            cron = self.env.ref("l10n_es_api_verifacti.ir_cron_send_pending", raise_if_not_found=False)
            if cron:
                cron.sudo()._trigger(at=next_trigger or (now + timedelta(seconds=60)))

    @api.model
    def _send_batch_for_emisor(self, emisor, registros):
        if not registros:
            return

        # Error AEAT 2004: si algún registro se envía >240s tras su generación,
        # se declara incidencia para que quede aceptado (con error no fatal).
        limite = fields.Datetime.now() - timedelta(seconds=INCIDENT_SECONDS)
        incidencia = any(
            registro.create_date < limite or registro.incidencia == "S" for registro in registros
        )

        registros_xml = [etree.fromstring(registro.xml_registro.encode("utf-8")) for registro in registros]
        envelope = xml_builder.build_envelope(
            {"nombre_razon": emisor.nombre_razon, "nif": emisor.nif},
            registros_xml,
            incidencia=incidencia,
        )
        registros.write({"xml_soap_request": envelope.decode("utf-8")})

        info = soap_client.send_envelope(emisor.certificate_id.sudo(), envelope, emisor.entorno)

        if info["raw_response"]:
            registros.write({"xml_soap_response": info["raw_response"]})

        if not info["ok"]:
            self._apply_batch_failure(registros, info)
            return

        if info["csv"]:
            registros.write({"response_csv": info["csv"]})

        for registro in registros:
            linea_info = info["lineas"].get(registro.num_serie)
            if not linea_info:
                registro.write(
                    {
                        "state": "aeat_error",
                        "error_message": _("La respuesta de la AEAT no contiene información del registro"),
                    }
                )
                continue
            self._apply_line_result(registro, linea_info)

        if info["waiting_time_seconds"]:
            emisor.sudo().next_batch_time = fields.Datetime.now() + timedelta(
                seconds=info["waiting_time_seconds"]
            )

    @api.model
    def _apply_batch_failure(self, registros, info):
        """Fallo a nivel de lote (red, fault, 5xx)."""
        error = "\n".join(info["errors"])
        if info["retryable"]:
            for registro in registros:
                retry_count = registro.retry_count + 1
                backoff = min(RETRY_BACKOFF_MIN * (2 ** min(retry_count, 5)), RETRY_BACKOFF_MAX)
                registro.write(
                    {
                        "state": "aeat_error",
                        "error_message": error,
                        "retry_count": retry_count,
                        "next_retry_time": fields.Datetime.now() + timedelta(seconds=backoff),
                    }
                )
                if retry_count >= RETRY_ALERT_COUNT:
                    _logger.error(
                        "Registro VeriFactu %s lleva %s reintentos fallidos", registro.uuid, retry_count
                    )
        else:
            registros.write({"state": "rejected", "error_message": error})

    @api.model
    def _apply_line_result(self, registro, linea_info):
        state = linea_info["state"]
        duplicate = linea_info.get("duplicate")

        # Recuperación tras timeout: el registro llegó a la AEAT y ahora
        # responde "rechazado por duplicado"; tomamos el estado del original.
        if state == "rejected" and duplicate and registro.error_message \
                and "[Read-Timeout]" in registro.error_message:
            if registro.tipo_registro == "alta" and duplicate["state"] in ("accepted", "accepted_errors"):
                state = duplicate["state"]
                linea_info = dict(
                    linea_info, error_code=duplicate["error_code"], error_message=duplicate["error_message"]
                )
            elif registro.tipo_registro == "anulacion" and duplicate["state"] == "cancelled":
                state = "accepted"
                linea_info = dict(
                    linea_info, error_code=duplicate["error_code"], error_message=duplicate["error_message"]
                )

        if not state:
            state = "aeat_error"

        registro.write(
            {
                "state": state,
                "error_code": linea_info.get("error_code") or "",
                "error_message": linea_info.get("error_message") or "",
                "next_retry_time": False,
            }
        )

        # Una anulación aceptada marca el alta correspondiente como anulada
        if registro.tipo_registro == "anulacion" and state in ("accepted", "accepted_errors"):
            altas = self.sudo().search(
                [
                    ("emisor_id", "=", registro.emisor_id.id),
                    ("tipo_registro", "=", "alta"),
                    ("num_serie", "=", registro.num_serie),
                    ("fecha_expedicion_str", "=", registro.fecha_expedicion_str),
                ]
            )
            altas.write({"anulada": True})


class VerifactiRegistroLinea(models.Model):
    _name = "l10n_es_verifacti.registro.linea"
    _description = "Línea de registro VeriFactu"

    registro_id = fields.Many2one(
        "l10n_es_verifacti.registro", required=True, readonly=True, ondelete="cascade", index=True
    )
    base_imponible = fields.Char(readonly=True)
    impuesto = fields.Char(readonly=True)
    tipo_impositivo = fields.Char(readonly=True)
    cuota_repercutida = fields.Char(readonly=True)
    calificacion_operacion = fields.Char(readonly=True)
    operacion_exenta = fields.Char(readonly=True)
    clave_regimen = fields.Char(readonly=True)
