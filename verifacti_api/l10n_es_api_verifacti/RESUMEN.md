Qué pedir al cliente vs qué haces tú

Pedir al cliente (obligado tributario)

1. NIF y razón social exactos del emisor de facturas (deben coincidir con el certificado).
2. Certificado digital en PKCS#12 (.p12/.pfx) + contraseña:
  - Sociedad → certificado de representante de persona jurídica (FNMT).
  - Autónomo → certificado de persona física.
  - Ojo: v1 no soporta colaborador social/apoderado (bloque Representante no implementado) — el cert debe ser del propio NIF emisor.
3. Series de facturación que usa (para no colisionar y saber qué series van a VeriFactu).
4. Si es sector especial (hostelería, comercio minorista...) → afecta al límite de factura simplificada (3.000€ vs 400€) en el cliente verifacti_api.
5. Fecha de arranque — desde cuándo se registra (VeriFactu no es retroactivo).

Qué haces tú (Oak Soft, productor del software)

1. Desplegar el servidor: instancia con dbfilter de una BD (o X-Odoo-Dbfilter en el proxy) — sin esto las rutas públicas dan 404.
2. Crear el emisor (VeriFactu Server → Emisores): NIF cliente + subir su P12 + entorno test primero.
3. Rellenar la pestaña Sistema Informático del emisor — estos datos son TUYOS, no del cliente:
  - SI: Nombre productor → Oak Soft
  - SI: NIF productor → el NIF de tu empresa
  - SI: Nombre sistema / SI: Id sistema (2 chars) / SI: Versión
  - Nº instalación se autogenera
  - Solo VeriFactu = S, multi-OT según despliegue (S si un servidor sirve a varios clientes)
4. Configurar el cliente: Ajustes → Verifacti → proveedor propio + URL + API key del emisor → Probar Conexión.
5. Probar en test (factura real → Correcto con CSV) → cambiar entorno a producción con el cert real.

La declaración responsable

Qué es: documento exigido por el art. 13 del RD 1007/2023 y la Orden HAC/1177/2024 donde el productor del software (tú, Oak Soft — no el cliente) certifica bajo su responsabilidad que el sistema cumple el reglamento VeriFactu.

Puntos clave:

- No se presenta a la AEAT. Se redacta, se firma, y se conserva. Debes tenerla disponible para la AEAT si la pide y entregarla/ponerla a disposición de cada cliente que use el software.
- Una por versión del sistema: si cambias SI: Versión, nueva declaración.
- Contenido mínimo (Orden HAC/1177/2024): nombre y NIF del productor, nombre del sistema, código identificador, versión, componentes hw/sw si aplica, tipo de uso (solo VeriFactu), capacidad multi-obligado, fecha y lugar, firma.
- El módulo ya te da los datos montados: GET /verifactu/declaracion_responsable devuelve todo el bloque Sistema Informático + texto de declaración — te sirve de base para el documento formal en PDF que firmas.
- Esos mismos datos viajan en cada registro enviado a la AEAT (bloque SistemaInformatico del XML), así que lo que declares y lo que envíe el sistema deben coincidir — por eso se configuran una vez en el emisor.

Resumen brutal: el cliente pone su NIF y su certificado; tú pones el software, el despliegue y la declaración responsable firmada como productor.