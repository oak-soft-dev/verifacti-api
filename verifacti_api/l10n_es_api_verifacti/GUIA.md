# Guía de `l10n_es_api_verifacti` — Servidor VeriFactu propio

Servidor VeriFactu autoalojado para Odoo 18 con **API REST 100% compatible con
Verifacti** (`https://api.verifacti.com`). Sustituye al SaaS sin tocar el
cliente: genera los registros de facturación conforme a AEAT (RD 1007/2023,
Orden HAC/1177/2024), calcula la huella SHA-256 encadenada, genera el QR
tributario y envía los registros por SOAP con certificado (mTLS) a los
servicios reales de la AEAT.

---

## 1. Cómo funciona

### Arquitectura

```
┌─────────────────────┐         HTTP REST          ┌──────────────────────────┐
│  Odoo con facturas   │  Bearer <api_key emisor>  │  Odoo con este módulo    │
│  (módulo             │ ─────────────────────────▶│  /verifactu/*            │
│   verifacti_api)     │   mismas rutas y JSON      │                          │
│                      │   que api.verifacti.com    │  1. valida payload       │
└─────────────────────┘                            │  2. huella encadenada    │
                                                   │  3. XML AEAT + XSD       │
     Pueden ser la misma instancia                 │  4. QR tributario        │
     o instancias distintas                        │  5. guarda registro      │
                                                   └───────────┬──────────────┘
                                                               │ cron (1 min,
                                                               │ asíncrono)
                                                               ▼
                                                   ┌──────────────────────────┐
                                                   │  AEAT VeriFactu           │
                                                   │  SOAP + mTLS (cert P12)  │
                                                   │  test: prewww1.aeat.es   │
                                                   │  prod: agenciatributaria │
                                                   └──────────────────────────┘
```

### Flujo de una factura

1. El cliente hace `POST /verifactu/create` con el JSON de la factura.
2. El servidor valida (mismas reglas que Verifacti), reserva el siguiente
   índice de la cadena del emisor, calcula la **huella** SHA-256 encadenada
   con el registro anterior, construye el XML `RegistroAlta`, lo valida
   contra los XSD oficiales de la AEAT (incluidos en `data/xsd/`), genera el
   QR y persiste todo. Responde al instante:
   ```json
   {"uuid": "...", "estado": "Pendiente", "url": "https://...ValidarQR?...",
    "huella": "6351ADFC...", "qr": "<png base64>"}
   ```
3. Un **cron cada minuto** (más un disparo inmediato tras cada create) agrupa
   los registros pendientes por emisor, construye el sobre SOAP
   `RegFactuSistemaFacturacion` y lo envía a la AEAT con el certificado del
   emisor. Respeta el `TiempoEsperaEnvio` que devuelve la AEAT.
4. La respuesta de la AEAT actualiza el estado del registro:
   `Correcto` (con CSV), `Incorrecto` (con código y mensaje de error) o
   `Error servidor AEAT` (se reintenta con backoff 60 s → 30 min).
5. El cliente consulta `GET /verifactu/status?uuid=...` hasta ver el estado
   final.

### Reglas importantes

- **Cadena de huellas**: cada registro incluye la huella del anterior. Los
  registros encadenados **no pueden borrarse** (obligación legal de
  conservación). No borrar nunca la BD del servidor sin exportar antes.
- **Regla de los 240 segundos**: si un registro se envía más de 240 s después
  de generarse, el sobre va con `Incidencia=S` (evita el rechazo 2004 de la
  AEAT y queda registrado igualmente).
- **Rechazos AEAT son terminales**: un registro `Incorrecto` no se reenvía;
  se corrige con `PUT /verifactu/modify` (subsanación con
  `rechazo_previo="S"`).
- **Anulación**: `POST /verifactu/cancel` crea un registro de anulación
  encadenado. Cuando la AEAT lo acepta, tanto el alta como la anulación
  reportan estado `Anulado`.

---

## 2. Configuración del servidor

### 2.1 Instalar el módulo

Dependencias Odoo: `base`, `certificate`, `mail`. Librería Python: `qrcode`
(ya en `venv-18.0`).

```bash
./venv-18.0/bin/python ./odoo-18.0/odoo-bin -c odoo.conf -d <mi_bd> \
    -i l10n_es_api_verifacti --stop-after-init
```

### 2.2 Crear el emisor

Menú **VeriFactu Server → Emisores → Nuevo**:

| Campo | Qué poner |
|---|---|
| NIF | NIF del obligado a expedir facturas (titular del certificado) |
| Nombre / Razón social | Razón social del emisor |
| Entorno | `Test (preproducción AEAT)` para probar; `Producción` para real |
| Certificado (PKCS#12) | Subir el `.p12`/`.pfx` del titular + su contraseña |
| API Key | Se genera sola (48 caracteres). Botón «Regenerar» si se compromete |

Pestaña **Sistema Informático** (obligatorio para la declaración
responsable): NIF y nombre del productor del software, nombre e ID del
sistema, versión y nº de instalación (se autogenera).

> Sin certificado, los registros se crean y quedan `Pendiente` pero **no se
> envían** a la AEAT (el cron avisa en el log).

Para probar en preproducción sirve el certificado de pruebas incluido en
Odoo: `odoo-18.0/addons/l10n_es_edi_verifactu/demo/certificates/
Certificado_RPJ_A39200019_...Pre.p12`, contraseña `1234` (NIF `A39200019`).

### 2.3 Requisito de despliegue: resolución de base de datos

Las rutas `/verifactu/*` son públicas (`auth='public'`): Odoo tiene que poder
resolver la BD **sin cookie de sesión**. Con un `dbfilter` multi-BD como el
del `odoo.conf` de este repo (`^(app|ges|her|oak)_.*$`), la petición no
resuelve BD y devuelve **404**.

Opciones (una de las dos):

- Instancia/worker dedicado: `--db-filter '^<mi_bd>$'` (o `dbfilter` de una
  sola BD en su odoo.conf).
- Proxy inverso que fije la cabecera por vhost:
  ```nginx
  location /verifactu/ {
      proxy_set_header X-Odoo-Dbfilter ^<mi_bd>$;
      proxy_pass http://odoo;
  }
  ```

Comprobar:

```bash
curl -H "Authorization: Bearer <api_key>" https://miservidor/verifactu/health
# → {"estado": "OK", "nif": "...", "entorno": "test", "hacienda": "verifactu"}
```

### 2.4 Paso a producción

1. Cambiar `Entorno` del emisor a `Producción` (endpoints
   `www1.agenciatributaria.gob.es`, QR `www2.agenciatributaria.gob.es`).
2. Sustituir el certificado de pruebas por el **real del titular** (debe
   corresponder al NIF del emisor).
3. Revisar `GET /verifactu/declaracion_responsable` (datos del sistema
   informático).

> No mezclar cadenas: si se ha estado probando con el mismo emisor en test,
> usar un emisor distinto para producción (la cadena de huellas es única por
> emisor).

---

## 3. Configuración del cliente (`verifacti_api`)

En el Odoo que emite las facturas, **Ajustes → Verifacti**:

1. **Proveedor** → `API VeriFactu propia (l10n_es_api_verifacti)`.
2. **URL API propia** → URL del Odoo servidor (p. ej.
   `https://verifactu.midominio.com` o `http://localhost:8069` si es la misma
   máquina).
3. **API Key propia** → la key de 48 caracteres del emisor (VeriFactu Server →
   Emisores).
4. Guardar y pulsar **Probar Conexión**.

La configuración es **por compañía** y las credenciales del SaaS no se pisan:
se puede volver a `Verifacti (SaaS)` en cualquier momento. El resto del
cliente (envío automático, operaciones masivas, control de carga, botones de
factura) funciona exactamente igual con ambos proveedores.

Desde ese momento: publicar factura → botón **Enviar a VeriFactu** (o envío
automático) → chatter muestra `Pendiente → Correcto` con enlace al QR de
validación de la AEAT.

---

## 4. Referencia de la API

Autenticación en todas las rutas: `Authorization: Bearer <api_key>`.
Key inválida → `401 {"message": "Unauthorized", ...}`.
Errores → `400/404 {"error": "...", "mensaje": "...", "detalles": {...},
"errores": [...]}` (superset del formato Verifacti).

| Ruta | Método | Función |
|---|---|---|
| `/verifactu/health` | GET | `{estado, nif, entorno, hacienda}` |
| `/verifactu/create` | POST | Alta de factura → `{uuid, estado, url, huella, qr}` |
| `/verifactu/create_bulk` | POST | Hasta 50 altas, resultado por ítem |
| `/verifactu/modify` | PUT | Subsanación. `rechazo_previo` obligatorio: `N` exige alta aceptada, `S` alta rechazada, `X` sin registro previo |
| `/verifactu/cancel` | POST | Anulación → `{uuid, estado, huella}`. No exige alta previa |
| `/verifactu/status` | GET `?uuid=` | Estado por uuid (404 si no existe) |
| `/verifactu/status` | POST | Detalle por serie+numero+fecha (serie opcional). No encontrada → `{"mensaje": "Factura no encontrada"}` |
| `/verifactu/list` | POST | `{ejercicio, periodo[, serie, numero, paginacion]}` → `{"paginacion": "S"/"N", "data": [...]}` |
| `/verifactu/export` | POST | XMLs por lotes de 100 con `token` de continuación |
| `/verifactu/downloadXML` | POST | Lista `[{uuid, operacion, xml_req, xml_res}]` (vacía si no hay) |
| `/verifactu/declaracion_responsable` | GET | Datos del sistema informático |

### Estados

`Pendiente` → en cola o enviándose · `Correcto` → aceptado por AEAT (hay CSV)
· `Incorrecto` → rechazado por AEAT (terminal; ver `codigo_error`) ·
`Error servidor AEAT` → fallo temporal, se reintenta · `Anulado` → anulada.
En `/verifactu/list` se usan los femeninos de la consulta AEAT (`Correcta`,
`Anulada`, `Incorrecta`).

### Ejemplo completo con curl

```bash
KEY="<api_key del emisor>"
URL="http://localhost:8069"
HOY=$(date +%d-%m-%Y)

# Alta
curl -s -X POST $URL/verifactu/create \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" -d "{
    \"serie\": \"FA\", \"numero\": \"25\", \"fecha_expedicion\": \"$HOY\",
    \"tipo_factura\": \"F1\", \"descripcion\": \"Servicios julio\",
    \"nif\": \"A15022510\", \"nombre\": \"Cliente SL\",
    \"lineas\": [{\"base_imponible\": \"100\", \"tipo_impositivo\": \"21\",
                  \"cuota_repercutida\": \"21\"}],
    \"importe_total\": \"121\"
  }"
# → {"uuid": "...", "estado": "Pendiente", ...}

# Estado (repetir hasta Correcto; el cron envía en <1 min)
curl -s "$URL/verifactu/status?uuid=<uuid>" -H "Authorization: Bearer $KEY"

# Anular
curl -s -X POST $URL/verifactu/cancel \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d "{\"serie\": \"FA\", \"numero\": \"25\", \"fecha_expedicion\": \"$HOY\"}"
```

### Reglas de validación destacables

- `fecha_expedicion` debe ser **la fecha actual** (Europe/Madrid) en
  `/create`; en `/modify` no se exige.
- Tipos de IVA (impuesto `01`): `0, 2, 4, 5, 7.5, 10, 21`. Los temporales
  solo dentro de su vigencia (contra `fecha_operacion` si existe, si no
  contra la de expedición): **5%** → 01-07-2022 a 30-09-2024; **2% y 7.5%** →
  01-10-2024 a 31-12-2024. IGIC (`03`), IPSI (`02`) y otros (`05`) no validan
  el tipo.
- Coherencia: `cuota ≈ base × tipo / 100` e `importe_total ≈ Σ líneas`
  (tolerancia ±10 €). Máximo 12 líneas.
- F2/R5 (simplificadas) **no admiten destinatario**; F1/F3/R1-R4 lo exigen
  (`nif`+`nombre` o `id_otro` para extranjeros).
- R1-R5 exigen `tipo_rectificativa` (I/S) y `facturas_rectificadas`; con S
  además `importe_rectificativa`.

---

## 5. Interfaz del servidor (menú «VeriFactu Server»)

- **Emisores**: NIF, key, certificado, entorno, contador de registros,
  próximo envío programado.
- **Registros**: cada alta/anulación con su estado, huella, cadena, CSV de la
  AEAT, QR, y pestañas con el payload original, el XML del registro y los
  XML de petición/respuesta SOAP.
- **Logs API**: cada petición HTTP recibida (endpoint, emisor, status,
  duración, cuerpo truncado). Retención 90 días (cron de limpieza diario).

---

## 6. Operación y resolución de problemas

| Síntoma | Causa probable | Solución |
|---|---|---|
| Todo da 404 | dbfilter multi-BD sin resolver | Ver §2.3 |
| 401 con key correcta | Espacios/saltos al copiar la key | Recopiar; el cliente ya normaliza |
| Registros siempre `Pendiente` | Emisor sin certificado, o cron parado | Subir P12; revisar Ajustes → Técnico → Acciones planificadas |
| `Error servidor AEAT` persistente | Caída AEAT o certificado no autorizado | Se reintenta solo (backoff hasta 30 min); si dura, mirar `xml_soap_response` del registro |
| `Incorrecto` con error 1117/1105... | Datos fiscales mal (cuotas, NIF...) | Corregir y reenviar con `/modify` + `rechazo_previo="S"` |
| Respuesta HTML de la AEAT | Certificado no admitido/caducado | Renovar certificado del emisor |
| Error 3000 «duplicado» | El registro ya llegó en un envío anterior | El estado real está en `RegistroDuplicado`; comprobar en AEAT |

### Tests

```bash
./venv-18.0/bin/python ./odoo-18.0/odoo-bin -c odoo.conf -d <bd_test> \
  --db-filter '^<bd_test>$' -u l10n_es_api_verifacti \
  --test-enable --test-tags /l10n_es_api_verifacti --stop-after-init
```

72 tests: vectores oficiales de huella AEAT, validación (incl. vigencias de
IVA), XML contra XSD oficiales, controladores HTTP, parseo SOAP mockeado y
ciclo completo del cron (aceptado/rechazado/reintentos/anulación).

---

## 7. Compatibilidad con Verifacti (verificada)

Probado caso a caso contra `api.verifacti.com` real (~35 escenarios):
mismos códigos HTTP y shapes JSON en `create` (todas las variantes F1-F3,
R1-R5, exentas, IGIC/IPSI, recargo), `modify`, `cancel`, `status` (GET y
POST), `list`, `downloadXML` y todos los casos de error. Diferencias a favor:

- `create_bulk`, `export` y `declaracion_responsable` funcionan aquí (el SaaS
  los bloquea en cuentas de prueba o no los tiene).
- Los errores 400 incluyen además `detalles`/`errores` por campo.
- `huella` presente en más respuestas.
- `/list` respeta el filtro `serie` (el SaaS lo ignora).

Cualquier cliente escrito contra Verifacti funciona apuntando la URL base a
este servidor y usando la key del emisor.
