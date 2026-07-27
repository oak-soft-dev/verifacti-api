# -*- coding: utf-8 -*-
"""Construcción de XML VeriFactu (RegistroAlta / RegistroAnulacion / sobre SOAP).

El orden de los elementos sigue estrictamente las secuencias de los XSD
oficiales pineados en data/xsd/ (SuministroInformacion.xsd, SuministroLR.xsd).
Sin dependencias de Odoo.
"""

import os

from lxml import etree

from . import constants, huella

SF = "{%s}" % constants.NS_SUM_INFO
SFLR = "{%s}" % constants.NS_SUM_LR
SOAP = "{%s}" % constants.NS_SOAP

NSMAP = {
    "soapenv": constants.NS_SOAP,
    "sfLR": constants.NS_SUM_LR,
    "sf": constants.NS_SUM_INFO,
}

_XSD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "xsd")
_SCHEMA_CACHE = {}


def _trim_decimales(text):
    """Quitar ceros decimales sobrantes (equivalente por spec huella AEAT)."""
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def format_importe(value):
    """Formatear importe como ImporteSgn12.2Type (punto decimal, sin ceros sobrantes)."""
    if value is None:
        return None
    return _trim_decimales(f"{float(str(value)):.2f}")


def format_tipo(value):
    """Formatear porcentaje como Tipo2.2Type (sin signo, sin ceros sobrantes)."""
    if value is None:
        return None
    return _trim_decimales(f"{float(str(value)):.2f}")


def _sub(parent, tag, text=None):
    element = etree.SubElement(parent, SF + tag)
    if text is not None:
        element.text = str(text)
    return element


def _sub_opt(parent, tag, text):
    """Añadir subelemento solo si hay valor (None/'' se omiten)."""
    if text is None or text == "":
        return None
    return _sub(parent, tag, text)


def cuota_total_from_lineas(lineas):
    """CuotaTotal = suma de cuotas repercutidas + recargos de equivalencia."""
    total = 0.0
    for linea in lineas:
        total += float(str(linea.get("cuota_repercutida") or 0))
        total += float(str(linea.get("cuota_recargo_equivalencia") or 0))
    return total


def num_serie_factura(payload):
    """NumSerieFactura AEAT = serie + numero concatenados (semántica Verifacti)."""
    return f"{payload.get('serie') or ''}{payload['numero']}"


def _persona(parent, tag, nombre, nif=None, id_otro=None):
    """PersonaFisicaJuridicaType: NombreRazon + (NIF | IDOtro)."""
    element = _sub(parent, tag)
    _sub(element, "NombreRazon", nombre)
    if nif:
        _sub(element, "NIF", str(nif).upper().strip())
    else:
        id_otro_el = _sub(element, "IDOtro")
        _sub_opt(id_otro_el, "CodigoPais", id_otro.get("codigo_pais"))
        _sub(id_otro_el, "IDType", id_otro["id_type"])
        _sub(id_otro_el, "ID", id_otro["id"])
    return element


def _encadenamiento(parent, previo):
    """Encadenamiento: PrimerRegistro o RegistroAnterior.

    :param previo: None (primer registro) o dict con IDEmisorFactura,
                   NumSerieFactura, FechaExpedicionFactura, Huella del anterior.
    """
    element = _sub(parent, "Encadenamiento")
    if not previo:
        _sub(element, "PrimerRegistro", "S")
    else:
        anterior = _sub(element, "RegistroAnterior")
        _sub(anterior, "IDEmisorFactura", previo["IDEmisorFactura"])
        _sub(anterior, "NumSerieFactura", previo["NumSerieFactura"])
        _sub(anterior, "FechaExpedicionFactura", previo["FechaExpedicionFactura"])
        _sub(anterior, "Huella", previo["Huella"])


