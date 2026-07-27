# -*- coding: utf-8 -*-

from datetime import datetime
from unittest.mock import patch

from pytz import timezone

from odoo.tests import TransactionCase, tagged

from ..models import verifacti_registro


def _info(lineas=None, ok=True, retryable=False, errors=None, csv="A-TESTCSV123", waiting=60):
    return {
        "ok": ok,
        "retryable": retryable,
        "errors": errors or [],
        "raw_response": "<respuesta/>" if ok else "",
        "csv": csv if ok else None,
        "waiting_time_seconds": waiting if ok else None,
        "estado_envio": "Correcto" if ok else None,
        "lineas": lineas or {},
    }


def _linea(state, error_code=None, error_message=None, cancellation=False, duplicate=None):
    return {
        "state": state,
        "cancellation": cancellation,
        "error_code": error_code,
        "error_message": error_message,
        "duplicate": duplicate,
    }


@tagged("post_install", "-at_install")
class TestCronSend(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Emisor = cls.env["l10n_es_verifacti.emisor"]
        cls.emisor = Emisor.search([("nif", "=", "A39200019")], limit=1) or Emisor.create(
            {
                "nif": "A39200019",
                "nombre_razon": "Emisor pruebas",
                "si_nif": "B86561412",
            }
        )
        cls.Registro = cls.env["l10n_es_verifacti.registro"]

    def _create_alta(self, numero="1"):
        hoy = datetime.now(timezone("Europe/Madrid")).strftime("%d-%m-%Y")
        payload = {
            "serie": "CRON",
            "numero": numero,
            "fecha_expedicion": hoy,
            "tipo_factura": "F1",
            "descripcion": "Factura de prueba",
            "nif": "A15022510",
            "nombre": "Cliente prueba",
            "lineas": [
                {"base_imponible": "100", "tipo_impositivo": "21", "cuota_repercutida": "21"},
            ],
            "importe_total": "121",
        }
        response = self.Registro.create_alta_from_payload(self.emisor, payload)
        return self.Registro.search([("uuid", "=", response["uuid"])])

    def _send(self, registros, info):
        with patch.object(verifacti_registro.soap_client, "send_envelope", return_value=info):
            self.Registro._send_batch_for_emisor(self.emisor, registros)

    def test_alta_aceptada(self):
        registro = self._create_alta("A1")
        self._send(registro, _info({"CRONA1": _linea("accepted")}))
        self.assertEqual(registro.state, "accepted")
        self.assertEqual(registro.response_csv, "A-TESTCSV123")
        self.assertIn("RegFactuSistemaFacturacion", registro.xml_soap_request)
        self.assertEqual(registro.xml_soap_response, "<respuesta/>")
        self.assertEqual(registro._verifacti_estado(), "Correcto")
        self.assertTrue(self.emisor.next_batch_time)

    def test_alta_rechazada(self):
        registro = self._create_alta("A2")
        self._send(
            registro,
            _info({"CRONA2": _linea("rejected", error_code="1117", error_message="Error de calculo")}),
        )
        self.assertEqual(registro.state, "rejected")
        self.assertEqual(registro.error_code, "1117")
        self.assertEqual(registro._verifacti_estado(), "Incorrecto")

    def test_alta_aceptada_con_errores(self):
        registro = self._create_alta("A3")
        self._send(
            registro,
            _info({"CRONA3": _linea("accepted_errors", error_code="2004", error_message="Fuera de plazo")}),
        )
        self.assertEqual(registro.state, "accepted_errors")
        # El cliente Verifacti no maneja AceptadoConErrores: se reporta Correcto
        self.assertEqual(registro._verifacti_estado(), "Correcto")
        self.assertEqual(registro.error_code, "2004")

    def test_fallo_reintentable_backoff(self):
        registro = self._create_alta("A4")
        self._send(registro, _info(ok=False, retryable=True, errors=["Error de red"]))
        self.assertEqual(registro.state, "aeat_error")
        self.assertEqual(registro.retry_count, 1)
        self.assertTrue(registro.next_retry_time)
        self.assertEqual(registro._verifacti_estado(), "Error servidor AEAT")

        retry1 = registro.next_retry_time
        self._send(registro, _info(ok=False, retryable=True, errors=["Error de red"]))
        self.assertEqual(registro.retry_count, 2)
        self.assertGreater(registro.next_retry_time, retry1)

    def test_fallo_no_reintentable_rechaza(self):
        registro = self._create_alta("A5")
        self._send(registro, _info(ok=False, retryable=False, errors=["SOAP Fault [env:Client] XML"]))
        self.assertEqual(registro.state, "rejected")

    def test_recuperacion_tras_timeout_duplicado(self):
        registro = self._create_alta("A6")
        self._send(registro, _info(ok=False, retryable=True, errors=["[Read-Timeout] Timeout"]))
        self.assertEqual(registro.state, "aeat_error")
        self.assertIn("[Read-Timeout]", registro.error_message)

        # Reintento: la AEAT responde duplicado con original aceptado
        self._send(
            registro,
            _info(
                {
                    "CRONA6": _linea(
                        "rejected",
                        error_code="3000",
                        duplicate={"state": "accepted", "error_code": None, "error_message": None},
                    )
                }
            ),
        )
        self.assertEqual(registro.state, "accepted")

    def test_anulacion_aceptada_marca_alta(self):
        alta = self._create_alta("A7")
        self._send(alta, _info({"CRONA7": _linea("accepted")}))

        respuesta = self.Registro.create_anulacion_from_payload(
            self.emisor,
            {"serie": "CRON", "numero": "A7", "fecha_expedicion": alta.fecha_expedicion_str},
        )
        anulacion = self.Registro.search([("uuid", "=", respuesta["uuid"])])
        self.assertEqual(anulacion.huella_anterior, alta.huella)

        self._send(anulacion, _info({"CRONA7": _linea("accepted", cancellation=True)}))
        self.assertEqual(anulacion.state, "accepted")
        self.assertTrue(alta.anulada)
        self.assertEqual(alta._verifacti_estado(), "Anulado")
        self.assertEqual(anulacion._verifacti_estado(), "Anulado")

    def test_linea_sin_respuesta_aeat_error(self):
        registro = self._create_alta("A8")
        self._send(registro, _info({"OTRA": _linea("accepted")}))
        self.assertEqual(registro.state, "aeat_error")
