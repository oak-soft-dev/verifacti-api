# -*- coding: utf-8 -*-

from odoo.tests import TransactionCase, tagged

from ..verifactu import xml_builder


SISTEMA_INFO = {
    "nombre_razon": "ISN",
    "nif": "B86561412",
    "nombre_sistema": "l10n_es_api_verifacti",
    "id_sistema": "01",
    "version": "1.0",
    "numero_instalacion": "INSTALACION-TEST",
    "solo_verifactu": "S",
    "multi_ot": "S",
    "indicador_multiples_ot": "S",
}


def alta_vals(payload_overrides=None, **vals_overrides):
    payload = {
        "serie": "TEST",
        "numero": "1",
        "fecha_expedicion": "03-07-2026",
        "tipo_factura": "F1",
        "descripcion": "Factura de prueba",
        "nif": "A15022510",
        "nombre": "Cliente prueba",
        "lineas": [
            {"base_imponible": "200", "tipo_impositivo": "21", "cuota_repercutida": "42"},
        ],
        "importe_total": "242",
    }
    payload.update(payload_overrides or {})
    vals = {
        "payload": payload,
        "emisor_nif": "A39200019",
        "emisor_nombre": "Emisor pruebas",
        "sistema_informatico": SISTEMA_INFO,
        "fecha_hora_huso_gen": "2026-07-03T10:00:00+02:00",
        "previo": None,
    }
    vals.update(vals_overrides)
    return vals


@tagged("post_install", "-at_install")
class TestXmlBuilder(TransactionCase):
    def test_alta_valida_xsd(self):
        registro, huella, cuota_total, importe_total = xml_builder.build_registro_alta(alta_vals())
        self.assertEqual(cuota_total, "42")
        self.assertEqual(importe_total, "242")
        self.assertEqual(len(huella), 64)
        self.assertEqual(xml_builder.validate_registro_xsd(registro), [])

    def test_alta_encadenada_valida_xsd(self):
        vals = alta_vals(
            previo={
                "IDEmisorFactura": "A39200019",
                "NumSerieFactura": "TEST0",
                "FechaExpedicionFactura": "02-07-2026",
                "Huella": "3C464DAF61ACB827C65FDA19F352A4E3BDC2C640E9E9FC4CC058073F38F12F60",
            }
        )
        registro, _huella, _cuota, _importe = xml_builder.build_registro_alta(vals)
        self.assertEqual(xml_builder.validate_registro_xsd(registro), [])

    def test_alta_extranjero_exenta(self):
        vals = alta_vals(
            payload_overrides={
                "nif": None,
                "id_otro": {"codigo_pais": "BE", "id_type": "02", "id": "BE0404621642"},
                "lineas": [{"base_imponible": "200", "operacion_exenta": "E5"}],
                "importe_total": "200",
            }
        )
        vals["payload"].pop("nif")
        registro, _huella, cuota, _importe = xml_builder.build_registro_alta(vals)
        self.assertEqual(cuota, "0")
        self.assertEqual(xml_builder.validate_registro_xsd(registro), [])

    def test_alta_simplificada_sin_destinatario(self):
        vals = alta_vals(payload_overrides={"tipo_factura": "F2"})
        vals["payload"].pop("nif")
        vals["payload"].pop("nombre")
        registro, _huella, _cuota, _importe = xml_builder.build_registro_alta(vals)
        self.assertEqual(xml_builder.validate_registro_xsd(registro), [])
        self.assertIsNone(registro.find(f"{xml_builder.SF}Destinatarios"))

    def test_alta_rectificativa(self):
        vals = alta_vals(
            payload_overrides={
                "tipo_factura": "R1",
                "tipo_rectificativa": "S",
                "importe_rectificativa": {"base_rectificada": "1000", "cuota_rectificada": "210"},
                "facturas_rectificadas": [
                    {"serie": "A", "numero": "1", "fecha_expedicion": "07-04-2026"},
                ],
            }
        )
        registro, _huella, _cuota, _importe = xml_builder.build_registro_alta(vals)
        self.assertEqual(xml_builder.validate_registro_xsd(registro), [])

    def test_anulacion_valida_xsd(self):
        registro, huella = xml_builder.build_registro_anulacion(
            {
                "payload": {"serie": "TEST", "numero": "1", "fecha_expedicion": "03-07-2026"},
                "emisor_nif": "A39200019",
                "sistema_informatico": SISTEMA_INFO,
                "fecha_hora_huso_gen": "2026-07-03T10:00:00+02:00",
                "previo": None,
            }
        )
        self.assertEqual(len(huella), 64)
        self.assertEqual(xml_builder.validate_registro_xsd(registro), [])

    def test_envelope_valida_xsd(self):
        registro, _huella, _cuota, _importe = xml_builder.build_registro_alta(alta_vals())
        envelope = xml_builder.build_envelope(
            {"nombre_razon": "Emisor pruebas", "nif": "A39200019"}, [registro]
        )
        self.assertEqual(xml_builder.validate_envelope_xsd(envelope), [])

    def test_recargo_equivalencia(self):
        vals = alta_vals(
            payload_overrides={
                "lineas": [
                    {
                        "base_imponible": "200",
                        "tipo_impositivo": "21",
                        "cuota_repercutida": "42",
                        "clave_regimen": "18",
                        "tipo_recargo_equivalencia": "5.2",
                        "cuota_recargo_equivalencia": "10.4",
                    }
                ],
                "importe_total": "252.4",
            }
        )
        registro, _huella, cuota, importe = xml_builder.build_registro_alta(vals)
        self.assertEqual(cuota, "52.4")
        self.assertEqual(importe, "252.4")
        self.assertEqual(xml_builder.validate_registro_xsd(registro), [])
