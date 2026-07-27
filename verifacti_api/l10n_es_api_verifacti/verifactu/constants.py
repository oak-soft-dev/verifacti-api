# -*- coding: utf-8 -*-
"""Constantes VeriFactu: namespaces, endpoints AEAT y valores permitidos."""

VERIFACTU_VERSION = "1.0"
TIPO_HUELLA_SHA256 = "01"
BATCH_LIMIT = 1000

# Namespaces (de SistemaFacturacion.wsdl / XSDs oficiales AEAT)
NS_BASE = (
    "https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/"
    "aplicaciones/es/aeat/tike/cont/ws/"
)
NS_SUM_LR = NS_BASE + "SuministroLR.xsd"           # sfLR: RegFactuSistemaFacturacion
NS_SUM_INFO = NS_BASE + "SuministroInformacion.xsd"  # sf: RegistroAlta, Cabecera...
NS_RESPUESTA = NS_BASE + "RespuestaSuministro.xsd"   # sfR: RespuestaRegFactu...
NS_SOAP = "http://schemas.xmlsoap.org/soap/envelope/"

# Endpoints AEAT por entorno
ENDPOINTS = {
    "test": {
        "verifactu": "https://prewww1.aeat.es/wlpl/TIKE-CONT/ws/SistemaFacturacion/VerifactuSOAP",
        "qr": "https://prewww2.aeat.es/wlpl/TIKE-CONT/ValidarQR",
    },
    "produccion": {
        "verifactu": "https://www1.agenciatributaria.gob.es/wlpl/TIKE-CONT/ws/SistemaFacturacion/VerifactuSOAP",
        "qr": "https://www2.agenciatributaria.gob.es/wlpl/TIKE-CONT/ValidarQR",
    },
}

# Valores permitidos (normativa AEAT / API Verifacti)
TIPOS_FACTURA = {"F1", "F2", "F3", "R1", "R2", "R3", "R4", "R5"}
TIPOS_FACTURA_CON_DESTINATARIO = {"F1", "F3", "R1", "R2", "R3", "R4"}
TIPOS_RECTIFICATIVA = {"I", "S"}
TIPOS_RECTIFICATIVOS = {"R1", "R2", "R3", "R4", "R5"}
IMPUESTOS = {"01", "02", "03", "05"}  # 01=IVA, 02=IPSI, 03=IGIC, 05=Otros
CALIFICACIONES_OPERACION = {"S1", "S2", "N1", "N2"}
OPERACIONES_EXENTAS = {"E1", "E2", "E3", "E4", "E5", "E6"}
CLAVES_REGIMEN = {f"{i:02d}" for i in range(1, 21)}
ID_TYPES = {"02", "03", "04", "05", "06", "07"}
RECHAZOS_PREVIOS = {"N", "S", "X"}
SI_NO = {"S", "N"}

# Tipos de IVA (impuesto 01) admitidos — mismo comportamiento que Verifacti:
# set base + ventanas de vigencia de los tipos temporales (RDL 11/2022, RDL 4/2024).
# Se valida contra fecha_operacion si existe, si no fecha_expedicion.
# IPSI (02), IGIC (03) y otros (05) no validan el tipo.
from datetime import date as _date

TIPOS_IVA = [0, 2, 4, 5, 7.5, 10, 21]
VIGENCIAS_IVA = {
    2: (_date(2024, 10, 1), _date(2024, 12, 31)),
    5: (_date(2022, 7, 1), _date(2024, 9, 30)),
    7.5: (_date(2024, 10, 1), _date(2024, 12, 31)),
}

MAX_LINEAS = 12
MAX_BULK = 50
MAX_SERIE_NUMERO = 60
MAX_DESCRIPCION = 500

# Tolerancias de coherencia de importes (Validaciones AEAT: ±10€ a nivel factura,
# ±1% con mínimo 3€ por línea; usamos los valores globales publicados)
TOLERANCIA_CUOTA_LINEA = 10.0
TOLERANCIA_IMPORTE_TOTAL = 10.0

# Estados internos del registro -> enum de la API Verifacti
ESTADO_VERIFACTI = {
    "pending": "Pendiente",
    "sending": "Pendiente",
    "accepted": "Correcto",
    "accepted_errors": "Correcto",
    "rejected": "Incorrecto",
    "aeat_error": "Error servidor AEAT",
    "cancelled": "Anulado",
}