def _sistema_informatico(parent, si):
    """SistemaInformaticoType a partir del dict del emisor."""
    element = _sub(parent, "SistemaInformatico")
    _sub(element, "NombreRazon", si["nombre_razon"])
    if si.get("nif"):
        _sub(element, "NIF", si["nif"])
    else:
        id_otro_el = _sub(element, "IDOtro")
        _sub_opt(id_otro_el, "CodigoPais", si["id_otro"].get("codigo_pais"))
        _sub(id_otro_el, "IDType", si["id_otro"]["id_type"])
        _sub(id_otro_el, "ID", si["id_otro"]["id"])
    _sub(element, "NombreSistemaInformatico", si["nombre_sistema"])
    _sub(element, "IdSistemaInformatico", si["id_sistema"])
    _sub(element, "Version", si["version"])
    _sub(element, "NumeroInstalacion", si["numero_instalacion"])
    _sub(element, "TipoUsoPosibleSoloVerifactu", si["solo_verifactu"])
    _sub(element, "TipoUsoPosibleMultiOT", si["multi_ot"])
    _sub(element, "IndicadorMultiplesOT", si["indicador_multiples_ot"])


def _detalle_desglose(parent, linea):
    """DetalleType de una línea (payload Verifacti ya validado)."""
    detalle = _sub(parent, "DetalleDesglose")
    impuesto = linea.get("impuesto") or "01"
    _sub(detalle, "Impuesto", impuesto)

    calificacion = linea.get("calificacion_operacion")
    exenta = linea.get("operacion_exenta")
    if not calificacion and not exenta:
        calificacion = "S1"

    clave_regimen = linea.get("clave_regimen")
    if not clave_regimen and impuesto in ("01", "03"):
        clave_regimen = "01"
    _sub_opt(detalle, "ClaveRegimen", clave_regimen)

    if exenta:
        _sub(detalle, "OperacionExenta", exenta)
    else:
        _sub(detalle, "CalificacionOperacion", calificacion)

    tipo = linea.get("tipo_impositivo")
    cuota = linea.get("cuota_repercutida")
    # Error AEAT [1237]: con N1/N2 e IVA no se informan tipo ni cuota
    if calificacion in ("N1", "N2") and impuesto == "01":
        tipo = None
        cuota = None
    # Las operaciones exentas no llevan tipo ni cuota
    if exenta:
        tipo = None
        cuota = None

    _sub_opt(detalle, "TipoImpositivo", format_tipo(tipo))
    _sub(detalle, "BaseImponibleOimporteNoSujeto", format_importe(linea["base_imponible"]))
    _sub_opt(detalle, "BaseImponibleACoste", format_importe(linea.get("base_imponible_a_coste")))
    _sub_opt(detalle, "CuotaRepercutida", format_importe(cuota))
    _sub_opt(detalle, "TipoRecargoEquivalencia", format_tipo(linea.get("tipo_recargo_equivalencia")))
    _sub_opt(detalle, "CuotaRecargoEquivalencia", format_importe(linea.get("cuota_recargo_equivalencia")))


