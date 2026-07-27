# -*- coding: utf-8 -*-
"""Cálculo de la huella (hash) de los registros de facturación VeriFactu.

Especificación: "Detalle de las especificaciones técnicas para generación de
la huella o hash de los registros de facturación"
https://www.agenciatributaria.es/static_files/AEAT_Desarrolladores/EEDD/IVA/VERI-FACTU/Veri-Factu_especificaciones_huella_hash_registros.pdf

Los valores deben ser exactamente los mismos que se serializan en el XML
(importes formateados con 2 decimales, fechas DD-MM-YYYY, timestamp ISO-8601
con huso horario).
"""

import hashlib


def _sha256_upper(string):
    return hashlib.sha256(string.encode("utf-8")).hexdigest().upper()


def _fingerprint_string(fields_values):
    return "&".join(f"{field}={str(value).strip()}" for field, value in fields_values)


def huella_alta(
    id_emisor,
    num_serie,
    fecha_expedicion,
    tipo_factura,
    cuota_total,
    importe_total,
    huella_anterior,
    fecha_hora_huso_gen,
):
    """Huella de un RegistroAlta. `huella_anterior` = '' si es el primer registro."""
    return _sha256_upper(
        _fingerprint_string(
            [
                ("IDEmisorFactura", id_emisor),
                ("NumSerieFactura", num_serie),
                ("FechaExpedicionFactura", fecha_expedicion),
                ("TipoFactura", tipo_factura),
                ("CuotaTotal", cuota_total),
                ("ImporteTotal", importe_total),
                ("Huella", huella_anterior or ""),
                ("FechaHoraHusoGenRegistro", fecha_hora_huso_gen),
            ]
        )
    )


def huella_anulacion(
    id_emisor,
    num_serie,
    fecha_expedicion,
    huella_anterior,
    fecha_hora_huso_gen,
):
    """Huella de un RegistroAnulacion."""
    return _sha256_upper(
        _fingerprint_string(
            [
                ("IDEmisorFacturaAnulada", id_emisor),
                ("NumSerieFacturaAnulada", num_serie),
                ("FechaExpedicionFacturaAnulada", fecha_expedicion),
                ("Huella", huella_anterior or ""),
                ("FechaHoraHusoGenRegistro", fecha_hora_huso_gen),
            ]
        )
    )
