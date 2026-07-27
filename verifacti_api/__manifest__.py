# -*- coding: utf-8 -*-
{
    "name": "Verifacti API - Integración Directa",
    "version": "13.0.1.0.0",
    "category": "Accounting/Accounting",
    "summary": "Integración directa con la API de Verifacti para cumplir VeriFactu España - Gratuito y Open Source",
    "description": """
        Verifacti API - Integración Directa
        ====================================

        **¡Prepárate para VeriFactu 2026!** 🇪🇸

        Módulo gratuito y completo para cumplir con el nuevo sistema VeriFactu de la AEAT
        mediante la API de Verifacti (https://www.verifacti.com).

        ✨ Características Principales
        ------------------------------
        ✅ **Gestión Completa de Facturas VeriFactu**
           • Envío de facturas a la AEAT mediante Verifacti API
           • Generación automática de código QR VeriFactu
           • Cálculo de huella (hash) automático
           • Descarga de XMLs de petición y respuesta
           • Monitorización del estado de envío en tiempo real

        ✅ **Gestión de Clientes**
           • Integración nativa con contactos de Odoo
           • Validación de NIF/CIF españoles en AEAT
           • Validación de IVAs intracomunitarios (VIES)
           • Gestión de clientes extranjeros

        ✅ **Operaciones Soportadas**
           • Crear factura nueva (POST /create)
           • Crear facturas en lote (POST /create_bulk)
           • Subsanar factura (PUT /modify)
           • Anular factura (POST /cancel)
           • Consultar estado factura (POST /status)
           • Consultar estado registro (GET /status)
           • Listar facturas (POST /list)
           • Exportar XMLs (POST /export)
           • Descargar XMLs (POST /downloadXML)

        ✅ **Tipos de Factura Soportados**
           • F1: Factura (Art. 6, 7.2 Y 7.3 del RD 1619/2012)
           • F2: Factura simplificada
           • R1: Factura rectificativa (Art 80.1, 80.2)
           • R2: Factura rectificativa (Art. 80.3)
           • R3: Factura rectificativa (Art. 80.4)
           • R4: Factura rectificativa (Resto)
           • R5: Factura rectificativa simplificada
           • F3: Factura en sustitución de simplificadas

        ✅ **Monitorización y Auditoría**
           • Log completo de llamadas API
           • Visualización de requests y responses
           • Tracking de errores y códigos de estado
           • Historial de cambios con Chatter

        ✅ **Configuración Sencilla**
           • Panel de configuración integrado en Ajustes de Odoo
           • Validación de API Key
           • Configuración de entornos (test/producción)
           • Sin certificados digitales necesarios

        🚀 Tecnología
        -------------
        • API REST de Verifacti (https://api.verifacti.com)
        • Sin certificados digitales requeridos
        • Gestión automática de colas y tiempos de espera
        • Generación automática de QR y huella
        • Validación de NIFs en AEAT
        • Cumplimiento 100% con normativa VeriFactu AEAT

        🔀 Elige tu Proveedor
        ---------------------
        Este módulo funciona directamente con la API SaaS de Verifacti (https://www.verifacti.com).

        ¿Prefieres no depender de un tercero? Contáctanos en oak.soft.develop@gmail.com
        y te damos acceso a nuestra versión con servidor VeriFactu propio, integrable
        en tu aplicación.

        📅 ¿Por qué ahora?
        ------------------
        VeriFactu será **OBLIGATORIO** a partir de:
        • 1 enero 2026: Empresas con Impuesto de Sociedades
        • 1 julio 2026: Resto de empresas y autónomos

        💰 Licencia y Precio
        --------------------
        **COMPLETAMENTE GRATUITO** - Licencia AGPL-3

        Este módulo es Open Source y gratuito. Solo necesitas:
        • Cuenta en Verifacti (https://www.verifacti.com)
        • API Key de Verifacti (test o producción)

        🔗 Enlaces Útiles
        -----------------
        • Verifacti: https://www.verifacti.com
        • Documentación API: https://www.verifacti.com/docs
        • Precios: https://www.verifacti.com/pricing
        • VeriFactu AEAT: https://sede.agenciatributaria.gob.es

        👨‍💻 Soporte
        -----------
        Este módulo es mantenido por la comunidad. Contribuciones bienvenidas!
    """,
    "author": "Oak Soft",
    "website": "https://github.com/oak-soft-dev/verifacti-api",
    "maintainer": "Oak Soft",
    "support": "oak.soft.develop@gmail.com",
    "license": "AGPL-3",
    "price": 0.00,
    "currency": "EUR",
    "images": ["static/description/banner.png"],
    "depends": [
        "base",
        "account",
        "contacts",
        "mail",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron_data.xml",
        "views/res_config_settings_views.xml",
        "views/account_move_views.xml",
        "views/account_move_actions.xml",
        "views/verifacti_api_log_views.xml",
        "views/menu_views.xml",
        "report/account_invoice_report.xml",
    ],
    "demo": [
        "data/demo_suppliers.xml",
        "data/demo_invoices.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
