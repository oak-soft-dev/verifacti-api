# -*- coding: utf-8 -*-
"""Validación de payloads de la API (formato Verifacti).

Cada función devuelve una lista de errores `[{"campo": ..., "mensaje": ...}]`.
Lista vacía = payload válido. Sin dependencias de Odoo (testeable aislada).
"""

import re
from datetime import datetime

from . import constants

FECHA_RE = re.compile(r"^\d{2}-\d{2}-\d{4}$")
NIF_RE = re.compile(r"^[0-9A-Z][0-9]{7}[0-9A-Z]$")


def _err(campo, mensaje):
    return {"campo": campo, "mensaje": mensaje}


def _parse_fecha(value):
    try:
        return datetime.strptime(value, "%d-%m-%Y").date()
    except (ValueError, TypeError):
        return None


def _parse_importe(value):
    """Los importes de la API llegan como string numérico."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(str(value))
    except ValueError:
        return None


def _validar_nif_es(nif):
    """Validación sintáctica de NIF español (9 caracteres, patrón AEAT)."""
    return bool(nif) and bool(NIF_RE.match(str(nif).upper().strip()))


def _tipo_iva_normalizado(valor):
    """Valor canónico del set de tipos de IVA, o None si no está permitido."""
    return next(
        (permitido for permitido in constants.TIPOS_IVA if abs(valor - permitido) < 0.005), None
    )


def _validar_id_factura(payload, errores, hoy=None, campo_prefijo=""):
    serie = payload.get("serie")
    numero = payload.get("numero")
    fecha = payload.get("fecha_expedicion")

    if serie is None:
        errores.append(_err(campo_prefijo + "serie", "El campo serie es obligatorio (puede ser cadena vacía)"))
    if not numero:
        errores.append(_err(campo_prefijo + "numero", "El campo numero es obligatorio"))
    if serie is not None and numero and len(f"{serie}{numero}") > constants.MAX_SERIE_NUMERO:
        errores.append(_err(campo_prefijo + "numero", "serie + numero no puede superar 60 caracteres"))

    if not fecha or not FECHA_RE.match(str(fecha)):
        errores.append(_err(campo_prefijo + "fecha_expedicion", "Formato de fecha inválido, debe ser DD-MM-YYYY"))
    else:
        fecha_dt = _parse_fecha(fecha)
        if not fecha_dt:
            errores.append(_err(campo_prefijo + "fecha_expedicion", "Fecha inexistente"))
        elif hoy and fecha_dt != hoy:
            errores.append(
                _err(
                    campo_prefijo + "fecha_expedicion",
                    "La fecha de expedición debe ser la fecha actual (registro VeriFactu en tiempo real)",
                )
            )


def _validar_destinatario(payload, tipo_factura, errores):
    nif = payload.get("nif")
    nombre = payload.get("nombre")
    id_otro = payload.get("id_otro")

    if tipo_factura in ("F2", "R5"):
        if nif or id_otro:
            errores.append(
                _err("nif", "Las facturas simplificadas (F2/R5) no admiten destinatario")
            )
        return

    if tipo_factura in constants.TIPOS_FACTURA_CON_DESTINATARIO:
        if not nombre:
            errores.append(_err("nombre", "El nombre del destinatario es obligatorio"))
        if not nif and not id_otro:
            errores.append(_err("nif", "Se requiere nif o id_otro para el destinatario"))
        if nif and id_otro:
            errores.append(_err("nif", "nif e id_otro son excluyentes"))
        if nif and not _validar_nif_es(nif):
            errores.append(_err("nif", f"NIF inválido: {nif}"))
        if id_otro:
            if not isinstance(id_otro, dict):
                errores.append(_err("id_otro", "id_otro debe ser un objeto"))
            else:
                if id_otro.get("id_type") not in constants.ID_TYPES:
                    errores.append(_err("id_otro.id_type", "id_type inválido (02-07)"))
                if not id_otro.get("id"):
                    errores.append(_err("id_otro.id", "id es obligatorio"))
                elif len(str(id_otro["id"])) > 20:
                    errores.append(_err("id_otro.id", "id no puede superar 20 caracteres"))
                codigo_pais = id_otro.get("codigo_pais")
                if codigo_pais and not re.match(r"^[A-Z]{2}$", str(codigo_pais)):
                    errores.append(_err("id_otro.codigo_pais", "codigo_pais debe ser ISO-3166 alfa-2"))


def _validar_lineas(payload, errores):
    lineas = payload.get("lineas")
    if not isinstance(lineas, list) or not lineas:
        errores.append(_err("lineas", "Se requiere al menos una línea"))
        return 0.0

    # Los tipos temporales de IVA se validan contra la fecha de operación
    # (si existe) o la de expedición — mismo criterio que Verifacti.
    fecha_referencia = _parse_fecha(payload.get("fecha_operacion")) or _parse_fecha(
        payload.get("fecha_expedicion")
    )

    if len(lineas) > constants.MAX_LINEAS:
        errores.append(_err("lineas", f"Máximo {constants.MAX_LINEAS} líneas por factura (límite AEAT)"))

    suma_total = 0.0
    for i, linea in enumerate(lineas):
        campo = f"lineas[{i}]"
        if not isinstance(linea, dict):
            errores.append(_err(campo, "Cada línea debe ser un objeto"))
            continue

        base = _parse_importe(linea.get("base_imponible"))
        if base is None:
            errores.append(_err(f"{campo}.base_imponible", "base_imponible es obligatoria y numérica"))
            continue

        impuesto = linea.get("impuesto", "01")
        if impuesto not in constants.IMPUESTOS:
            errores.append(_err(f"{campo}.impuesto", "impuesto inválido (01, 02, 03, 05)"))

        calificacion = linea.get("calificacion_operacion")
        exenta = linea.get("operacion_exenta")
        if calificacion and exenta:
            errores.append(
                _err(f"{campo}.calificacion_operacion", "calificacion_operacion y operacion_exenta son excluyentes")
            )
        if calificacion and calificacion not in constants.CALIFICACIONES_OPERACION:
            errores.append(_err(f"{campo}.calificacion_operacion", "Valor inválido (S1, S2, N1, N2)"))
        if exenta and exenta not in constants.OPERACIONES_EXENTAS:
            errores.append(_err(f"{campo}.operacion_exenta", "Valor inválido (E1-E6)"))

        clave_regimen = linea.get("clave_regimen")
        if clave_regimen and clave_regimen not in constants.CLAVES_REGIMEN:
            errores.append(_err(f"{campo}.clave_regimen", "clave_regimen inválida (01-20)"))

        tipo = _parse_importe(linea.get("tipo_impositivo"))
        cuota = _parse_importe(linea.get("cuota_repercutida"))
        if linea.get("tipo_impositivo") is not None:
            if tipo is None:
                errores.append(_err(f"{campo}.tipo_impositivo", "tipo_impositivo debe ser numérico"))
            elif impuesto == "01":
                tipo_iva = _tipo_iva_normalizado(tipo)
                if tipo_iva is None:
                    permitidos = ", ".join(f"{v:g}" for v in constants.TIPOS_IVA)
                    errores.append(
                        _err(
                            f"{campo}.tipo_impositivo",
                            f"Si impuesto es 01, el campo tipo_impositivo debe ser {permitidos}",
                        )
                    )
                else:
                    vigencia = constants.VIGENCIAS_IVA.get(tipo_iva)
                    if vigencia and fecha_referencia and not (vigencia[0] <= fecha_referencia <= vigencia[1]):
                        desde = vigencia[0].strftime("%d-%m-%Y")
                        hasta = vigencia[1].strftime("%d-%m-%Y")
                        errores.append(
                            _err(
                                f"{campo}.tipo_impositivo",
                                f"Si impuesto es 01 y la fecha de operacion o expedicion no esta entre "
                                f"el {desde} y el {hasta}, el campo tipo_impositivo no puede ser {tipo_iva:g}",
                            )
                        )
        if linea.get("cuota_repercutida") is not None and cuota is None:
            errores.append(_err(f"{campo}.cuota_repercutida", "cuota_repercutida debe ser numérica"))

        # Coherencia cuota ≈ base * tipo / 100 (validación AEAT con tolerancia)
        if tipo is not None and cuota is not None:
            esperada = base * tipo / 100.0
            if abs(cuota - esperada) > constants.TOLERANCIA_CUOTA_LINEA:
                errores.append(
                    _err(
                        f"{campo}.cuota_repercutida",
                        f"cuota_repercutida ({cuota:.2f}) incoherente con base * tipo ({esperada:.2f})",
                    )
                )

        recargo_cuota = _parse_importe(linea.get("cuota_recargo_equivalencia")) or 0.0
        suma_total += base + (cuota or 0.0) + recargo_cuota

    return suma_total


def validate_create(payload, hoy=None):
    """Validar payload de POST /verifactu/create (y PUT /verifactu/modify).

    :param dict payload: payload JSON de la petición
    :param date hoy: fecha actual en Europe/Madrid (None = no comprobar)
    """
    errores = []
    if not isinstance(payload, dict):
        return [_err("payload", "El cuerpo debe ser un objeto JSON")]

    _validar_id_factura(payload, errores, hoy=hoy)

    tipo_factura = payload.get("tipo_factura")
    if tipo_factura not in constants.TIPOS_FACTURA:
        errores.append(_err("tipo_factura", "tipo_factura inválido (F1, F2, F3, R1-R5)"))

    descripcion = payload.get("descripcion")
    if not descripcion:
        errores.append(_err("descripcion", "descripcion es obligatoria"))
    elif len(descripcion) > constants.MAX_DESCRIPCION:
        errores.append(_err("descripcion", f"descripcion no puede superar {constants.MAX_DESCRIPCION} caracteres"))

    _validar_destinatario(payload, tipo_factura, errores)

    # Rectificativas
    tipo_rectificativa = payload.get("tipo_rectificativa")
    if tipo_factura in constants.TIPOS_RECTIFICATIVOS:
        if tipo_rectificativa not in constants.TIPOS_RECTIFICATIVA:
            errores.append(_err("tipo_rectificativa", "tipo_rectificativa (I/S) es obligatoria en facturas R1-R5"))
        if tipo_rectificativa == "S":
            importe_rect = payload.get("importe_rectificativa")
            if not isinstance(importe_rect, dict) or importe_rect.get("base_rectificada") is None \
                    or importe_rect.get("cuota_rectificada") is None:
                errores.append(
                    _err(
                        "importe_rectificativa",
                        "importe_rectificativa {base_rectificada, cuota_rectificada} es obligatorio si tipo_rectificativa=S",
                    )
                )
        if not payload.get("facturas_rectificadas"):
            errores.append(_err("facturas_rectificadas", "facturas_rectificadas es obligatorio en facturas R1-R5"))
    elif tipo_rectificativa:
        errores.append(_err("tipo_rectificativa", "tipo_rectificativa solo aplica a facturas R1-R5"))

    for lista_campo in ("facturas_rectificadas", "facturas_sustituidas"):
        referencias = payload.get(lista_campo)
        if referencias is None:
            continue
        if not isinstance(referencias, list):
            errores.append(_err(lista_campo, f"{lista_campo} debe ser una lista"))
            continue
        for i, ref in enumerate(referencias):
            if not isinstance(ref, dict):
                errores.append(_err(f"{lista_campo}[{i}]", "Cada referencia debe ser un objeto"))
                continue
            _validar_id_factura(ref, errores, hoy=None, campo_prefijo=f"{lista_campo}[{i}].")

    if payload.get("facturas_sustituidas") and tipo_factura != "F3":
        errores.append(_err("facturas_sustituidas", "facturas_sustituidas solo aplica a facturas F3"))

    if payload.get("incidencia") and payload["incidencia"] not in constants.SI_NO:
        errores.append(_err("incidencia", "incidencia debe ser S o N"))

    especial = payload.get("especial")
    if especial is not None:
        if not isinstance(especial, dict):
            errores.append(_err("especial", "especial debe ser un objeto"))
        else:
            emitida_por = especial.get("emitida_por_tercero_o_destinatario")
            if emitida_por not in ("T", "D"):
                errores.append(_err("especial.emitida_por_tercero_o_destinatario", "Valor inválido (T/D)"))
            elif emitida_por == "T":
                if not especial.get("nombre_tercero") or not especial.get("nif_tercero"):
                    errores.append(_err("especial", "nombre_tercero y nif_tercero son obligatorios si emite un tercero"))
                elif not _validar_nif_es(especial["nif_tercero"]):
                    errores.append(_err("especial.nif_tercero", f"NIF inválido: {especial['nif_tercero']}"))

    # Líneas y coherencia del total
    suma_lineas = _validar_lineas(payload, errores)
    importe_total = _parse_importe(payload.get("importe_total"))
    if importe_total is None:
        errores.append(_err("importe_total", "importe_total es obligatorio y numérico"))
    elif not any(e["campo"].startswith("lineas") for e in errores):
        if abs(importe_total - suma_lineas) > constants.TOLERANCIA_IMPORTE_TOTAL:
            errores.append(
                _err(
                    "importe_total",
                    f"importe_total ({importe_total:.2f}) incoherente con la suma de líneas ({suma_lineas:.2f})",
                )
            )

    return errores


def validate_modify(payload, hoy=None):
    """PUT /verifactu/modify: mismo shape que create + rechazo_previo (N/X/S)."""
    errores = validate_create(payload, hoy=None)  # la subsanación no exige fecha actual
    # Verifacti exige el campo explícito en /modify
    rechazo_previo = payload.get("rechazo_previo") if isinstance(payload, dict) else None
    if rechazo_previo not in constants.RECHAZOS_PREVIOS:
        errores.append(_err("rechazo_previo", "rechazo_previo es obligatorio y debe ser N, X o S"))
    return errores


def validate_cancel(payload):
    """POST /verifactu/cancel."""
    errores = []
    if not isinstance(payload, dict):
        return [_err("payload", "El cuerpo debe ser un objeto JSON")]
    _validar_id_factura(payload, errores)
    if payload.get("rechazo_previo", "N") not in ("N", "S"):
        errores.append(_err("rechazo_previo", "rechazo_previo debe ser N o S"))
    if payload.get("sin_registro_previo", "N") not in constants.SI_NO:
        errores.append(_err("sin_registro_previo", "sin_registro_previo debe ser S o N"))
    if payload.get("incidencia") and payload["incidencia"] not in constants.SI_NO:
        errores.append(_err("incidencia", "incidencia debe ser S o N"))
    return errores
