# -*- coding: utf-8 -*-

from unittest.mock import patch

import requests

from odoo.tests import TransactionCase, tagged

from ..verifactu import constants, soap_client


def _soap_response(body_inner):
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<env:Envelope xmlns:env="{constants.NS_SOAP}">'
        f"<env:Body>{body_inner}</env:Body>"
        "</env:Envelope>"
    )


def _respuesta(estado_envio, lineas_xml, csv="A-TESTCSV123", tiempo="60"):
    csv_xml = f"<sfR:CSV>{csv}</sfR:CSV>" if csv else ""
    return _soap_response(
        f'<sfR:RespuestaRegFactuSistemaFacturacion xmlns:sfR="{constants.NS_RESPUESTA}" '
        f'xmlns:sf="{constants.NS_SUM_INFO}">'
        f"{csv_xml}"
        "<sfR:Cabecera><sf:ObligadoEmision>"
        "<sf:NombreRazon>Emisor pruebas</sf:NombreRazon><sf:NIF>A39200019</sf:NIF>"
        "</sf:ObligadoEmision></sfR:Cabecera>"
        f"<sfR:TiempoEsperaEnvio>{tiempo}</sfR:TiempoEsperaEnvio>"
        f"<sfR:EstadoEnvio>{estado_envio}</sfR:EstadoEnvio>"
        f"{lineas_xml}"
        "</sfR:RespuestaRegFactuSistemaFacturacion>"
    )


def _linea(num_serie, estado, tipo_operacion="Alta", error_code=None, error_message=None, duplicado=None):
    error_xml = ""
    if error_code:
        error_xml = (
            f"<sfR:CodigoErrorRegistro>{error_code}</sfR:CodigoErrorRegistro>"
            f"<sfR:DescripcionErrorRegistro>{error_message or ''}</sfR:DescripcionErrorRegistro>"
        )
    duplicado_xml = ""
    if duplicado:
        duplicado_xml = (
            "<sfR:RegistroDuplicado>"
            f"<sfR:EstadoRegistroDuplicado>{duplicado}</sfR:EstadoRegistroDuplicado>"
            "</sfR:RegistroDuplicado>"
        )
    return (
        "<sfR:RespuestaLinea>"
        "<sfR:IDFactura>"
        "<sf:IDEmisorFactura>A39200019</sf:IDEmisorFactura>"
        f"<sf:NumSerieFactura>{num_serie}</sf:NumSerieFactura>"
        "<sf:FechaExpedicionFactura>03-07-2026</sf:FechaExpedicionFactura>"
        "</sfR:IDFactura>"
        "<sfR:Operacion>"
        f"<sf:TipoOperacion>{tipo_operacion}</sf:TipoOperacion>"
        "</sfR:Operacion>"
        f"<sfR:EstadoRegistro>{estado}</sfR:EstadoRegistro>"
        f"{error_xml}{duplicado_xml}"
        "</sfR:RespuestaLinea>"
    )


class FakeResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.content = text.encode("utf-8")
        self.status_code = status_code


def _send(response=None, exception=None):
    def fake_post(self, url, **kwargs):
        if exception:
            raise exception
        return response

    with patch.object(requests.Session, "post", fake_post):
        return soap_client.send_envelope(None, b"<envelope/>", "test")


