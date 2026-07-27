# -*- coding: utf-8 -*-
"""Generación del código QR VeriFactu.

Especificación: "Detalle de las especificaciones técnicas del código «QR» de
la factura y de la «URL» del servicio de cotejo"
https://www.agenciatributaria.es/static_files/AEAT_Desarrolladores/EEDD/IVA/VERI-FACTU/DetalleEspecificacTecnCodigoQRfactura.pdf
"""

import base64
import io
from urllib.parse import urlencode

import qrcode

from . import constants


def qr_url(entorno, nif, num_serie, fecha_expedicion, importe_total):
    """URL de cotejo AEAT que codifica el QR."""
    endpoint = constants.ENDPOINTS[entorno]["qr"]
    params = urlencode(
        {
            "nif": nif,
            "numserie": num_serie,
            "fecha": fecha_expedicion,
            "importe": importe_total,
        }
    )
    return f"{endpoint}?{params}"


def qr_png_base64(url):
    """PNG del QR en base64 (nivel de corrección M, 30-40mm según spec)."""
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=6,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")
