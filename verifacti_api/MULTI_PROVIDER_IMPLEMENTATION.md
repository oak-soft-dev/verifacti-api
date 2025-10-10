# Implementación Multi-Proveedor en Verifacti API

## Resumen

El módulo `verifacti_api` ha sido actualizado para soportar arquitectura multi-proveedor (multi-tenant), permitiendo gestionar múltiples emisores de facturas, cada uno con su propia API Key de Verifacti.

## Cambios Realizados

### 1. Nuevo Modelo: `verifacti.supplier`

**Archivo**: `models/verifacti_supplier.py`

Modelo para gestionar proveedores/emisores de facturas:

**Campos principales**:
- `name`: Nombre o razón social del proveedor
- `nif`: NIF/CIF del emisor (único)
- `api_key`: API Key de Verifacti para este NIF específico
- `api_url`: URL de la API (default: https://api.verifacti.com)
- `environment`: Test o Producción
- `invoice_ids`: Facturas emitidas por este proveedor
- Estadísticas: total de facturas, correctas, con error, última factura

**Funcionalidades**:
- Validación de NIF
- Prueba de conexión con Verifacti usando su API Key específica
- Visualización de facturas por proveedor
- Seguimiento de estadísticas

### 2. Modificación: Modelo `verifacti.invoice`

**Archivo**: `models/verifacti_invoice.py`

**Cambios principales**:

1. **Nuevo campo obligatorio**:
   ```python
   supplier_id = fields.Many2one(
       'verifacti.supplier',
       string='Proveedor Emisor',
       required=True,
       ondelete='restrict'
   )
   ```

2. **Restricción SQL actualizada**:
   ```python
   _sql_constraints = [
       ('serie_numero_fecha_supplier_unique',
        'unique(supplier_id, serie, numero, fecha_expedicion)',
        'Ya existe una factura de este proveedor con la misma serie, número y fecha de expedición'),
   ]
   ```

3. **Métodos actualizados para pasar contexto del proveedor**:
   - `action_send_to_verifacti()`: Usa API Key del proveedor al enviar
   - `action_check_registration_status()`: Usa API Key del proveedor al verificar
   - `action_check_invoice_status()`: Usa API Key del proveedor al consultar
   - `action_download_xmls()`: Usa API Key del proveedor al descargar
   - `action_cancel_invoice()`: Usa API Key del proveedor al anular
   - `cron_check_pending_registrations()`: Usa API Key del proveedor correspondiente

   **Patrón utilizado**:
   ```python
   response = api_client.with_context(
       verifacti_supplier_id=self.supplier_id.id
   ).create_invoice(invoice_data)
   ```

### 3. Modificación: Cliente API `verifacti.api.client`

**Archivo**: `models/verifacti_api_client.py`

**Cambio clave**: Método `_get_config()` actualizado para soportar múltiples proveedores:

```python
@api.model
def _get_config(self):
    """Obtener configuración de Verifacti

    Si hay un supplier_id en el contexto, usa su configuración específica.
    Si no, usa la configuración global (retrocompatibilidad).
    """
    # Verificar si hay un proveedor específico en el contexto (modo multi-tenant)
    supplier_id = self._context.get('verifacti_supplier_id')
    if supplier_id:
        supplier = self.env['verifacti.supplier'].browse(supplier_id)
        if supplier.exists():
            return {
                'api_key': supplier.api_key,
                'api_url': supplier.api_url or 'https://api.verifacti.com',
                'environment': supplier.environment or 'test',
                'supplier_nif': supplier.nif,
                'supplier_name': supplier.name,
            }

    # Fallback a configuración global (retrocompatibilidad)
    ICP = self.env['ir.config_parameter'].sudo()
    return {
        'api_key': ICP.get_param('verifacti_api.api_key', ''),
        'api_url': ICP.get_param('verifacti_api.api_url', 'https://api.verifacti.com'),
        'environment': ICP.get_param('verifacti_api.environment', 'test'),
    }
```

### 4. Nuevas Vistas

**Archivo**: `views/verifacti_supplier_views.xml`

Vistas completas para gestión de proveedores:
- Vista de formulario con botón "Probar Conexión"
- Vista de lista con estadísticas
- Vista kanban para visualización móvil
- Vista de búsqueda con filtros
- Acción y menú en Configuración

**Archivo actualizado**: `views/verifacti_invoice_views.xml`

Actualizadas para incluir campo `supplier_id`:
- Vista de formulario: Campo proveedor en primera posición
- Vista de lista: Columna de proveedor
- Vista de búsqueda: Campo de búsqueda y filtro por proveedor

### 5. Seguridad y Accesos

**Archivo**: `security/ir.model.access.csv`

Nuevos accesos para el modelo `verifacti.supplier`:
```csv
access_verifacti_supplier_user,access_verifacti_supplier_user,model_verifacti_supplier,base.group_user,1,0,0,0
access_verifacti_supplier_manager,access_verifacti_supplier_manager,model_verifacti_supplier,base.group_system,1,1,1,1
```

- Usuarios regulares: Solo lectura
- Administradores: Control total

### 6. Datos de Demostración

**Archivo nuevo**: `data/demo_suppliers.xml`

Dos proveedores de demostración:
- Mi Empresa SL (B12345678)
- Otra Empresa SA (A87654321)

**Archivo actualizado**: `data/demo_invoices.xml`

Facturas demo actualizadas para vincularse a proveedores demo.

### 7. Documentación

**Archivo**: `README.md`

Actualizado con:
- Sección sobre arquitectura multi-proveedor
- Instrucciones de configuración de múltiples proveedores
- Casos de uso para SaaS y gestorías
- FAQ sobre gestión multi-NIF

**Archivo nuevo**: `MULTI_PROVIDER_IMPLEMENTATION.md` (este archivo)

Documentación técnica completa de los cambios.

## Casos de Uso

### 1. Gestoría con Múltiples Clientes

Una gestoría puede gestionar facturas de múltiples clientes, cada uno con su propio NIF y API Key de Verifacti.

```
Proveedor 1: Cliente A (NIF: B12345678, API Key: sk_xxxxx)
  ├── Factura A-001
  ├── Factura A-002
  └── Factura A-003

Proveedor 2: Cliente B (NIF: A87654321, API Key: sk_yyyyy)
  ├── Factura B-001
  └── Factura B-002
```

### 2. Aplicación SaaS Multi-Tenant

Una aplicación SaaS puede dar servicio a múltiples empresas, cada una emitiendo sus propias facturas.

```
Tenant 1: Empresa X
  - API Key propia
  - Facturas independientes
  - Estadísticas propias

Tenant 2: Empresa Y
  - API Key propia
  - Facturas independientes
  - Estadísticas propias
```

### 3. Empresa con Múltiples NIFs

Una empresa con varios NIFs puede gestionar las facturas de cada uno de forma independiente.

```
NIF Principal: B11111111
NIF Sucursal 1: B22222222
NIF Sucursal 2: B33333333
```

## Flujo de Trabajo

1. **Configuración**:
   - Registrar cada NIF en Verifacti.com
   - Obtener API Key para cada NIF
   - Crear proveedor en Odoo con NIF y API Key
   - Probar conexión

2. **Emisión de Factura**:
   - Crear factura seleccionando el proveedor emisor
   - El sistema automáticamente usa la API Key del proveedor seleccionado
   - La factura se envía a Verifacti con las credenciales correctas

3. **Verificación y Gestión**:
   - Todas las operaciones (verificar, descargar XMLs, anular) usan la API Key del proveedor
   - Estadísticas separadas por proveedor
   - Búsqueda y filtrado por proveedor

## Retrocompatibilidad

El módulo mantiene retrocompatibilidad con configuración global:
- Si no se especifica proveedor en el contexto, usa configuración global
- Permite migración gradual de configuración global a multi-proveedor

## Validaciones

1. **Obligatoriedad de proveedor**: Toda factura debe tener un proveedor asignado
2. **Unicidad de NIF**: No pueden existir dos proveedores con el mismo NIF
3. **Unicidad de factura**: No pueden existir dos facturas del mismo proveedor con la misma (serie, número, fecha)
4. **API Key requerida**: Todo proveedor debe tener una API Key configurada

## Archivos Modificados

### Modelos
- ✅ `models/__init__.py` - Añadido import de verifacti_supplier
- ✅ `models/verifacti_supplier.py` - NUEVO modelo
- ✅ `models/verifacti_invoice.py` - Añadido supplier_id y contexto
- ✅ `models/verifacti_api_client.py` - Actualizado _get_config()

### Vistas
- ✅ `views/verifacti_supplier_views.xml` - NUEVO archivo
- ✅ `views/verifacti_invoice_views.xml` - Añadido campo supplier_id

### Seguridad
- ✅ `security/ir.model.access.csv` - Añadidos accesos para supplier

### Datos
- ✅ `data/demo_suppliers.xml` - NUEVO archivo
- ✅ `data/demo_invoices.xml` - Vinculado a suppliers

### Documentación
- ✅ `README.md` - Actualizado con info multi-proveedor
- ✅ `MULTI_PROVIDER_IMPLEMENTATION.md` - NUEVO archivo (este)

### Manifest
- ✅ `__manifest__.py` - Añadido supplier views y demo data

## Pruebas Recomendadas

1. **Crear múltiples proveedores**:
   - Con diferentes NIFs
   - Probar conexión de cada uno

2. **Emitir facturas de diferentes proveedores**:
   - Verificar que usan la API Key correcta
   - Verificar unicidad por proveedor

3. **Verificar estadísticas**:
   - Cada proveedor tiene sus propias estadísticas
   - Total de facturas separado por proveedor

4. **Cron de verificación**:
   - Verificar que usa la API Key correcta para cada factura pendiente

5. **Operaciones de factura**:
   - Verificar estado (registro y AEAT)
   - Descargar XMLs
   - Anular factura

## Mejoras Futuras

1. **Permisos por proveedor**: Permitir que usuarios solo vean facturas de ciertos proveedores
2. **Dashboard por proveedor**: Panel de control con métricas por proveedor
3. **Facturación en lote por proveedor**: Enviar múltiples facturas del mismo proveedor
4. **Configuración de series por proveedor**: Series de facturación específicas por proveedor
5. **Integración con account.move**: Sincronización automática con módulo de contabilidad

## Soporte

Para dudas o problemas con la implementación multi-proveedor:
- Email: oak.soft@telefonica.net
- GitHub: https://github.com/oak-soft-dev/verifacti-api

---

**Fecha de implementación**: 2025-01-09
**Versión del módulo**: 16.0.1.0.0
**Autor**: Oak Soft
