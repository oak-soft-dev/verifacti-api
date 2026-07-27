# -*- coding: utf-8 -*-
"""Cliente SOAP mTLS para el servicio VeriFactu de la AEAT.

Envía el sobre RegFactuSistemaFacturacion con certificado de cliente
(PKCS#12 gestionado por el addon `certificate` de Odoo, adaptador mTLS en
memoria) y parsea la respuesta a un dict normalizado.
"""

import logging

import requests
from lxml import etree

from odoo.addons.certificate.tools import CertificateAdapter

from . import constants

_logger = logging.getLogger(__name__)

# Evitar fallo en servidores con clave DH pequeña (mismo ajuste que el módulo
# oficial l10n_es_edi_verifactu)
CIPHERS = "DEFAULT:!DH"

TIMEOUT = 30

# EstadoRegistroType -> estado interno del registro
STATE_MAP = {
    "Correcto": "accepted",
    "AceptadoConErrores": "accepted_errors",
    "Incorrecto": "rejected",
}
# EstadoRegistroSFType (registro duplicado)
DUPLICATE_STATE_MAP = {
    "Correcta": "accepted",
    "AceptadaConErrores": "accepted_errors",
    "Anulada": "cancelled",
}


def _text(element, tag):
    child = element.find(f"{{{constants.NS_RESPUESTA}}}{tag}")
    if child is None:
        child = element.find(f"{{{constants.NS_SUM_INFO}}}{tag}")
    return child.text if child is not None else None


def send_envelope(certificate, envelope_bytes, entorno):
    """Enviar el sobre SOAP a la AEAT.

    :param certificate: record certificate.certificate (con clave privada)
    :param bytes envelope_bytes: sobre SOAP serializado
    :param str entorno: 'test' | 'produccion'
    :return: dict {
        ok: bool,
        retryable: bool,           # error de red/servidor, reintentable
        errors: [str],
        raw_response: str,
        csv: str|None,
        waiting_time_seconds: int|None,
        estado_envio: str|None,    # Correcto|ParcialmenteCorrecto|Incorrecto
        lineas: {num_serie: {state, cancellation, error_code, error_message, duplicate}},
    }
    """
    url = constants.ENDPOINTS[entorno]["verifactu"]
    info = {
        "ok": False,
        "retryable": False,
        "errors": [],
        "raw_response": "",
        "csv": None,
        "waiting_time_seconds": None,
        "estado_envio": None,
        "lineas": {},
    }

    session = requests.Session()
    session.mount("https://", CertificateAdapter(ciphers=CIPHERS))
    session.cert = certificate

    try:
        response = session.post(
            url,
            data=envelope_bytes,
            headers={"Content-Type": "text/xml;charset=UTF-8", "SOAPAction": ""},
            timeout=TIMEOUT,
        )
    except requests.exceptions.SSLError as error:
        info["errors"].append(f"Error SSL/certificado: {error}")
        info["retryable"] = False
        return info
    except requests.exceptions.ReadTimeout as error:
        # El registro puede haber llegado a la AEAT: el reintento resolverá
        # vía la información de duplicado de la respuesta.
        info["errors"].append(f"[Read-Timeout] Timeout esperando respuesta de la AEAT: {error}")
        info["retryable"] = True
        return info
    except requests.exceptions.RequestException as error:
        info["errors"].append(f"Error de red enviando a la AEAT: {error}")
        info["retryable"] = True
        return info

    info["raw_response"] = response.text

    if response.status_code >= 500:
        info["errors"].append(f"Error del servidor AEAT (HTTP {response.status_code})")
        info["retryable"] = True
        return info

    if response.text.lstrip().lower().startswith(("<!doctype", "<html")):
        info["errors"].append(
            "La AEAT respondió HTML en lugar de XML (problema probable de certificado/autorización)"
        )
        info["retryable"] = False
        return info

    try:
        root = etree.fromstring(response.content)
    except etree.XMLSyntaxError:
        info["errors"].append("Respuesta de la AEAT no parseable como XML")
        info["retryable"] = True
        return info

    # SOAP Fault
    fault = root.find(f".//{{{constants.NS_SOAP}}}Fault")
    if fault is not None:
        code = fault.findtext("faultcode") or ""
        message = fault.findtext("faultstring") or etree.tostring(fault, encoding="unicode")
        info["errors"].append(f"SOAP Fault [{code}] {message}")
        # Los faults de infraestructura son reintentables; los de validación no.
        info["retryable"] = "env:Server" in code or "soapenv:Server" in code
        return info

    respuesta = root.find(f".//{{{constants.NS_RESPUESTA}}}RespuestaRegFactuSistemaFacturacion")
    if respuesta is None:
        info["errors"].append("Respuesta AEAT sin RespuestaRegFactuSistemaFacturacion")
        info["retryable"] = True
        return info

    info["ok"] = True
    info["csv"] = _text(respuesta, "CSV")
    info["estado_envio"] = _text(respuesta, "EstadoEnvio")
    waiting = _text(respuesta, "TiempoEsperaEnvio")
    info["waiting_time_seconds"] = int(waiting) if waiting else None

    for linea in respuesta.findall(f"{{{constants.NS_RESPUESTA}}}RespuestaLinea"):
        id_factura = linea.find(f"{{{constants.NS_RESPUESTA}}}IDFactura")
        num_serie = (_text(id_factura, "NumSerieFactura") or "").strip()

        operacion = linea.find(f"{{{constants.NS_RESPUESTA}}}Operacion")
        tipo_operacion = _text(operacion, "TipoOperacion") if operacion is not None else None

        estado = _text(linea, "EstadoRegistro")
        linea_info = {
            "state": STATE_MAP.get(estado),
            "cancellation": tipo_operacion == "Anulacion",
            "error_code": _text(linea, "CodigoErrorRegistro"),
            "error_message": _text(linea, "DescripcionErrorRegistro"),
            "duplicate": None,
        }

        duplicado = linea.find(f"{{{constants.NS_RESPUESTA}}}RegistroDuplicado")
        if duplicado is None:
            duplicado = linea.find(f"{{{constants.NS_SUM_INFO}}}RegistroDuplicado")
        if duplicado is not None:
            linea_info["duplicate"] = {
                "state": DUPLICATE_STATE_MAP.get(_text(duplicado, "EstadoRegistroDuplicado")),
                "error_code": _text(duplicado, "CodigoErrorRegistro"),
                "error_message": _text(duplicado, "DescripcionErrorRegistro"),
            }

        info["lineas"][num_serie] = linea_info

    return info
