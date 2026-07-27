# -*- coding: utf-8 -*-
"""Tests de huella contra los ejemplos oficiales del PDF de la AEAT
("Detalle de las especificaciones técnicas para generación de la huella o
hash de los registros de facturación")."""

from odoo.tests import TransactionCase, tagged

from ..verifactu import huella


@tagged("post_install", "-at_install")
class TestHuella(TransactionCase):
    def test_huella_alta_primer_registro(self):
        resultado = huella.huella_alta(
            "  89890001K  ",
            "  12345678/G33  ",
            "  01-01-2024  ",
            "  F1  ",
            "  12.35  ",
            "  123.45  ",
            "",
            "  2024-01-01T19:20:30+01:00  ",
        )
        self.assertEqual(resultado, "3C464DAF61ACB827C65FDA19F352A4E3BDC2C640E9E9FC4CC058073F38F12F60")

    def test_huella_alta_encadenada(self):
        resultado = huella.huella_alta(
            "89890001K",
            "12345679/G34",
            "01-01-2024",
            "F1",
            "12.35",
            "123.45",
            "3C464DAF61ACB827C65FDA19F352A4E3BDC2C640E9E9FC4CC058073F38F12F60",
            "2024-01-01T19:20:35+01:00",
        )
        self.assertEqual(resultado, "F7B94CFD8924EDFF273501B01EE5153E4CE8F259766F88CF6ACB8935802A2B97")

    def test_huella_anulacion(self):
        resultado = huella.huella_anulacion(
            "89890001K",
            "12345679/G34",
            "01-01-2024",
            "F7B94CFD8924EDFF273501B01EE5153E4CE8F259766F88CF6ACB8935802A2B97",
            "2024-01-01T19:20:40+01:00",
        )
        self.assertEqual(resultado, "177547C0D57AC74748561D054A9CEC14B4C4EA23D1BEFD6F2E69E3A388F90C68")