def build_registro_alta(vals):
    """Construir elemento sf:RegistroAlta.

    :param dict vals: {
        payload: payload Verifacti validado,
        emisor_nif, emisor_nombre: obligado a expedir,
        sistema_informatico: dict para _sistema_informatico,
        fecha_hora_huso_gen: str ISO-8601 con offset,
        previo: dict RegistroAnterior o None,
        subsanacion: 'S'|None, rechazo_previo: 'N'|'X'|'S'|None,
    }
    Devuelve (elemento lxml, huella_calculada, cuota_total_str, importe_total_str).
    """
    payload = vals["payload"]
    num_serie = num_serie_factura(payload)
    cuota_total = format_importe(cuota_total_from_lineas(payload["lineas"]))
    importe_total = format_importe(payload["importe_total"])

    registro = etree.Element(SF + "RegistroAlta", nsmap={"sf": constants.NS_SUM_INFO})
    _sub(registro, "IDVersion", constants.VERIFACTU_VERSION)

    id_factura = _sub(registro, "IDFactura")
    _sub(id_factura, "IDEmisorFactura", vals["emisor_nif"])
    _sub(id_factura, "NumSerieFactura", num_serie)
    _sub(id_factura, "FechaExpedicionFactura", payload["fecha_expedicion"])

    _sub_opt(registro, "RefExterna", vals.get("ref_externa"))
    _sub(registro, "NombreRazonEmisor", vals["emisor_nombre"])
    _sub(registro, "Subsanacion", vals.get("subsanacion") or "N")
    _sub(registro, "RechazoPrevio", vals.get("rechazo_previo") or "N")
    _sub(registro, "TipoFactura", payload["tipo_factura"])
    _sub_opt(registro, "TipoRectificativa", payload.get("tipo_rectificativa"))

    for lista_campo, wrapper_tag, item_tag in (
        ("facturas_rectificadas", "FacturasRectificadas", "IDFacturaRectificada"),
        ("facturas_sustituidas", "FacturasSustituidas", "IDFacturaSustituida"),
    ):
        referencias = payload.get(lista_campo)
        if referencias:
            wrapper = _sub(registro, wrapper_tag)
            for ref in referencias:
                item = _sub(wrapper, item_tag)
                _sub(item, "IDEmisorFactura", vals["emisor_nif"])
                _sub(item, "NumSerieFactura", num_serie_factura(ref))
                _sub(item, "FechaExpedicionFactura", ref["fecha_expedicion"])

    importe_rect = payload.get("importe_rectificativa")
    if importe_rect:
        rect = _sub(registro, "ImporteRectificacion")
        _sub(rect, "BaseRectificada", format_importe(importe_rect["base_rectificada"]))
        _sub(rect, "CuotaRectificada", format_importe(importe_rect["cuota_rectificada"]))
        _sub_opt(rect, "CuotaRecargoRectificado", format_importe(importe_rect.get("cuota_recargo_rectificado")))

    _sub_opt(registro, "FechaOperacion", payload.get("fecha_operacion"))
    _sub(registro, "DescripcionOperacion", payload["descripcion"])

    if abs(float(importe_total)) >= 100000000:
        _sub(registro, "Macrodato", "S")

    especial = payload.get("especial") or {}
    emitida_por = especial.get("emitida_por_tercero_o_destinatario")
    if emitida_por:
        _sub(registro, "EmitidaPorTerceroODestinatario", emitida_por)
        if emitida_por == "T":
            _persona(registro, "Tercero", especial["nombre_tercero"], nif=especial["nif_tercero"])

    if payload.get("nif") or payload.get("id_otro"):
        destinatarios = _sub(registro, "Destinatarios")
        _persona(
            destinatarios,
            "IDDestinatario",
            payload["nombre"],
            nif=payload.get("nif"),
            id_otro=payload.get("id_otro"),
        )

    desglose = _sub(registro, "Desglose")
    for linea in payload["lineas"]:
        _detalle_desglose(desglose, linea)

    _sub(registro, "CuotaTotal", cuota_total)
    _sub(registro, "ImporteTotal", importe_total)

    previo = vals.get("previo")
    _encadenamiento(registro, previo)
    _sistema_informatico(registro, vals["sistema_informatico"])
    _sub(registro, "FechaHoraHusoGenRegistro", vals["fecha_hora_huso_gen"])
    _sub(registro, "TipoHuella", constants.TIPO_HUELLA_SHA256)

    huella_valor = huella.huella_alta(
        vals["emisor_nif"],
        num_serie,
        payload["fecha_expedicion"],
        payload["tipo_factura"],
        cuota_total,
        importe_total,
        previo["Huella"] if previo else "",
        vals["fecha_hora_huso_gen"],
    )
    _sub(registro, "Huella", huella_valor)

    return registro, huella_valor, cuota_total, importe_total


