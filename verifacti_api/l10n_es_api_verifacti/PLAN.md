Plan saved to: ~/.claude/plans/quiero-crear-un-modulo-parallel-cloud.md · /plan to edit
Plan: módulo l10n_es_api_verifacti — servidor VeriFactu compatible con la API de Verifacti

▎ Nombre del módulo fijado por el usuario: l10n_es_api_verifacti. Modelos con prefijo l10n_es_verifacti.*.

Contexto

El repo ya tiene custom-addons-18.0/verifacti_api, un cliente Odoo que envía facturas a AEAT a través del SaaS Verifacti (https://api.verifacti.com). Se quiere eliminar la dependencia del SaaS: crear un módulo Odoo 18 nuevo, l10n_es_api_verifacti, que exponga la misma API REST (/verifactu/*, mismos JSON de petición/respuesta según https://www.verifacti.com/en/docs) pero implemente VeriFactu de verdad: genera los registros XML conforme a AEAT (RD 1007/2023, Orden HAC/1177/2024), calcula la huella SHA-256 encadenada, genera el QR y envía por SOAP con mTLS al servicio real de AEAT. El cliente verifacti_api funcionará sin cambios apuntando su api_url a este Odoo.

Decisiones del usuario:
- Implementación real (no mock, no proxy), con registros persistentes y envío a AEAT asíncrono (create devuelve Pendiente, cron envía, GET status refleja progreso).
- Auth por API keys configurables: cada key → un emisor (NIF). Bearer inválido → 401.
- Certificado PKCS#12 (.p12/.pfx) + contraseña por emisor.
- Entorno inicial: preproducción AEAT (prewww1.aeat.es), conmutable a producción.

Activos clave descubiertos (reutilizar, no reinventar)

- odoo-18.0/addons/l10n_es_edi_verifactu/models/verifactu_document.py — implementación oficial Odoo: algoritmo de huella (_fingerprint, líneas 861-878), encadenamiento, bloque SistemaInformatico (803-830), endpoints AEAT test/prod (res_company.py:43-67), control de flujo TiempoEsperaEnvio, parseo de respuestas AEAT con duplicados (_send_batch, 955-1157), regla de 240s para FechaHoraHusoGenRegistro (1073-1077). No dependemos de él (arrastra account y plan contable ES); se portan sus algoritmos verificados a nuestro engine.
- odoo-18.0/addons/certificate/ — modelo certificate.certificate ya decodifica PKCS#12+password a PEM; certificate/tools/certificate_adapter.py da CertificateAdapter para mTLS en memoria con requests (sin PEM temporales). Dependencia del módulo.
- Certificados de prueba AEAT incluidos: l10n_es_edi_verifactu/demo/certificates/Certificado_RPJ_A39200019_...Pre.p12 y ..._PF_99999910G_...Pre.pfx, contraseña 1234 — para smoke tests en preproducción (M5).
- Libs ya en venv-18.0: qrcode, cryptography 42, lxml 5.2, requests, zeep 4.2 (odoo.tools.zeep como fallback de transporte). Sin pip installs nuevos.
- Contrato del cliente: custom-addons-18.0/verifacti_api/models/verifacti_api_client.py (Bearer, {api_url}{endpoint}, timeout 30s, errores {mensaje, detalles, errores}) y mapeo de estados en account_move.py:1756-1800 (Correcto/Pendiente/Error servidor AEAT/Incorrecto/No registrado/Anulado).

Arquitectura

Módulo autocontenido. depends: base, certificate, mail. Engine VeriFactu como paquete Python dentro del módulo (lxml para XML + requests con CertificateAdapter para SOAP mTLS; sin zeep en runtime, fallback disponible). El payload JSON Verifacti mapea ~1:1 a RegistroAlta AEAT — sin lógica de impuestos, los importes llegan como strings.

Estructura de ficheros (todos nuevos)

custom-addons-18.0/l10n_es_api_verifacti/
├── __init__.py, __manifest__.py, README.md
├── security/ir.model.access.csv
├── data/
│   ├── ir_cron.xml                  # cron_submit (1 min + trigger), retención logs
│   └── xsd/                         # XSDs AEAT pineados (descarga única en dev)
├── models/
│   ├── verifacti_emisor.py          # l10n_es_verifacti.emisor
│   ├── verifacti_registro.py        # l10n_es_verifacti.registro (+ .linea)
│   └── verifacti_request_log.py     # l10n_es_verifacti.request.log
├── verifactu/                       # engine puro
│   ├── constants.py                 # endpoints, namespaces, enums, tipos impositivos
│   ├── validation.py                # payload → [{campo, mensaje}]
│   ├── huella.py                    # fingerprint alta/anulación (port oficial)
│   ├── xml_builder.py               # RegistroAlta/Anulacion + sobre SOAP + validación XSD local
│   ├── qr.py                        # URL QR AEAT + PNG base64 (nivel M)
│   └── soap_client.py               # requests+CertificateAdapter, parseo respuesta AEAT
├── controllers/main.py              # todas las rutas /verifactu/*
├── views/ (emisor, registro, log, menú "VeriFactu Server")
└── tests/ (validation, huella vs ejemplos PDF AEAT, xml vs XSD, chaining, controllers HttpCase, soap parsing con fixtures)

Modelos

l10n_es_verifacti.emisor: nif (unique), nombre_razon, api_key (unique, indexed, default secrets.token_hex(24)=48 chars, botón regenerar, comparación hmac.compare_digest), entorno (test/produccion), certificate_id → certificate.certificate (sube p12+password), campos SistemaInformatico (si_nombre_razon, si_nif, si_nombre_sistema, si_id_sistema 2 chars, si_version, si_numero_instalacion default SHA-256 de database.uuid, si_solo_verifactu, si_multi_ot, si_indicador_multiples_ot), chain_sequence_id (ir.sequence por emisor), last_registro_id, next_batch_time (control flujo). Helpers: _find_by_api_key, _get_endpoints() (URLs SOAP+QR por entorno, copiadas de res_company.py:49-67), _lock() (SELECT ... FOR UPDATE para serializar cadena).

l10n_es_verifacti.registro: uuid (uuid4 hex, unique), emisor_id, tipo_registro (alta/anulacion), campos factura (serie, numero, fecha_expedicion, tipo_factura, descripcion, destinatario nif/nombre/id_otro, importe_total, cuota_total, tipo_rectificativa, incidencia, subsanacion, rechazo_previo...), payload_json, líneas hijas. Artefactos: chain_index, huella, huella_anterior, fecha_hora_huso_gen (ISO Europe/Madrid, fijada en creación), qr_png, qr_url, xml_registro, xml_soap_request, xml_soap_response, response_csv. Estado: pending → sending → accepted | accepted_errors | rejected | aeat_error (reintentable) | cancelled + error_code/error_message/retry_count. Mapeo salida _verifacti_estado(): pending/sending→Pendiente, accepted/accepted_errors→Correcto (accepted_errors con codigo/mensaje_error poblados — el cliente no maneja AceptadoConErrores, así queda terminal), aeat_error→Error servidor AEAT, rejected→Incorrecto, anulado→Anulado. Restricciones: rechazar alta duplicada (emisor, serie, numero, fecha_expedicion) no-rechazada; prohibir unlink de registros encadenados (conservación legal).

Pipeline create_from_payload(emisor, payload, ...) bajo emisor._lock(): validar → reservar chain_index (sequence) → leer registro anterior (o PrimerRegistro) → fijar fecha_hora_huso_gen → calcular huella → generar xml_registro + validar contra XSD local (falla el API call, no el cron) → generar QR → persistir → devolver {uuid, estado: "Pendiente", url, huella, qr}.

l10n_es_verifacti.request.log: endpoint, method, prefijo api_key, emisor, request/response truncados, status, duración, IP. Retención 90 días.

Controladores (controllers/main.py)

Todas las rutas type='http', auth='public', csrf=False, methods explícitos (NUNCA type='json': no controla status codes). Respuestas con request.make_json_response(payload, status=...). Helpers: _authenticate() (Bearer → emisor sudo, si no 401 {"mensaje": "API key inválida"}), _parse_body(), _error(status, mensaje, detalles, errores), decorador try/except+log (500 {"mensaje": ...}).

┌────────────────────────────────────┬───────────┬────────────────────────────────────────────────────────────────┐
│                Ruta                │  Método   │                             Acción                             │
├────────────────────────────────────┼───────────┼────────────────────────────────────────────────────────────────┤
│ /verifactu/health                  │ GET       │ {"estado":"OK","nif","entorno"}                                │
├────────────────────────────────────┼───────────┼────────────────────────────────────────────────────────────────┤
│ /verifactu/create                  │ POST      │ pipeline create → 200 / 400 validación                         │
├────────────────────────────────────┼───────────┼────────────────────────────────────────────────────────────────┤
│ /verifactu/create_bulk             │ POST      │ array ≤50, secuencial bajo lock, resultado por ítem            │
├────────────────────────────────────┼───────────┼────────────────────────────────────────────────────────────────┤
│ /verifactu/modify                  │ PUT       │ alta con Subsanacion='S' + RechazoPrevio (N/X/S)               │
├────────────────────────────────────┼───────────┼────────────────────────────────────────────────────────────────┤
│ /verifactu/cancel                  │ POST      │ registro anulación encadenado → {uuid, estado:"Pendiente"}     │
├────────────────────────────────────┼───────────┼────────────────────────────────────────────────────────────────┤
│ /verifactu/status                  │ GET       │ 404 si no existe; {estado, qr, codigo_error, mensaje_error}    │
│                                    │ ?uuid=    │                                                                │
├────────────────────────────────────┼───────────┼────────────────────────────────────────────────────────────────┤
│ /verifactu/status                  │ POST      │ estado por (serie,numero,fecha) desde BD local                 │
├────────────────────────────────────┼───────────┼────────────────────────────────────────────────────────────────┤
│ /verifactu/list                    │ POST      │ filtro ejercicio/periodo/serie/numero + paginación, BD local   │
├────────────────────────────────────┼───────────┼────────────────────────────────────────────────────────────────┤
│ /verifactu/export                  │ POST      │ XMLs por lotes con token de continuación                       │
├────────────────────────────────────┼───────────┼────────────────────────────────────────────────────────────────┤
│ /verifactu/downloadXML             │ POST      │ {"xml_req": soap_request o xml_registro, "xml_res":            │
│                                    │           │ soap_response o ""}                                            │
├────────────────────────────────────┼───────────┼────────────────────────────────────────────────────────────────┤
│ /verifactu/declaracion_responsable │ GET       │ datos SistemaInformatico del emisor                            │
└────────────────────────────────────┴───────────┴────────────────────────────────────────────────────────────────┘

Validación (verifactu/validation.py)

400 estilo Verifacti con {mensaje, errores:[{campo,mensaje}], detalles}. Reglas: serie+numero ≤60; fecha_expedicion DD-MM-YYYY == hoy (Europe/Madrid); descripcion ≤500; tipo_factura ∈ F1/F2/F3/R1-R5; destinatario obligatorio F1/F3/R1-R4 (nif+nombre XOR id_otro{codigo_pais,id_type,id}), prohibido en F2/R5; tipo_rectificativa I/S en R*, importe_rectificativa si S; lineas 1..12, tipo_impositivo ∈ {0,0.5,1.75,2,4,5,7,9.5,10,13.5,15,20,21}, impuesto ∈ {01,02,03,05}, calificacion_operacion (S1/S2/N1/N2) XOR operacion_exenta (E1-E6), clave_regimen 01-20; coherencia cuota≈base·tipo/100 e importe_total≈Σ (tolerancia según PDF Validaciones AEAT — verificar en M2).

Engine

- huella.py: port literal de _fingerprint oficial. Alta: IDEmisorFactura=..&NumSerieFactura=..&FechaExpedicionFactura=..&TipoFactura=..&CuotaTotal=..&ImporteTotal=..&Huella=<prev|''>&FechaHoraHusoGenRegistro=.. → SHA-256 hex mayúsculas; importes 2 decimales. Anulación con campos *FacturaAnulada. Tests contra ejemplos del PDF de huella AEAT.
- xml_builder.py: builders lxml de RegistroAlta/RegistroAnulacion + sobre SOAP RegFactuSistemaFacturacion (Cabecera ObligadoEmision + RegistroFactura[]). Orden de elementos verificado contra XSDs pineados, no de memoria. validate_against_xsd() en creación.
- qr.py: {QR_endpoint}?nif=&numserie=&fecha=&importe=; qrcode nivel M, base64 PNG.
- soap_client.py: requests.Session + CertificateAdapter (mTLS en memoria desde certificate_id), POST timeout 30s. Parseo: EstadoEnvio, CSV, TiempoEsperaEnvio, por línea EstadoRegistro + CodigoErrorRegistro/Descripcion + RegistroDuplicado. Correcto→accepted, AceptadoConErrores→accepted_errors, Incorrecto→rejected. Fault/red/HTML → aeat_error reintentable.

Cambios en verifacti_api (cliente): selector de proveedor

Requisito del usuario: poder elegir entre la API de Verifacti (SaaS) y la nuestra (l10n_es_api_verifacti) desde los ajustes del cliente. Cambios mínimos, siempre vía HTTP (misma ruta de código, contrato idéntico):

- verifacti_api/models/res_config_settings.py:
  - Nuevo campo verifacti_provider Selection [('verifacti', 'Verifacti (SaaS)'), ('propio', 'API VeriFactu propia (l10n_es_api_verifacti)')], default verifacti, persistido como param provider.
  - Nuevos campos verifacti_propio_api_url (default http://localhost:8069) y verifacti_propio_api_key, persistidos como propio_api_url / propio_api_key. Los campos existentes api_key/api_url quedan para el SaaS — cambiar de proveedor no pisa credenciales del otro.
  - get_values()/set_values() extendidos con los 3 params.
- verifacti_api/models/verifacti_api_client.py _get_config(): leer provider; si propio → usar propio_api_url/propio_api_key (misma normalización y mínimo 20 chars — la key de l10n_es_verifacti.emisor tiene 48). Resto del cliente intacto: _make_request, endpoints, logs y "Probar Conexión" funcionan igual contra ambos backends.
- verifacti_api/views/res_config_settings_views.xml: widget radio para proveedor; bloques Verifacti/propio visibles según selección (invisible por valor del campo).

Cron de envío

cron_submit cada 1 min + ir.cron._trigger() tras cada create (mayoría de envíos <240s). Por emisor: respetar next_batch_time; tomar pendientes ordenados por chain_index; Incidencia='S' en Cabecera si algún registro >240s (evita rechazo por error 2004); construir sobre, guardar xml_soap_request/response, aplicar estados, next_batch_time = now + TiempoEsperaEnvio, commit por emisor. Reintentos aeat_error: backoff exponencial 60s→30min, tope ~48 intentos con alerta. rejected terminal (reenvío = nuevo create/modify con rechazo_previo). Anulación aceptada marca también el alta → ambos reportan Anulado.

Hitos (API compatible desde día 1)

1. M1: esqueleto + modelos + auth + /verifactu/health + logging. Verificar: curl -H "Authorization: Bearer <key>" localhost:8069/verifactu/health; "Probar Conexión" del cliente pasa.
2. M2: pipeline create completo sin AEAT (validación, huella, encadenamiento, XML+XSD, QR), /create, /create_bulk, GET /status (queda Pendiente), /downloadXML, /declaracion_responsable. Incluye selector de proveedor en verifacti_api (res_config_settings + _get_config + vista). Verificar: unit tests + seleccionar proveedor propio en el cliente y enviar factura real Odoo end-to-end.
3. M3: soap_client + cron + control de flujo + /modify + /cancel + reintentos. Verificar con respuestas AEAT mockeadas (fixtures estilo l10n_es_edi_verifactu/tests/responses/).
4. M4: /list, POST /status, /export, concurrencia, retención logs.
5. M5: preproducción AEAT real con cert de pruebas incluido (A39200019, pwd 1234) o cert propio, entorno=test, envíos a prewww1.aeat.es; después documentar paso a producción.

Verificación global

- python odoo-bin -d <db_test> -i l10n_es_api_verifacti --test-enable --test-tags /l10n_es_api_verifacti
- Smoke curl por endpoint (401 sin key, 400 payloads inválidos, 200 shapes).
- End-to-end: cliente verifacti_api con api_url=http://localhost:8069 → crear factura → estado pending→correct vía cron de polling del cliente.
- M5: registro real aceptado en preproducción AEAT (CSV devuelto).

Riesgos declarados

1. Namespaces/orden XSD exactos: descargar WSDL+XSDs de AEAT y pinearlos en data/xsd/; validar cada XML localmente. Fallback: transporte con odoo.tools.zeep (como módulo oficial).
2. Certificado: el cert de cada emisor debe pertenecer a ese NIF; bloque Representante (colaborador social) fuera de v1 — documentar.
3. Multi-DB: odoo.conf tiene dbfilter = ^(app|ges|her|oak)_.*$ (ambiguo) — las rutas públicas no resuelven BD. Prerequisito de despliegue: vhost/instancia con dbfilter de una sola BD o header X-Odoo-Dbfilter en nginx. Documentar en README.
4. validar_destinatario: v1 solo validación sintáctica de NIF (sin censo AEAT/VIES).
5. Tolerancias de cuota/importe: confirmar contra "Validaciones_Errores_Veri-Factu.pdf" en M2.