# -*- coding: utf-8 -*-
"""API REST compatible con Verifacti (https://www.verifacti.com) en /verifactu/*.

Todas las rutas son type='http' (auth por Bearer, códigos de estado HTTP y
cuerpos JSON con el mismo shape que Verifacti: errores {mensaje, detalles,
errores}).
"""

import functools
import json
import logging
import time
from datetime import datetime

from pytz import timezone

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request
from psycopg2 import OperationalError, errorcodes

# Códigos pgcode reintentables (equivalentes a los de odoo.service.model,
# pero usando la API pública y estable de psycopg2 en vez de un símbolo
# interno de Odoo que no existe igual en todas las versiones)
PG_RETRYABLE_PGCODES = (
    errorcodes.LOCK_NOT_AVAILABLE,
    errorcodes.SERIALIZATION_FAILURE,
    errorcodes.DEADLOCK_DETECTED,
)

from ..verifactu import constants, validation, xml_builder

_logger = logging.getLogger(__name__)

MADRID = timezone("Europe/Madrid")

DECLARACION_RESPONSABLE_URL = (
    "https://oak-soft-public.s3.eu-west-1.amazonaws.com/declaracion/1.0.0.pdf"
)


class ApiError(Exception):
    def __init__(self, status, mensaje, detalles=None, errores=None):
        super().__init__(mensaje)
        self.status = status
        self.mensaje = mensaje
        self.detalles = detalles
        self.errores = errores


def _json_response(payload, status=200):
    return request.make_json_response(payload, status=status)


def _error_body(mensaje, detalles=None, errores=None):
    # "error" es la clave que usa Verifacti SaaS; "mensaje" se mantiene por
    # compatibilidad con clientes existentes.
    body = {"error": mensaje, "mensaje": mensaje}
    if detalles:
        body["detalles"] = detalles
    if errores:
        body["errores"] = errores
    return body


def _get_bearer_key():
    auth = request.httprequest.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    return auth[len("Bearer "):].strip()


def _authenticate():
    api_key = _get_bearer_key()
    emisor = request.env["l10n_es_verifacti.emisor"].sudo()._find_by_api_key(api_key)
    if not emisor:
        raise ApiError(401, "API key inválida")
    return emisor


def _parse_json_body():
    try:
        return json.loads(request.httprequest.get_data(as_text=True) or "null")
    except (ValueError, UnicodeDecodeError):
        raise ApiError(400, "JSON inválido")


def _validation_error(errores):
    detalles = {error["campo"]: error["mensaje"] for error in errores}
    return ApiError(400, "Errores de validación", detalles=detalles, errores=errores)


def _hoy_madrid():
    return datetime.now(MADRID).date()


def verifactu_endpoint(func):
    """Auth + manejo de errores + log de la petición."""

    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        start = time.time()
        emisor = None
        api_key = _get_bearer_key()
        status = 200
        response_payload = None
        try:
            emisor = _authenticate()
            response_payload = func(self, emisor, *args, **kwargs)
            if isinstance(response_payload, tuple):
                response_payload, status = response_payload
            return _json_response(response_payload, status=status)
        except ApiError as error:
            status = error.status
            response_payload = _error_body(error.mensaje, error.detalles, error.errores)
            if status == 401:
                # Verifacti SaaS responde {"message": "Unauthorized"}
                response_payload["message"] = "Unauthorized"
            return _json_response(response_payload, status=status)
        except UserError as error:
            status = 400
            response_payload = _error_body(str(error))
            return _json_response(response_payload, status=status)
        except Exception as error:
            if isinstance(error, OperationalError) and getattr(error, "pgcode", None) in PG_RETRYABLE_PGCODES:
                # Dejar que el dispatcher de Odoo reintente la petición completa
                # (SerializationFailure/deadlock por concurrencia con el cron).
                raise
            _logger.exception("Error inesperado en %s", request.httprequest.path)
            status = 500
            response_payload = _error_body("Error interno del servidor")
            return _json_response(response_payload, status=status)
        finally:
            request.env["l10n_es_verifacti.request.log"].sudo().log_request(
                endpoint=request.httprequest.path,
                method=request.httprequest.method,
                emisor=emisor,
                api_key=api_key,
                remote_addr=request.httprequest.remote_addr,
                status_code=status,
                request_body=request.httprequest.get_data(as_text=True),
                response_body=json.dumps(response_payload, ensure_ascii=False)
                if response_payload is not None
                else "",
                duration_ms=(time.time() - start) * 1000.0,
            )

    return wrapper


