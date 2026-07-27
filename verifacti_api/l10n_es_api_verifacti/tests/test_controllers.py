# -*- coding: utf-8 -*-

import json
from datetime import datetime

from pytz import timezone

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestVerifactuControllers(HttpCase):
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
        cls.api_key = cls.emisor.api_key

    def _request(self, method, path, payload=None, api_key=None):
        headers = {"Content-Type": "application/json"}
        key = api_key if api_key is not None else self.api_key
        if key:
            headers["Authorization"] = f"Bearer {key}"
        data = json.dumps(payload) if payload is not None else None
        response = self.opener.request(
            method, self.base_url() + path, data=data, headers=headers, timeout=30
        )
        return response.status_code, response.json()

    def _payload_create(self, numero="1"):
        hoy = datetime.now(timezone("Europe/Madrid")).strftime("%d-%m-%Y")
        return {
            "serie": "TEST",
            "numero": numero,
            "fecha_expedicion": hoy,
            "tipo_factura": "F1",
            "descripcion": "Factura de prueba",
            "nif": "A15022510",
            "nombre": "Cliente prueba",
            "lineas": [
                {"base_imponible": "200", "tipo_impositivo": "21", "cuota_repercutida": "42"},
            ],
            "importe_total": "242",
        }

    def test_health_ok(self):
        status, body = self._request("GET", "/verifactu/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["estado"], "OK")
        self.assertEqual(body["nif"], "A39200019")
        self.assertEqual(body["entorno"], "test")

    def test_health_sin_key_401(self):
        status, body = self._request("GET", "/verifactu/health", api_key="")
        self.assertEqual(status, 401)
        self.assertIn("mensaje", body)

    def test_health_key_invalida_401(self):
        status, _body = self._request("GET", "/verifactu/health", api_key="x" * 48)
        self.assertEqual(status, 401)

    def test_create_y_status(self):
        status, body = self._request("POST", "/verifactu/create", self._payload_create())
        self.assertEqual(status, 200)
        self.assertEqual(body["estado"], "Pendiente")
        self.assertTrue(body["uuid"])
        self.assertEqual(len(body["huella"]), 64)
        self.assertTrue(body["qr"])
        self.assertIn("ValidarQR", body["url"])

        status, body_status = self._request("GET", f"/verifactu/status?uuid={body['uuid']}")
        self.assertEqual(status, 200)
        self.assertEqual(body_status["estado"], "Pendiente")

    def test_create_duplicado_400(self):
        payload = self._payload_create(numero="DUP1")
        status, _body = self._request("POST", "/verifactu/create", payload)
        self.assertEqual(status, 200)
        status, body = self._request("POST", "/verifactu/create", payload)
        self.assertEqual(status, 400)
        self.assertIn("mensaje", body)

    def test_create_invalido_400(self):
        payload = self._payload_create()
        payload["tipo_factura"] = "ZZ"
        status, body = self._request("POST", "/verifactu/create", payload)
        self.assertEqual(status, 400)
        self.assertTrue(body.get("errores"))
        self.assertIn("tipo_factura", body.get("detalles", {}))

    def test_status_uuid_desconocido_404(self):
        status, body = self._request("GET", "/verifactu/status?uuid=inexistente")
        self.assertEqual(status, 404)
        self.assertIn("mensaje", body)

    def test_encadenamiento_huellas(self):
        _status, body1 = self._request("POST", "/verifactu/create", self._payload_create(numero="C1"))
        _status, body2 = self._request("POST", "/verifactu/create", self._payload_create(numero="C2"))
        registro2 = self.env["l10n_es_verifacti.registro"].search([("uuid", "=", body2["uuid"])])
        self.assertEqual(registro2.huella_anterior, body1["huella"])

    def test_create_bulk(self):
        payloads = [self._payload_create(numero="B1"), self._payload_create(numero="B2")]
        status, body = self._request("POST", "/verifactu/create_bulk", payloads)
        self.assertEqual(status, 200)
        self.assertEqual(len(body), 2)
        self.assertTrue(all(item.get("uuid") for item in body))

    def test_cancel(self):
        payload = self._payload_create(numero="CAN1")
        _status, _body = self._request("POST", "/verifactu/create", payload)
        status, body = self._request(
            "POST",
            "/verifactu/cancel",
            {"serie": "TEST", "numero": "CAN1", "fecha_expedicion": payload["fecha_expedicion"]},
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["uuid"])
        self.assertEqual(len(body["huella"]), 64)

    def test_cancel_sin_alta_previa(self):
        # Verifacti acepta anular facturas registradas fuera del sistema
        hoy = datetime.now(timezone("Europe/Madrid")).strftime("%d-%m-%Y")
        status, body = self._request(
            "POST",
            "/verifactu/cancel",
            {"serie": "TEST", "numero": "NUNCAEXISTIO", "fecha_expedicion": hoy},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["estado"], "Pendiente")

    def test_download_xml(self):
        payload = self._payload_create(numero="XML1")
        _status, _body = self._request("POST", "/verifactu/create", payload)
        status, body = self._request(
            "POST", "/verifactu/downloadXML", {"serie": "TEST", "numero": "XML1"}
        )
        self.assertEqual(status, 200)
        self.assertIsInstance(body, list)
        self.assertEqual(body[0]["operacion"], "Alta")
        self.assertIn("RegistroAlta", body[0]["xml_req"])

    def test_declaracion_responsable(self):
        response = self.opener.request(
            "GET",
            self.base_url() + "/verifactu/declaracion_responsable",
            allow_redirects=False,
            timeout=30,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers["Location"],
            "https://oak-soft-public.s3.eu-west-1.amazonaws.com/declaracion/1.0.0.pdf",
        )

    def test_modify(self):
        payload = self._payload_create(numero="MOD1")
        _status, created = self._request("POST", "/verifactu/create", payload)
        # Subsanar con rechazo_previo=N exige un alta ya aceptada por la AEAT
        alta = self.env["l10n_es_verifacti.registro"].search([("uuid", "=", created["uuid"])])
        alta.sudo().write({"state": "accepted"})

        payload["descripcion"] = "Factura subsanada"
        payload["rechazo_previo"] = "N"
        status, body = self._request("PUT", "/verifactu/modify", payload)
        self.assertEqual(status, 200)
        self.assertEqual(body["estado"], "Pendiente")
        self.assertNotEqual(body["uuid"], created["uuid"])

        registro = self.env["l10n_es_verifacti.registro"].search([("uuid", "=", body["uuid"])])
        self.assertEqual(registro.subsanacion, "S")
        self.assertEqual(registro.huella_anterior, created["huella"])

    def test_modify_sin_registro_aceptado_400(self):
        payload = self._payload_create(numero="MOD2")
        _status, _created = self._request("POST", "/verifactu/create", payload)
        payload["rechazo_previo"] = "N"  # el alta sigue Pendiente
        status, body = self._request("PUT", "/verifactu/modify", payload)
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "No existe el registro de facturacion.")

    def test_modify_rechazo_previo_x_sin_registro(self):
        payload = self._payload_create(numero="MOD3")
        payload["rechazo_previo"] = "X"
        status, body = self._request("PUT", "/verifactu/modify", payload)
        self.assertEqual(status, 200)
        self.assertEqual(body["estado"], "Pendiente")

    def test_status_post_no_registrado(self):
        status, body = self._request(
            "POST",
            "/verifactu/status",
            {"serie": "NOEX", "numero": "1", "fecha_expedicion": "01-07-2026"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["mensaje"], "Factura no encontrada")

    def test_status_post_sin_fecha_400(self):
        status, body = self._request("POST", "/verifactu/status", {"serie": "A", "numero": "1"})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "serie, numero y fecha_expedicion son requeridos")

    def test_list_y_export(self):
        payload = self._payload_create(numero="LST1")
        _status, created = self._request("POST", "/verifactu/create", payload)

        hoy = datetime.now(timezone("Europe/Madrid"))
        filtro = {"ejercicio": str(hoy.year), "periodo": f"{hoy.month:02d}", "serie": "TEST", "numero": "LST1"}

        status, body = self._request("POST", "/verifactu/list", filtro)
        self.assertEqual(status, 200)
        self.assertEqual(body["paginacion"], "N")
        self.assertEqual(len(body["data"]), 1)
        registro = body["data"][0]
        self.assertEqual(registro["uuid"], created["uuid"])
        self.assertEqual(registro["estado"], "Pendiente")
        self.assertEqual(registro["num_serie"], "TESTLST1")
        self.assertIn("encadenamiento", registro)
        self.assertIn("ultima_modificacion", registro)

        status, body = self._request("POST", "/verifactu/export", filtro)
        self.assertEqual(status, 200)
        self.assertEqual(body["total"], 1)
        self.assertIn("RegistroAlta", body["xmls"][0]["xml_req"])
        self.assertNotIn("token", body)

    def test_list_periodo_invalido_data_vacia(self):
        status, body = self._request("POST", "/verifactu/list", {"ejercicio": "2026", "periodo": "13"})
        self.assertEqual(status, 200)
        self.assertEqual(body, {"data": []})

    def test_list_sin_ejercicio_400(self):
        status, body = self._request("POST", "/verifactu/list", {"periodo": "07"})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "ejercicio y periodo son requeridos")

    def test_download_xml_inexistente_lista_vacia(self):
        status, body = self._request(
            "POST", "/verifactu/downloadXML", {"serie": "NOEX", "numero": "999"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(body, [])
