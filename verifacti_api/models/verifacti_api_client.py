# -*- coding: utf-8 -*-

from odoo import models, api, _
from odoo.exceptions import UserError
import requests
import json
import time
import logging

_logger = logging.getLogger(__name__)


class VerifactiApiClient(models.AbstractModel):
    """Cliente para interactuar con la API de Verifacti"""

    _name = "verifacti.api.client"
    _description = "Cliente API de Verifacti"

    # Valores permitidos por VeriFactu según normativa AEAT
    VALORES_TIPO_IMPOSITIVO_PERMITIDOS = [
        0,
        0.5,
        1.75,
        2,
        4,
        5,
        7,
        9.5,
        10,
        13.5,
        15,
        20,
        21,
    ]

    @api.model
    def _get_param_key(self, company_id, param):
        """Generar clave de parámetro por compañía"""
        return f'verifacti_api.company_{company_id}.{param}'

    @api.model
    def _get_config(self):
        """Obtener configuración de Verifacti desde ir.config_parameter por compañía

        Si hay un verifacti_company_id en el contexto, usa esa compañía.
        Si no, usa la compañía actual.
        """
        # Verificar si hay una compañía específica en el contexto
        company_id = self.env.context.get("verifacti_company_id")

        if company_id:
            company = self.env["res.company"].browse(company_id)
        else:
            # Usar compañía actual
            company = self.env.company

        # Obtener configuración desde ir.config_parameter
        IrConfigParameter = self.env['ir.config_parameter'].sudo()

        # Proveedor: Verifacti SaaS o servidor propio (l10n_es_api_verifacti)
        provider = IrConfigParameter.get_param(
            self._get_param_key(company.id, 'provider'), default='verifacti'
        )

        # VALIDACIÓN MEJORADA DE API KEY
        key_param = 'propio_api_key' if provider == 'propio' else 'api_key'
        api_key = IrConfigParameter.get_param(self._get_param_key(company.id, key_param), default='')

        if not api_key:
            raise UserError(
                _(
                    "❌ API Key no configurada\n\n"
                    "Compañía: %s\n"
                    "Proveedor: %s\n\n"
                    "Pasos para configurar:\n"
                    "1. Ir a Ajustes → Verifacti\n"
                    "2. Introducir la API Key del proveedor seleccionado\n"
                    "3. Guardar y hacer clic en 'Probar Conexión'"
                )
                % (company.name, provider)
            )

        # NORMALIZAR: Eliminar espacios en blanco y saltos de línea
        api_key = api_key.strip().replace('\n', '').replace('\r', '').replace(' ', '')

        # VALIDAR longitud mínima
        if len(api_key) < 20:
            raise UserError(
                _(
                    "❌ API Key inválida (muy corta)\n\n"
                    "Compañía: %s\n"
                    "Longitud actual: %s caracteres\n"
                    "Longitud mínima: 20 caracteres\n\n"
                    "💡 Verifica tu API Key en: https://www.verifacti.com/dashboard"
                )
                % (company.name, len(api_key))
            )

        # Log seguro (muestra solo inicio y fin de la key)
        _logger.debug(
            "API Key validada para %s: %s...%s (%s caracteres)",
            company.name,
            api_key[:8],
            api_key[-4:],
            len(api_key)
        )

        # Obtener resto de configuración
        if provider == 'propio':
            api_url = IrConfigParameter.get_param(
                self._get_param_key(company.id, 'propio_api_url'),
                default='http://localhost:8069'
            ) or 'http://localhost:8069'
        else:
            api_url = IrConfigParameter.get_param(
                self._get_param_key(company.id, 'api_url'),
                default='https://api.verifacti.com'
            ) or 'https://api.verifacti.com'
        api_url = api_url.strip().rstrip('/')
        max_retries = int(IrConfigParameter.get_param(
            self._get_param_key(company.id, 'max_retries'),
            default='3'
        ))
        retry_delay = int(IrConfigParameter.get_param(
            self._get_param_key(company.id, 'retry_delay'),
            default='2'
        ))

        return {
            "provider": provider,
            "api_key": api_key,  # Ya normalizada y validada
            "api_url": api_url,
            "company_name": company.name,
            "max_retries": max(1, min(10, max_retries)),  # Entre 1 y 10
            "retry_delay": max(1, min(30, retry_delay)),  # Entre 1 y 30
        }

    @api.model
    def _make_request(
        self,
        method,
        endpoint,
        data=None,
        params=None,
        max_retries=None,
        retry_delay=None,
    ):
        """Realizar petición HTTP con mejor manejo de errores"""
        config = self._get_config()
        max_retries = max_retries or config.get("max_retries", 3)
        retry_delay = retry_delay or config.get("retry_delay", 2)

        if not config["api_key"]:
            raise UserError(_("No se ha configurado la API Key de Verifacti"))

        url = f"{config['api_url']}{endpoint}"
        headers = {
            "Authorization": f"Bearer {config['api_key']}",
            "Content-Type": "application/json",
        }

        for attempt in range(max_retries):
            start_time = time.time()
            response_data = None
            status_code = None

            try:
                _logger.info(
                    f"API Verifacti: {method} {url} (intento {attempt + 1}/{max_retries})"
                )

                response = requests.request(
                    method=method,
                    url=url,
                    json=data,
                    params=params,
                    headers=headers,
                    timeout=30,
                )

                status_code = response.status_code
                duration = (time.time() - start_time) * 1000

                try:
                    response_data = response.json()
                except:
                    response_data = {"text": response.text}

                # Incluir status_code en la respuesta
                if isinstance(response_data, dict):
                    response_data["status_code"] = status_code

                # Loggear SIEMPRE la llamada (éxito o error)
                self.env["verifacti.api.log"].sudo().log_api_call(
                    endpoint=endpoint,
                    method=method,
                    request_data=data,
                    response_data=response_data,
                    status_code=status_code,
                    duration=duration,
                )

                # Para errores HTTP 4xx y 5xx
                if status_code >= 400:
                    # Extraer mensaje detallado
                    error_msg = (
                        response_data.get("mensaje")
                        or response_data.get("error")
                        or response.text
                        or f"HTTP {status_code}"
                    )

                    # Crear mensaje de error completo
                    full_error = f"HTTP {status_code}: {error_msg}"

                    # Si hay detalles adicionales, incluirlos
                    if isinstance(response_data, dict):
                        if "detalles" in response_data:
                            full_error += f"\nDetalles: {json.dumps(response_data['detalles'], ensure_ascii=False)}"
                        if "errores" in response_data:
                            full_error += f"\nErrores: {json.dumps(response_data['errores'], ensure_ascii=False)}"

                    _logger.error(
                        "API VeriFactu respondió con error\n"
                        "Status: %s | Endpoint: %s\n"
                        "Request: %s\n"
                        "Response: %s",
                        status_code,
                        endpoint,
                        (
                            json.dumps(data, indent=2, ensure_ascii=False)
                            if data
                            else "N/A"
                        ),
                        json.dumps(response_data, indent=2, ensure_ascii=False),
                    )

                    raise UserError(full_error)

                _logger.info(f"API Verifacti: Éxito en intento {attempt + 1}")

                return response_data

            except UserError:
                # Re-lanzar errores HTTP (ya procesados arriba)
                raise

            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
            ) as e:
                error = str(e)
                duration = (time.time() - start_time) * 1000

                _logger.warning(
                    f"API Verifacti: Error de conexión en intento {attempt + 1}/{max_retries}"
                )

                self.env["verifacti.api.log"].sudo().log_api_call(
                    endpoint=endpoint,
                    method=method,
                    request_data=data,
                    response_data=response_data,
                    status_code=0,
                    error=f"Intento {attempt + 1}/{max_retries}: {error}",
                    duration=duration,
                )

                # Reintentar si no es el último intento
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (attempt + 1)
                    _logger.info(
                        f"Esperando {wait_time}s antes del siguiente intento..."
                    )
                    time.sleep(wait_time)
                    continue

                # Último intento: lanzar error
                raise UserError(
                    _(
                        "No se pudo conectar con la API de Verifacti después de %s intentos.\n\n"
                        "Posibles causas:\n"
                        "1. Problemas de red o DNS\n"
                        "2. URL incorrecta: %s\n"
                        "3. Firewall bloqueando la conexión\n\n"
                        "Error: %s"
                    )
                    % (max_retries, url, error)
                )

            except Exception as e:
                error = str(e)
                duration = (time.time() - start_time) * 1000

                self.env["verifacti.api.log"].sudo().log_api_call(
                    endpoint=endpoint,
                    method=method,
                    request_data=data,
                    response_data=response_data,
                    status_code=status_code or 0,
                    error=error,
                    duration=duration,
                )

                raise UserError(_("Error inesperado en llamada a API: %s") % error)

    # ==================== VERIFACTU API ENDPOINTS ====================

    @api.model
    def health_check(self):
        """GET /verifactu/health - Estado de la API"""
        return self._make_request("GET", "/verifactu/health")

    @api.model
    def get_invoice_status(self, serie, numero, fecha_expedicion, fecha_operacion=None):
        """POST /verifactu/status - Consultar estado de una factura en AEAT"""
        payload = {
            "serie": serie,
            "numero": numero,
            "fecha_expedicion": fecha_expedicion,
        }
        if fecha_operacion:
            payload["fecha_operacion"] = fecha_operacion
        return self._make_request("POST", "/verifactu/status", data=payload)

    @api.model
    def get_registration_status(self, uuid):
        """GET /verifactu/status?uuid=xxx - Consultar estado de un registro

        Returns:
            dict: Respuesta de la API con status_code incluido

        Raises:
            UserError: Si hay error HTTP, incluyendo el status_code en el mensaje
        """
        try:
            response = self._make_request(
                "GET", "/verifactu/status", params={"uuid": uuid}
            )
            return response
        except UserError as e:
            # Re-lanzar el error tal cual para que se capture el status_code
            raise

    @api.model
    def create_invoice(self, invoice_data):
        """POST /verifactu/create - Crear una factura nueva"""
        return self._make_request("POST", "/verifactu/create", data=invoice_data)

    @api.model
    def create_invoices_bulk(self, invoices_data):
        """POST /verifactu/create_bulk - Crear facturas en lote (hasta 50)"""
        if len(invoices_data) > 50:
            raise UserError(_("Solo se pueden enviar hasta 50 facturas en lote"))
        return self._make_request("POST", "/verifactu/create_bulk", data=invoices_data)

    @api.model
    def modify_invoice(self, invoice_data):
        """PUT /verifactu/modify - Subsanar una factura existente"""
        return self._make_request("PUT", "/verifactu/modify", data=invoice_data)

    @api.model
    def cancel_invoice(
        self,
        serie,
        numero,
        fecha_expedicion,
        rechazo_previo="N",
        sin_registro_previo="N",
        incidencia=None,
    ):
        """POST /verifactu/cancel - Anular una factura"""
        payload = {
            "serie": serie,
            "numero": numero,
            "fecha_expedicion": fecha_expedicion,
            "rechazo_previo": rechazo_previo,
            "sin_registro_previo": sin_registro_previo,
        }
        if incidencia:
            payload["incidencia"] = incidencia
        return self._make_request("POST", "/verifactu/cancel", data=payload)

    @api.model
    def list_invoices(
        self,
        ejercicio,
        periodo,
        serie=None,
        numero=None,
        rango_fecha_expedicion=None,
        fecha_expedicion=None,
        paginacion=None,
    ):
        """POST /verifactu/list - Listar facturas presentadas en AEAT"""
        payload = {"ejercicio": ejercicio, "periodo": periodo}
        if serie:
            payload["serie"] = serie
        if numero:
            payload["numero"] = numero
        if rango_fecha_expedicion:
            payload["rango_fecha_expedicion"] = rango_fecha_expedicion
        if fecha_expedicion:
            payload["fecha_expedicion"] = fecha_expedicion
        if paginacion:
            payload["paginacion"] = paginacion
        return self._make_request("POST", "/verifactu/list", data=payload)

    @api.model
    def export_xmls(self, ejercicio, periodo, token=None):
        """POST /verifactu/export - Exportar XMLs en lotes"""
        payload = {"ejercicio": ejercicio, "periodo": periodo}
        if token:
            payload["token"] = token
        return self._make_request("POST", "/verifactu/export", data=payload)

    @api.model
    def download_xml(self, serie, numero):
        """POST /verifactu/downloadXML - Descargar XMLs de una factura"""
        return self._make_request(
            "POST", "/verifactu/downloadXML", data={"serie": serie, "numero": numero}
        )

    @api.model
    def get_declaracion_responsable(self):
        """URL del PDF de declaración responsable de Verifacti (documento estático, no requiere llamada a la API)"""
        return "https://storage.googleapis.com/verifacti_non_sensitive/declaracion/1.0.0.pdf"

    @api.model
    def test_connection(self):
        """Probar conexión con la API"""
        if not self._get_config()["api_key"]:
            raise UserError(_("Debe configurar la API Key"))

        try:
            response = self.health_check()
            if response.get("estado") == "OK":
                return {
                    "success": True,
                    "message": _("Conexión exitosa"),
                    "nif": response.get("nif"),
                    "entorno": response.get("entorno"),
                }
            raise UserError(_("Respuesta inesperada de la API"))
        except Exception as e:
            raise UserError(_("Error al probar conexión: %s") % str(e))

    # ==================== HELPER METHODS ====================

    @api.model
    def normalize_tipo_impositivo(self, tipo_impositivo):
        """Normalizar tipo impositivo a valor permitido por VeriFactu

        Args:
            tipo_impositivo: Valor decimal del tipo impositivo

        Returns:
            float: Valor más cercano de la lista de valores permitidos
        """
        if tipo_impositivo is None:
            return None

        # Redondear a 2 decimales
        tipo_rounded = round(float(tipo_impositivo), 2)

        # Si ya está en la lista, devolverlo directamente
        if tipo_rounded in self.VALORES_TIPO_IMPOSITIVO_PERMITIDOS:
            return tipo_rounded

        # Buscar el valor más cercano
        valor_cercano = min(
            self.VALORES_TIPO_IMPOSITIVO_PERMITIDOS, key=lambda x: abs(x - tipo_rounded)
        )

        # Si la diferencia es mayor a 0.5%, registrar advertencia
        if abs(tipo_rounded - valor_cercano) > 0.5:
            self.env["verifacti.api.log"].sudo().create(
                {
                    "endpoint": "/verifactu/normalize",
                    "method": "INTERNAL",
                    "status_code": 0,
                    "error": f"ADVERTENCIA: Tipo impositivo {tipo_rounded}% normalizado a {valor_cercano}%",
                }
            )

        return valor_cercano

    @api.model
    def prepare_invoice_line(
        self,
        base_imponible,
        tipo_impositivo=None,
        cuota_repercutida=None,
        impuesto="01",
        calificacion_operacion="S1",
        clave_regimen="01",
        operacion_exenta=None,
        base_imponible_a_coste=None,
        tipo_recargo_equivalencia=None,
        cuota_recargo_equivalencia=None,
    ):
        """Preparar línea de factura según formato API Verifacti

        Args:
            base_imponible: Base imponible de la línea
            tipo_impositivo: Tipo impositivo (será normalizado automáticamente)
            cuota_repercutida: Cuota repercutida
            impuesto: Tipo de impuesto (01=IVA, 02=IPSI, 03=IGIC, 05=Otros)
            calificacion_operacion: S1, S2, N1, N2
            clave_regimen: Clave de régimen (01-20)
            operacion_exenta: E1-E6 si es operación exenta
            base_imponible_a_coste: Base imponible a coste
            tipo_recargo_equivalencia: Tipo de recargo
            cuota_recargo_equivalencia: Cuota de recargo
        """
        line = {
            "base_imponible": str(base_imponible),
            "impuesto": impuesto,
        }

        # Normalizar tipo_impositivo a valores permitidos
        if tipo_impositivo is not None:
            tipo_normalizado = self.normalize_tipo_impositivo(tipo_impositivo)
            if tipo_normalizado is not None:
                line["tipo_impositivo"] = str(tipo_normalizado)

        if cuota_repercutida is not None:
            line["cuota_repercutida"] = str(round(float(cuota_repercutida), 2))

        if calificacion_operacion:
            line["calificacion_operacion"] = calificacion_operacion
        if clave_regimen:
            line["clave_regimen"] = clave_regimen
        if operacion_exenta:
            line["operacion_exenta"] = operacion_exenta
        if base_imponible_a_coste is not None:
            line["base_imponible_a_coste"] = str(base_imponible_a_coste)

        # Normalizar tipo_recargo_equivalencia también
        if tipo_recargo_equivalencia is not None:
            tipo_recargo_norm = self.normalize_tipo_impositivo(
                tipo_recargo_equivalencia
            )
            if tipo_recargo_norm is not None:
                line["tipo_recargo_equivalencia"] = str(tipo_recargo_norm)

        if cuota_recargo_equivalencia is not None:
            line["cuota_recargo_equivalencia"] = str(
                round(float(cuota_recargo_equivalencia), 2)
            )

        return line

    @api.model
    def format_date(self, date_obj):
        """Convertir fecha de Odoo a formato Verifacti (DD-MM-YYYY)"""
        if not date_obj:
            return None
        return date_obj.strftime("%d-%m-%Y")