def build_registro_anulacion(vals):
    """Construir elemento sf:RegistroAnulacion.

    :param dict vals: {
        payload: payload de /verifactu/cancel validado,
        emisor_nif, sistema_informatico, fecha_hora_huso_gen, previo,
    }
    Devuelve (elemento lxml, huella_calculada).
    """
    payload = vals["payload"]
    num_serie = num_serie_factura(payload)

    registro = etree.Element(SF + "RegistroAnulacion", nsmap={"sf": constants.NS_SUM_INFO})
    _sub(registro, "IDVersion", constants.VERIFACTU_VERSION)

    id_factura = _sub(registro, "IDFactura")
    _sub(id_factura, "IDEmisorFacturaAnulada", vals["emisor_nif"])
    _sub(id_factura, "NumSerieFacturaAnulada", num_serie)
    _sub(id_factura, "FechaExpedicionFacturaAnulada", payload["fecha_expedicion"])

    _sub_opt(registro, "RefExterna", vals.get("ref_externa"))

    sin_registro_previo = payload.get("sin_registro_previo", "N")
    if sin_registro_previo == "S":
        _sub(registro, "SinRegistroPrevio", "S")
    rechazo_previo = payload.get("rechazo_previo", "N")
    if rechazo_previo == "S":
        _sub(registro, "RechazoPrevio", "S")

    previo = vals.get("previo")
    _encadenamiento(registro, previo)
    _sistema_informatico(registro, vals["sistema_informatico"])
    _sub(registro, "FechaHoraHusoGenRegistro", vals["fecha_hora_huso_gen"])
    _sub(registro, "TipoHuella", constants.TIPO_HUELLA_SHA256)

    huella_valor = huella.huella_anulacion(
        vals["emisor_nif"],
        num_serie,
        payload["fecha_expedicion"],
        previo["Huella"] if previo else "",
        vals["fecha_hora_huso_gen"],
    )
    _sub(registro, "Huella", huella_valor)

    return registro, huella_valor


def build_envelope(cabecera, registros_xml, incidencia=False):
    """Sobre SOAP 1.1 con sfLR:RegFactuSistemaFacturacion.

    :param dict cabecera: {nombre_razon, nif}
    :param list registros_xml: elementos sf:RegistroAlta / sf:RegistroAnulacion
    :param bool incidencia: RemisionVoluntaria/Incidencia = 'S'
    """
    envelope = etree.Element(SOAP + "Envelope", nsmap=NSMAP)
    etree.SubElement(envelope, SOAP + "Header")
    body = etree.SubElement(envelope, SOAP + "Body")

    reg_factu = etree.SubElement(body, SFLR + "RegFactuSistemaFacturacion")

    cabecera_el = etree.SubElement(reg_factu, SFLR + "Cabecera")
    obligado = _sub(cabecera_el, "ObligadoEmision")
    _sub(obligado, "NombreRazon", cabecera["nombre_razon"])
    _sub(obligado, "NIF", cabecera["nif"])
    remision = _sub(cabecera_el, "RemisionVoluntaria")
    _sub(remision, "Incidencia", "S" if incidencia else "N")

    for registro in registros_xml:
        registro_factura = etree.SubElement(reg_factu, SFLR + "RegistroFactura")
        registro_factura.append(registro)

    return etree.tostring(envelope, xml_declaration=True, encoding="UTF-8")


def _get_schema(xsd_filename):
    if xsd_filename not in _SCHEMA_CACHE:
        with open(os.path.join(_XSD_DIR, xsd_filename), "rb") as xsd_file:
            _SCHEMA_CACHE[xsd_filename] = etree.XMLSchema(etree.parse(xsd_file))
    return _SCHEMA_CACHE[xsd_filename]


def validate_registro_xsd(registro_element):
    """Validar un RegistroAlta/RegistroAnulacion contra el XSD oficial.

    Devuelve lista de mensajes de error (vacía si es válido).
    """
    schema = _get_schema("SuministroInformacion.xsd")
    if schema.validate(registro_element):
        return []
    return [str(error) for error in schema.error_log]


def validate_envelope_xsd(envelope_bytes):
    """Validar el cuerpo RegFactuSistemaFacturacion del sobre contra el XSD."""
    schema = _get_schema("SuministroLR.xsd")
    envelope = etree.fromstring(envelope_bytes)
    reg_factu = envelope.find(f".//{SFLR}RegFactuSistemaFacturacion")
    if reg_factu is None:
        return ["No se encontró RegFactuSistemaFacturacion en el sobre"]
    if schema.validate(reg_factu):
        return []
    return [str(error) for error in schema.error_log]