@tagged("post_install", "-at_install")
class TestSoapClient(TransactionCase):
    def test_aceptado(self):
        response = FakeResponse(_respuesta("Correcto", _linea("TEST1", "Correcto")))
        info = _send(response=response)
        self.assertTrue(info["ok"])
        self.assertEqual(info["csv"], "A-TESTCSV123")
        self.assertEqual(info["estado_envio"], "Correcto")
        self.assertEqual(info["waiting_time_seconds"], 60)
        self.assertEqual(info["lineas"]["TEST1"]["state"], "accepted")
        self.assertFalse(info["lineas"]["TEST1"]["cancellation"])

    def test_rechazado(self):
        response = FakeResponse(
            _respuesta(
                "Incorrecto",
                _linea("TEST1", "Incorrecto", error_code="1117", error_message="Error de calculo"),
                csv=None,
            )
        )
        info = _send(response=response)
        self.assertTrue(info["ok"])
        self.assertIsNone(info["csv"])
        linea = info["lineas"]["TEST1"]
        self.assertEqual(linea["state"], "rejected")
        self.assertEqual(linea["error_code"], "1117")
        self.assertEqual(linea["error_message"], "Error de calculo")

    def test_aceptado_con_errores(self):
        response = FakeResponse(
            _respuesta(
                "ParcialmenteCorrecto",
                _linea("TEST1", "AceptadoConErrores", error_code="2004", error_message="Fuera de plazo"),
            )
        )
        info = _send(response=response)
        self.assertEqual(info["lineas"]["TEST1"]["state"], "accepted_errors")
        self.assertEqual(info["lineas"]["TEST1"]["error_code"], "2004")

    def test_anulacion_aceptada(self):
        response = FakeResponse(
            _respuesta("Correcto", _linea("TEST1", "Correcto", tipo_operacion="Anulacion"))
        )
        info = _send(response=response)
        self.assertTrue(info["lineas"]["TEST1"]["cancellation"])
        self.assertEqual(info["lineas"]["TEST1"]["state"], "accepted")

    def test_duplicado(self):
        response = FakeResponse(
            _respuesta(
                "Incorrecto",
                _linea("TEST1", "Incorrecto", error_code="3000", duplicado="Correcta"),
                csv=None,
            )
        )
        info = _send(response=response)
        linea = info["lineas"]["TEST1"]
        self.assertEqual(linea["state"], "rejected")
        self.assertEqual(linea["duplicate"]["state"], "accepted")

    def test_varias_lineas(self):
        response = FakeResponse(
            _respuesta(
                "ParcialmenteCorrecto",
                _linea("A1", "Correcto") + _linea("A2", "Incorrecto", error_code="1100"),
            )
        )
        info = _send(response=response)
        self.assertEqual(info["lineas"]["A1"]["state"], "accepted")
        self.assertEqual(info["lineas"]["A2"]["state"], "rejected")

    def test_soap_fault_server_reintentable(self):
        fault = _soap_response(
            '<env:Fault xmlns:env="http://schemas.xmlsoap.org/soap/envelope/">'
            "<faultcode>env:Server</faultcode>"
            "<faultstring>Error interno</faultstring>"
            "</env:Fault>"
        )
        info = _send(response=FakeResponse(fault))
        self.assertFalse(info["ok"])
        self.assertTrue(info["retryable"])
        self.assertIn("SOAP Fault", info["errors"][0])

    def test_soap_fault_client_no_reintentable(self):
        fault = _soap_response(
            '<env:Fault xmlns:env="http://schemas.xmlsoap.org/soap/envelope/">'
            "<faultcode>env:Client</faultcode>"
            "<faultstring>XML invalido</faultstring>"
            "</env:Fault>"
        )
        info = _send(response=FakeResponse(fault))
        self.assertFalse(info["ok"])
        self.assertFalse(info["retryable"])

    def test_http_500_reintentable(self):
        info = _send(response=FakeResponse("Internal Server Error", status_code=500))
        self.assertFalse(info["ok"])
        self.assertTrue(info["retryable"])

    def test_html_no_reintentable(self):
        info = _send(response=FakeResponse("<html><body>Acceso denegado</body></html>"))
        self.assertFalse(info["ok"])
        self.assertFalse(info["retryable"])

    def test_ssl_error_no_reintentable(self):
        info = _send(exception=requests.exceptions.SSLError("bad cert"))
        self.assertFalse(info["ok"])
        self.assertFalse(info["retryable"])
        self.assertIn("SSL", info["errors"][0])

    def test_read_timeout_reintentable(self):
        info = _send(exception=requests.exceptions.ReadTimeout("timeout"))
        self.assertFalse(info["ok"])
        self.assertTrue(info["retryable"])
        self.assertIn("[Read-Timeout]", info["errors"][0])

    def test_connection_error_reintentable(self):
        info = _send(exception=requests.exceptions.ConnectionError("refused"))
        self.assertFalse(info["ok"])
        self.assertTrue(info["retryable"])