class VerifactuController(http.Controller):

    # ------------------------------------------------------------------
    # Salud y declaración
    # ------------------------------------------------------------------

    @http.route("/verifactu/health", type="http", auth="public", csrf=False, methods=["GET"])
    @verifactu_endpoint
    def health(self, emisor):
        return {
            "estado": "OK",
            "nif": emisor.nif,
            "entorno": emisor.entorno,
            "hacienda": "verifactu",
        }

    @http.route("/verifactu/declaracion_responsable", type="http", auth="public", csrf=False, methods=["GET"])
    def declaracion_responsable(self):
        return request.redirect(DECLARACION_RESPONSABLE_URL, code=302, local=False)

    # ------------------------------------------------------------------
    # Creación / modificación / anulación
    # ------------------------------------------------------------------

    def _create_one(self, emisor, payload, subsanacion=None, rechazo_previo=None, check_fecha=True):
        hoy = _hoy_madrid() if check_fecha else None
        if subsanacion:
            errores = validation.validate_modify(payload)
        else:
            errores = validation.validate_create(payload, hoy=hoy)
        if errores:
            raise _validation_error(errores)
        emisor._lock()
        Registro = request.env["l10n_es_verifacti.registro"].sudo()
        if subsanacion and rechazo_previo != "X":
            # Como Verifacti: subsanar con N exige un registro ya aceptado por
            # la AEAT; con S, uno rechazado. X (sin registro previo) no exige.
            estados = ("rejected",) if rechazo_previo == "S" else ("accepted", "accepted_errors")
            existe = Registro.search_count(
                [
                    ("emisor_id", "=", emisor.id),
                    ("tipo_registro", "=", "alta"),
                    ("num_serie", "=", xml_builder.num_serie_factura(payload)),
                    ("fecha_expedicion_str", "=", payload["fecha_expedicion"]),
                    ("state", "in", estados),
                ],
                limit=1,
            )
            if not existe:
                raise ApiError(400, "No existe el registro de facturacion.")
        return Registro.create_alta_from_payload(
            emisor, payload, subsanacion=subsanacion, rechazo_previo=rechazo_previo
        )

    @http.route("/verifactu/create", type="http", auth="public", csrf=False, methods=["POST"])
    @verifactu_endpoint
    def create(self, emisor):
        payload = _parse_json_body()
        return self._create_one(emisor, payload)

    @http.route("/verifactu/create_bulk", type="http", auth="public", csrf=False, methods=["POST"])
    @verifactu_endpoint
    def create_bulk(self, emisor):
        payloads = _parse_json_body()
        if not isinstance(payloads, list):
            raise ApiError(400, "El cuerpo debe ser una lista de facturas")
        if len(payloads) > constants.MAX_BULK:
            raise ApiError(400, f"Máximo {constants.MAX_BULK} facturas por lote")

        resultados = []
        for payload in payloads:
            try:
                resultados.append(self._create_one(emisor, payload))
            except ApiError as error:
                resultados.append(_error_body(error.mensaje, error.detalles, error.errores))
            except UserError as error:
                resultados.append(_error_body(str(error)))
        return resultados

    @http.route("/verifactu/modify", type="http", auth="public", csrf=False, methods=["PUT"])
    @verifactu_endpoint
    def modify(self, emisor):
        payload = _parse_json_body()
        rechazo_previo = (payload or {}).get("rechazo_previo", "N") if isinstance(payload, dict) else "N"
        return self._create_one(
            emisor, payload, subsanacion="S", rechazo_previo=rechazo_previo, check_fecha=False
        )

    @http.route("/verifactu/cancel", type="http", auth="public", csrf=False, methods=["POST"])
    @verifactu_endpoint
    def cancel(self, emisor):
        payload = _parse_json_body()
        errores = validation.validate_cancel(payload)
        if errores:
            raise _validation_error(errores)
        emisor._lock()
        Registro = request.env["l10n_es_verifacti.registro"].sudo()
        return Registro.create_anulacion_from_payload(emisor, payload)

    # ------------------------------------------------------------------
    # Consulta de estado
    # ------------------------------------------------------------------

    @http.route("/verifactu/status", type="http", auth="public", csrf=False, methods=["GET"])
    @verifactu_endpoint
    def status_get(self, emisor, uuid=None, **kwargs):
        if not uuid:
            raise ApiError(400, "Falta el parámetro uuid")
        registro = request.env["l10n_es_verifacti.registro"].sudo().search(
            [("uuid", "=", uuid), ("emisor_id", "=", emisor.id)], limit=1
        )
        if not registro:
            raise ApiError(404, "Registro no encontrado")
        return registro._to_status_response()

    @http.route("/verifactu/status", type="http", auth="public", csrf=False, methods=["POST"])
    @verifactu_endpoint
    def status_post(self, emisor):
        payload = _parse_json_body()
        # Como Verifacti: serie es opcional (vacía por defecto), numero y
        # fecha_expedicion son obligatorios.
        if (
            not isinstance(payload, dict)
            or not payload.get("numero")
            or not validation._parse_fecha(payload.get("fecha_expedicion"))
        ):
            raise ApiError(400, "serie, numero y fecha_expedicion son requeridos")

        num_serie = f"{payload.get('serie') or ''}{payload['numero']}"
        Registro = request.env["l10n_es_verifacti.registro"].sudo()
        domain = [
            ("emisor_id", "=", emisor.id),
            ("num_serie", "=", num_serie),
            ("fecha_expedicion_str", "=", payload["fecha_expedicion"]),
        ]
        # El detalle se da sobre el alta (como Verifacti); la anulación queda
        # reflejada en su estado ("Anulado").
        registro = Registro.search(
            domain + [("tipo_registro", "=", "alta")], order="chain_index desc", limit=1
        ) or Registro.search(domain, order="chain_index desc", limit=1)
        if not registro:
            return {"mensaje": "Factura no encontrada"}
        return registro._to_detail_response()

    # ------------------------------------------------------------------
    # Listado / exportación / descarga de XML
    # ------------------------------------------------------------------

    def _registros_periodo(self, emisor, payload):
        """Dominio del periodo, o None si ejercicio/periodo no casan con nada
        (Verifacti responde {"data": []} en ese caso)."""
        if not payload.get("ejercicio") or not payload.get("periodo"):
            raise ApiError(400, "ejercicio y periodo son requeridos")
        try:
            ejercicio = int(payload.get("ejercicio"))
            periodo = int(payload.get("periodo"))
            if not 1 <= periodo <= 12:
                raise ValueError
        except (TypeError, ValueError):
            return None

        domain = [
            ("emisor_id", "=", emisor.id),
            ("fecha_expedicion", ">=", f"{ejercicio}-{periodo:02d}-01"),
            ("fecha_expedicion", "<", f"{ejercicio + (periodo == 12)}-{(periodo % 12) + 1:02d}-01"),
        ]
        if payload.get("serie") or payload.get("numero"):
            num_serie = f"{payload.get('serie') or ''}{payload.get('numero') or ''}"
            domain.append(("num_serie", "=like", f"{num_serie}%"))
        if payload.get("fecha_expedicion"):
            domain.append(("fecha_expedicion_str", "=", payload["fecha_expedicion"]))
        rango = payload.get("rango_fecha_expedicion")
        if isinstance(rango, dict):
            for clave, operador in (("desde", ">="), ("hasta", "<=")):
                fecha = validation._parse_fecha(rango.get(clave)) if rango.get(clave) else None
                if fecha:
                    domain.append(("fecha_expedicion", operador, fecha))
        return domain

    @http.route("/verifactu/list", type="http", auth="public", csrf=False, methods=["POST"])
    @verifactu_endpoint
    def list_registros(self, emisor):
        payload = _parse_json_body()
        if not isinstance(payload, dict):
            raise ApiError(400, "El cuerpo debe ser un objeto JSON")
        domain = self._registros_periodo(emisor, payload)
        if domain is None:
            return {"data": []}

        paginacion = payload.get("paginacion") or {}
        pagina = max(1, int(paginacion.get("pagina", 1) or 1))
        por_pagina = min(100, max(1, int(paginacion.get("resultados_por_pagina", 50) or 50)))

        Registro = request.env["l10n_es_verifacti.registro"].sudo()
        total = Registro.search_count(domain)
        offset = (pagina - 1) * por_pagina
        registros = Registro.search(
            domain, order="chain_index asc", limit=por_pagina, offset=offset
        )
        # Shape de Verifacti: {"paginacion": "S"|"N" (si quedan más páginas),
        # "data": [detalle de cada registro]}
        return {
            "paginacion": "S" if offset + len(registros) < total else "N",
            "data": [registro._to_list_item() for registro in registros],
        }

    @http.route("/verifactu/export", type="http", auth="public", csrf=False, methods=["POST"])
    @verifactu_endpoint
    def export_xmls(self, emisor):
        payload = _parse_json_body()
        if not isinstance(payload, dict):
            raise ApiError(400, "El cuerpo debe ser un objeto JSON")
        domain = self._registros_periodo(emisor, payload)
        if domain is None:
            return {"total": 0, "xmls": []}

        lote = 100
        try:
            offset = int(payload.get("token") or 0)
        except ValueError:
            raise ApiError(400, "token inválido")

        Registro = request.env["l10n_es_verifacti.registro"].sudo()
        total = Registro.search_count(domain)
        registros = Registro.search(domain, order="chain_index asc", limit=lote, offset=offset)
        respuesta = {
            "total": total,
            "xmls": [
                {
                    "uuid": registro.uuid,
                    "serie": registro.serie,
                    "numero": registro.numero,
                    "xml_req": registro.xml_soap_request or registro.xml_registro or "",
                    "xml_res": registro.xml_soap_response or "",
                }
                for registro in registros
            ],
        }
        if offset + len(registros) < total:
            respuesta["token"] = str(offset + len(registros))
        return respuesta

    @http.route("/verifactu/downloadXML", type="http", auth="public", csrf=False, methods=["POST"])
    @verifactu_endpoint
    def download_xml(self, emisor):
        payload = _parse_json_body()
        if not isinstance(payload, dict) or not payload.get("numero"):
            raise ApiError(400, "serie y numero son obligatorios")

        num_serie = f"{payload.get('serie') or ''}{payload['numero']}"
        registros = request.env["l10n_es_verifacti.registro"].sudo().search(
            [("emisor_id", "=", emisor.id), ("num_serie", "=", num_serie)],
            order="chain_index asc",
        )
        # Verifacti devuelve una lista con todos los registros de la factura
        # (vacía si no hay ninguno)
        return [
            {
                "uuid": registro.uuid,
                "operacion": "Alta" if registro.tipo_registro == "alta" else "Anulacion",
                "xml_req": registro.xml_soap_request or registro.xml_registro or "",
                "xml_res": registro.xml_soap_response or "",
            }
            for registro in registros
        ]
