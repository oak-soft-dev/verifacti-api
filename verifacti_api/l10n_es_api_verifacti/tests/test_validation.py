# -*- coding: utf-8 -*-

from datetime import date

from odoo.tests import TransactionCase, tagged

from ..verifactu import validation


def payload_base(**overrides):
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
    payload.update(overrides)
    return payload


HOY = date(2026, 7, 3)


@tagged("post_install", "-at_install")
class TestValidation(TransactionCase):
    def test_payload_valido(self):
        self.assertEqual(validation.validate_create(payload_base(), hoy=HOY), [])

    def test_f2_sin_destinatario(self):
        payload = payload_base(tipo_factura="F2")
        payload.pop("nif")
        payload.pop("nombre")
        self.assertEqual(validation.validate_create(payload, hoy=HOY), [])

    def test_f2_con_destinatario_falla(self):
        errores = validation.validate_create(payload_base(tipo_factura="F2"), hoy=HOY)
        self.assertTrue(any(e["campo"] == "nif" for e in errores))

    def test_f1_sin_destinatario_falla(self):
        payload = payload_base()
        payload.pop("nif")
        errores = validation.validate_create(payload, hoy=HOY)
        self.assertTrue(any(e["campo"] == "nif" for e in errores))

    def test_fecha_no_actual(self):
        errores = validation.validate_create(payload_base(fecha_expedicion="01-01-2026"), hoy=HOY)
        self.assertTrue(any(e["campo"] == "fecha_expedicion" for e in errores))

    def test_fecha_formato_invalido(self):
        errores = validation.validate_create(payload_base(fecha_expedicion="2026-07-03"), hoy=HOY)
        self.assertTrue(any(e["campo"] == "fecha_expedicion" for e in errores))

    def test_tipo_impositivo_no_permitido(self):
        payload = payload_base(
            lineas=[{"base_imponible": "100", "tipo_impositivo": "18", "cuota_repercutida": "18"}],
            importe_total="118",
        )
        errores = validation.validate_create(payload, hoy=HOY)
        self.assertTrue(any("tipo_impositivo" in e["campo"] for e in errores))

    def test_tipo_iva_temporal_fuera_de_vigencia(self):
        # 5% solo fue válido entre 01-07-2022 y 30-09-2024
        payload = payload_base(
            lineas=[{"base_imponible": "100", "tipo_impositivo": "5", "cuota_repercutida": "5"}],
            importe_total="105",
        )
        errores = validation.validate_create(payload, hoy=HOY)
        self.assertTrue(any("tipo_impositivo" in e["campo"] for e in errores))

    def test_tipo_iva_temporal_con_fecha_operacion_en_vigencia(self):
        payload = payload_base(
            fecha_operacion="15-06-2023",
            lineas=[{"base_imponible": "100", "tipo_impositivo": "5", "cuota_repercutida": "5"}],
            importe_total="105",
        )
        self.assertEqual(validation.validate_create(payload, hoy=HOY), [])

    def test_tipo_igic_no_se_valida(self):
        payload = payload_base(
            lineas=[{"base_imponible": "100", "impuesto": "03", "tipo_impositivo": "18",
                     "cuota_repercutida": "18"}],
            importe_total="118",
        )
        self.assertEqual(validation.validate_create(payload, hoy=HOY), [])

    def test_cuota_incoherente(self):
        payload = payload_base(
            lineas=[{"base_imponible": "200", "tipo_impositivo": "21", "cuota_repercutida": "99"}],
            importe_total="299",
        )
        errores = validation.validate_create(payload, hoy=HOY)
        self.assertTrue(any("cuota_repercutida" in e["campo"] for e in errores))

    def test_importe_total_incoherente(self):
        errores = validation.validate_create(payload_base(importe_total="999"), hoy=HOY)
        self.assertTrue(any(e["campo"] == "importe_total" for e in errores))

    def test_max_lineas(self):
        linea = {"base_imponible": "10", "tipo_impositivo": "21", "cuota_repercutida": "2.1"}
        payload = payload_base(lineas=[dict(linea) for _ in range(13)], importe_total="157.3")
        errores = validation.validate_create(payload, hoy=HOY)
        self.assertTrue(any(e["campo"] == "lineas" for e in errores))

    def test_rectificativa_requiere_tipo(self):
        payload = payload_base(tipo_factura="R1")
        errores = validation.validate_create(payload, hoy=HOY)
        self.assertTrue(any(e["campo"] == "tipo_rectificativa" for e in errores))
        self.assertTrue(any(e["campo"] == "facturas_rectificadas" for e in errores))

    def test_rectificativa_s_requiere_importe(self):
        payload = payload_base(
            tipo_factura="R1",
            tipo_rectificativa="S",
            facturas_rectificadas=[{"serie": "A", "numero": "1", "fecha_expedicion": "07-04-2026"}],
        )
        errores = validation.validate_create(payload, hoy=HOY)
        self.assertTrue(any(e["campo"] == "importe_rectificativa" for e in errores))

    def test_id_otro_extranjero(self):
        payload = payload_base()
        payload.pop("nif")
        payload["id_otro"] = {"codigo_pais": "BE", "id_type": "02", "id": "BE0404621642"}
        payload["lineas"] = [{"base_imponible": "200", "operacion_exenta": "E5"}]
        payload["importe_total"] = "200"
        self.assertEqual(validation.validate_create(payload, hoy=HOY), [])

    def test_cancel_valido(self):
        payload = {"serie": "A", "numero": "1", "fecha_expedicion": "25-02-2026"}
        self.assertEqual(validation.validate_cancel(payload), [])

    def test_cancel_rechazo_previo_invalido(self):
        payload = {"serie": "A", "numero": "1", "fecha_expedicion": "25-02-2026", "rechazo_previo": "X"}
        errores = validation.validate_cancel(payload)
        self.assertTrue(any(e["campo"] == "rechazo_previo" for e in errores))
