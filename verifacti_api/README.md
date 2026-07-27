# Verifacti API - Integración Directa con VeriFactu

Módulo de Odoo 16 para integración directa con la API de Verifacti y cumplimiento del sistema VeriFactu de la AEAT.

## Descripción

Este módulo permite enviar facturas directamente a la AEAT mediante la API de Verifacti (https://www.verifacti.com), evitando la necesidad de certificados digitales y simplificando el cumplimiento de la normativa VeriFactu que será obligatoria en 2026.

### Elige tu Proveedor VeriFactu

Por defecto, el módulo usa la API SaaS de Verifacti. Si prefieres no depender de un
tercero, contáctanos en **oak.soft.develop@gmail.com** y te damos acceso a nuestra
versión con servidor VeriFactu propio, integrable en tu aplicación.

### Arquitectura Multi-Proveedor

✅ **Soporte para múltiples emisores de facturas (multi-tenant)**
- Cada proveedor/emisor tiene su propia API Key de Verifacti
- Gestión independiente de facturas por NIF emisor
- Ideal para aplicaciones SaaS y gestorías
- Estadísticas individuales por proveedor

## Características Principales

### Gestión Completa de Facturas VeriFactu
- ✅ Envío de facturas a la AEAT mediante Verifacti API
- ✅ Generación automática de código QR VeriFactu
- ✅ Cálculo de huella (hash) automático
- ✅ Descarga de XMLs de petición y respuesta
- ✅ Monitorización del estado de envío en tiempo real

### Operaciones Soportadas
- ✅ Crear factura nueva (POST /verifactu/create)
- ✅ Crear facturas en lote - hasta 50 (POST /verifactu/create_bulk)
- ✅ Subsanar factura (PUT /verifactu/modify)
- ✅ Anular factura (POST /verifactu/cancel)
- ✅ Consultar estado factura en AEAT (POST /verifactu/status)
- ✅ Consultar estado registro (GET /verifactu/status)
- ✅ Listar facturas (POST /verifactu/list)
- ✅ Exportar XMLs (POST /verifactu/export)
- ✅ Descargar XMLs (POST /verifactu/downloadXML)

### Tipos de Factura Soportados
- **F1**: Factura (Art. 6, 7.2 Y 7.3 del RD 1619/2012)
- **F2**: Factura simplificada
- **R1**: Factura rectificativa (Art 80.1, 80.2)
- **R2**: Factura rectificativa (Art. 80.3)
- **R3**: Factura rectificativa (Art. 80.4)
- **R4**: Factura rectificativa (Resto)
- **R5**: Factura rectificativa simplificada
- **F3**: Factura en sustitución de simplificadas

### Gestión de Clientes
- ✅ Integración nativa con contactos de Odoo
- ✅ Validación de NIF/CIF españoles en AEAT
- ✅ Validación de IVAs intracomunitarios (VIES)
- ✅ Gestión de clientes extranjeros

### Monitorización y Auditoría
- ✅ Log completo de llamadas API
- ✅ Visualización de requests y responses
- ✅ Tracking de errores y códigos de estado
- ✅ Historial de cambios con Chatter

## Instalación

1. Copiar el módulo en la carpeta `addons` de Odoo:
```bash
cp -r verifacti_api /ruta/a/odoo/addons/
```

2. Actualizar la lista de módulos en Odoo:
   - Ir a: Aplicaciones > Actualizar lista de aplicaciones

3. Buscar "Verifacti API" e instalar

## Configuración

### 1. Obtener API Key de Verifacti

1. Registrarse en https://www.verifacti.com
2. Registrar cada NIF emisor que quieras usar
3. Obtener una API Key para cada NIF registrado
4. Elegir el entorno adecuado:
   - **Test**: Para pruebas (comunica con entorno de pruebas de la AEAT)
   - **Producción**: Para facturas reales (requiere suscripción)

### 2. Configurar Compañía en Odoo

1. Ir a: **Configuración > Compañías > [Tu Compañía]**
2. Ir a la pestaña **Verifacti**
3. Configurar:
   - **API Key de Verifacti**: API Key obtenida de Verifacti (debe coincidir con el NIF de la compañía)
   - **Envío Automático**: Activar para envío automático de facturas
   - **Configuración Avanzada** (opcional):
     - **URL API**: Dejar por defecto (`https://api.verifacti.com`)
     - **Reintentos**: Número de intentos en caso de error (por defecto: 3)
     - **Espera**: Segundos entre reintentos (por defecto: 2)
     - **Límite Operaciones Masivas**: Máximo de facturas por operación masiva (por defecto: 10)
     - **Control de Carga**: Control de carga del sistema para alto volumen
     - **Carga Máxima**: Load average máximo permitido (por defecto: 4.0)
4. Hacer clic en **Probar Conexión** para verificar la configuración
5. Guardar

**Nota**: Puedes crear múltiples proveedores, cada uno con su propio NIF y API Key. Esto es ideal para:
- Gestorías que gestionan múltiples clientes
- Aplicaciones SaaS multi-tenant
- Empresas con múltiples NIFs emisores

### 3. Configurar Clientes VeriFactu

1. Ir a: **Contactos**
2. Seleccionar o crear un cliente
3. Marcar la casilla **Cliente VeriFactu**
4. Asegurarse de que el cliente tenga:
   - **NIF/CIF**: Obligatorio para facturas F1 (no simplificadas)
   - **Nombre**: Obligatorio
   - **Dirección**: Recomendado

## Uso

### Crear una Factura VeriFactu

1. Ir a: **Verifacti > Facturas**
2. Hacer clic en **Crear**
3. Rellenar los datos:
   - **Proveedor Emisor**: Seleccionar el proveedor que emite la factura
   - **Serie**: (opcional) Ej: "A", "B", etc.
   - **Número**: (obligatorio) Ej: "00001"
   - **Cliente**: Seleccionar un cliente marcado como VeriFactu
   - **Fecha de Expedición**: Fecha de emisión
   - **Fecha de Operación**: (opcional) Si es diferente de la expedición
   - **Tipo de Factura**: F1, F2, R1, etc.
   - **Descripción**: Descripción de la operación (máx 500 caracteres)

4. Añadir **Líneas de Factura**:
   - **Base Imponible**: Importe sin IVA
   - **Tipo Impositivo**: 0, 2, 4, 5, 7.5, 10, 21 (para IVA)
   - **Cuota Repercutida**: Importe del IVA
   - **Impuesto**: IVA, IPSI, IGIC u Otros
   - **Calificación Operación**: S1 (más común), S2, N1, N2
   - **Clave Régimen**: 01 (régimen general) u otras

5. Hacer clic en **Guardar**

### Enviar Factura a Verifacti

1. Abrir la factura creada
2. Hacer clic en **Enviar a Verifacti**
3. El sistema enviará la factura usando la API Key del proveedor emisor seleccionado
4. La factura cambiará a estado **Pendiente**
5. En unos segundos/minutos, el sistema verificará automáticamente el estado
6. El estado cambiará a:
   - **Correcto**: Factura aceptada por la AEAT
   - **Error**: Factura rechazada (ver mensaje de error)

### Verificar Estado de la Factura

Existen dos formas de verificar el estado:

1. **Verificar Estado Registro** (más rápido):
   - Muestra el estado del envío en Verifacti
   - Estados: Pendiente, Correcto, Incorrecto, etc.
   - Soporta operaciones masivas (hasta el límite configurado)

2. **Verificar Estado AEAT** (más completo):
   - Consulta directamente a la AEAT
   - Muestra información completa de la factura registrada

### Operaciones Masivas

El módulo soporta operaciones masivas con límite configurable:

- **Enviar múltiples facturas**: Selecciona varias facturas y envíalas en un solo click
- **Verificar estado masivo**: Verifica el estado de múltiples facturas simultáneamente
- **Límite configurable**: Por defecto 10 facturas, modificable en Configuración > Compañías > [Tu Compañía] > Verifacti > Configuración Avanzada > Límite Operaciones Masivas
- **Notificación automática**: Si se seleccionan más facturas del límite, se procesarán solo las primeras y recibirás una advertencia

### Descargar XMLs

1. Abrir una factura en estado **Correcto**
2. Hacer clic en **Descargar XMLs**
3. Ver los XMLs en la pestaña **XMLs**:
   - **XML Petición**: XML enviado a la AEAT
   - **XML Respuesta**: XML recibido de la AEAT

### Anular una Factura

1. Abrir una factura en estado **Correcto**
2. Hacer clic en **Anular Factura**
3. Confirmar la anulación
4. La factura cambiará a estado **Anulado**

## Validaciones y Restricciones

### Validaciones Automáticas

El módulo realiza las siguientes validaciones:

1. **Proveedor obligatorio**: Toda factura debe tener un proveedor emisor asignado
2. **Límite de líneas**: Máximo 12 líneas por factura (restricción de la AEAT)
3. **Descripción**: Máximo 500 caracteres
4. **Tipo impositivo para IVA**: Solo valores permitidos (0, 2, 4, 5, 7.5, 10, 21)
5. **Operaciones exentas**: No pueden tener tipo impositivo ni cuota repercutida
6. **Unicidad**: No pueden existir dos facturas del mismo proveedor con la misma (serie, número, fecha_expedición)

### Validación de Destinatarios

Por defecto, el módulo valida que el NIF del destinatario esté censado en la AEAT antes de enviar. Esto evita rechazos posteriores.

Para desactivar esta validación:
- Desmarcar **Validar Destinatario en AEAT** en el formulario de factura

## Estados de la Factura

| Estado | Descripción |
|--------|-------------|
| **Borrador** | Factura creada pero no enviada |
| **Enviado** | Factura enviada a Verifacti |
| **Pendiente** | Factura en cola de procesamiento |
| **Correcto** | Factura aceptada por la AEAT |
| **Error** | Factura rechazada o con errores |
| **Anulado** | Factura anulada correctamente |

## Cron Jobs

El módulo incluye un cron que se ejecuta cada **5 minutos** para:
- Verificar el estado de facturas pendientes
- Actualizar automáticamente los estados
- Descargar códigos QR y huellas

## Log de API

Para ver todas las llamadas a la API:

1. Ir a: **Verifacti > Configuración > Log API**
2. Ver:
   - Fecha y hora de cada llamada
   - Método (GET, POST, PUT)
   - Endpoint llamado
   - Código de estado HTTP
   - Duración de la llamada
   - Request y Response completos
   - Errores si los hubo

## Casos de Uso Comunes

### Factura Normal con IVA 21%

```
Serie: A
Número: 00001
Tipo: F1
Cliente: [Cliente con NIF]
Descripción: Prestación de servicios

Línea 1:
  Base Imponible: 1000.00
  Tipo Impositivo: 21
  Cuota Repercutida: 210.00
  Impuesto: 01 (IVA)
  Calificación: S1
  Clave Régimen: 01

Importe Total: 1210.00
```

### Factura con Múltiples IVAs

```
Serie: B
Número: 00002
Tipo: F1
Cliente: [Cliente con NIF]
Descripción: Venta de productos

Línea 1 (Libros - IVA 4%):
  Base Imponible: 100.00
  Tipo Impositivo: 4
  Cuota Repercutida: 4.00

Línea 2 (Electrónica - IVA 21%):
  Base Imponible: 500.00
  Tipo Impositivo: 21
  Cuota Repercutida: 105.00

Importe Total: 709.00
```

### Factura Simplificada

```
Serie: T
Número: 00123
Tipo: F2
Descripción: Ticket de venta

Línea 1:
  Base Imponible: 50.00
  Tipo Impositivo: 21
  Cuota Repercutida: 10.50

Importe Total: 60.50

Nota: No requiere NIF ni Nombre del cliente
```

## Preguntas Frecuentes

### ¿Puedo gestionar facturas de múltiples emisores/NIFs?

Sí, el módulo soporta arquitectura multi-proveedor. Cada proveedor tiene su propia API Key de Verifacti y puede emitir facturas de forma independiente.

### ¿Necesito certificado digital?

No, este módulo usa la API de Verifacti que gestiona los certificados por ti.

### ¿Cuánto cuesta Verifacti?

El módulo es **gratuito y open source**. Verifacti tiene:
- **Entorno de test**: Gratis
- **Entorno de producción**: Requiere suscripción (consultar precios en https://www.verifacti.com/pricing)

### ¿Puedo usar un servidor VeriFactu propio en vez de Verifacti SaaS?

Sí. Contáctanos en oak.soft.develop@gmail.com y te damos acceso a nuestra versión
con servidor propio, sin depender de un tercero.

### ¿Puedo usar este módulo para producción?

Sí, una vez que tengas una API Key de producción de Verifacti y VeriFactu esté en producción (previsto para 2026).

### ¿Qué pasa si se cae Verifacti?

Las facturas se encolan en el sistema. El cron las reintentará automáticamente.

### ¿Puedo ver el código QR de la factura?

Sí, una vez la factura esté en estado **Correcto**, el código QR se muestra en la pestaña **Estado Verifacti**.

### ¿Se integra con el módulo de facturación de Odoo?

Este módulo es independiente y gestiona sus propias facturas VeriFactu. No está integrado directamente con `account.move`.

## Soporte y Contribuciones

- **Repositorio**: https://github.com/oak-soft-dev/verifacti-api
- **Bugs y Sugerencias**: https://github.com/oak-soft-dev/verifacti-api/issues
- **Documentación Verifacti**: https://www.verifacti.com/docs
- **Email**: oak.soft.develop@gmail.com

## Licencia

AGPL-3 - Completamente gratuito y open source

## Autor

Oak Soft - https://github.com/oak-soft-dev

## Créditos

- API de Verifacti: https://www.verifacti.com
- Normativa VeriFactu AEAT: https://sede.agenciatributaria.gob.es
