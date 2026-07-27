# -*- coding: utf-8 -*-
{
    "name": "VeriFactu Server (API compatible Verifacti)",
    "version": "19.0.1.0.0",
    "category": "Accounting/Localizations",
    "summary": "Servidor VeriFactu propio con API REST compatible con Verifacti",
    "description": """
Servidor VeriFactu autocontenido que expone la misma API REST que Verifacti
(https://www.verifacti.com) en /verifactu/* y remite los registros de
facturación directamente a la AEAT (RD 1007/2023, Orden HAC/1177/2024):

- Autenticación por API Key (Bearer) por emisor (NIF)
- Cálculo de huella SHA-256 encadenada por emisor
- Generación de XML RegistroAlta/RegistroAnulacion conforme a los XSD de AEAT
- Código QR de validación AEAT
- Envío SOAP con certificado mTLS (PKCS#12 por emisor) y control de flujo
- Entornos test (preproducción) y producción de la AEAT

El módulo cliente `verifacti_api` funciona sin cambios apuntando su URL de
API a esta instancia de Odoo.
""",
    "author": "ISN",
    "license": "LGPL-3",
    "depends": ["base", "certificate", "mail"],
    "external_dependencies": {"python": ["qrcode"]},
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron_data.xml",
        "views/verifacti_emisor_views.xml",
        "views/verifacti_registro_views.xml",
        "views/verifacti_request_log_views.xml",
        "views/menu_views.xml",
    ],
    "installable": True,
    "application": True,
}
