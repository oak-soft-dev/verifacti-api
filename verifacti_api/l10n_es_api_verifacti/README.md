# l10n_es_api_verifacti — Servidor VeriFactu con API compatible Verifacti

Módulo Odoo 18 que expone la misma API REST que Verifacti SaaS
(`https://api.verifacti.com`, rutas `/verifactu/*`) pero implementa VeriFactu
de verdad contra la AEAT: genera los registros XML (RD 1007/2023, Orden
HAC/1177/2024), calcula la huella SHA-256 encadenada, genera el QR y envía por
SOAP con mTLS a los servicios reales de la AEAT.

El cliente `verifacti_api` funciona sin cambios apuntando su URL a este Odoo
(selector "Proveedor → API VeriFactu propia" en Ajustes → Verifacti).

## Configuración

1. Instalar el módulo (`l10n_es_api_verifacti`). Dependencias: `base`,
   `certificate`, `mail`; librería Python `qrcode`.
2. Menú **VeriFactu Server → Emisores**: crear un emisor con:
   - NIF y razón social del obligado a expedir factura.
   - Certificado PKCS#12 (.p12/.pfx) + contraseña del titular (modelo
     `certificate.certificate`). Sin certificado los registros quedan
     `Pendiente` y no se envían.
   - Entorno: `test` (preproducción, `prewww1.aeat.es`) o `produccion`.
   - Datos del Sistema Informático (NIF del productor del software
     obligatorio).
3. Copiar la **API key** del emisor (48 caracteres) al cliente.

Cada API key identifica un emisor. Autenticación `Authorization: Bearer <key>`;
key inválida → 401.

## Endpoints

| Ruta | Método | Función |
|---|---|---|
| `/verifactu/health` | GET | Estado + NIF + entorno |
| `/verifactu/create` | POST | Alta de factura (asíncrono, devuelve `Pendiente`) |
| `/verifactu/create_bulk` | POST | Lote de hasta 50 altas |
| `/verifactu/modify` | PUT | Subsanación (`Subsanacion=S`) |
| `/verifactu/cancel` | POST | Anulación |
| `/verifactu/status` | GET `?uuid=` / POST | Estado por uuid o por serie+número+fecha |
| `/verifactu/list` | POST | Listado por ejercicio/periodo con paginación |
| `/verifactu/export` | POST | Exportación de XMLs por lotes (token) |
| `/verifactu/downloadXML` | POST | XML petición/respuesta de un registro |
| `/verifactu/declaracion_responsable` | GET | Datos del sistema informático |

Estados devueltos (enum Verifacti): `Pendiente`, `Correcto`,
`Error servidor AEAT`, `Incorrecto`, `No registrado`, `Anulado`.

## Envío a la AEAT

- Cron cada minuto (+ trigger inmediato tras cada create). Agrupa por emisor,
  respeta `TiempoEsperaEnvio` de la AEAT y envía en orden de cadena.
- Registros generados hace más de 240 s se envían con `Incidencia=S` (evita el
  rechazo 2004).
- Errores de red/5xx/fault de servidor: reintento con backoff exponencial
  (60 s → 30 min). Rechazos AEAT son terminales: reenviar vía `/modify` con
  `rechazo_previo`.
- Timeout de lectura: se recupera en el reintento vía la información de
  registro duplicado de la AEAT.
- Los registros encadenados no pueden borrarse (obligación de conservación).

## Prerequisito de despliegue: resolución de base de datos

Las rutas `/verifactu/*` son públicas (`auth='public'`): Odoo debe poder
resolver la BD **sin cookie de sesión**. Con el `dbfilter` multi-BD actual
(`^(app|ges|her|oak)_.*$`) la petición no resuelve y devuelve 404.

Opciones:
- Instancia/worker dedicado con `--db-filter '^<db>$'` (o `dbfilter` de una
  sola BD en su odoo.conf).
- Proxy (nginx/Apache) que añada la cabecera `X-Odoo-Dbfilter: ^<db>$` según
  el vhost.

## Paso a producción

1. Cambiar `entorno` del emisor a `produccion` (endpoints
   `www1.agenciatributaria.gob.es` / QR `www2.agenciatributaria.gob.es`).
2. Sustituir el certificado de pruebas por el certificado real del titular
   (debe corresponder al NIF del emisor).
3. Verificar la declaración responsable (`/verifactu/declaracion_responsable`)
   y los datos del Sistema Informático.

Registros de alta/anulación ya encadenados en test no se mezclan con
producción: usar un emisor distinto por entorno si se convive con ambos.

## Tests

```bash
python odoo-bin -c odoo.conf -d <db_test> --db-filter '^<db_test>$' \
  -i l10n_es_api_verifacti --test-enable --test-tags /l10n_es_api_verifacti \
  --stop-after-init
```

Incluyen: vectores oficiales de huella AEAT, validación de payloads,
XML contra los XSD oficiales pineados (`data/xsd/`), controladores HTTP
(HttpCase), parseo SOAP con respuestas mockeadas y ciclo del cron
(aceptado/rechazado/reintentos/anulación).
