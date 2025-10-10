# -*- coding: utf-8 -*-

from odoo import models, api, _
from odoo.exceptions import UserError
import requests
import json
import time


class VerifactiApiClient(models.AbstractModel):
    """Cliente para interactuar con la API de Verifacti"""
    _name = 'verifacti.api.client'
    _description = 'Cliente API de Verifacti'

    @api.model
    def _get_config(self):
        """Obtener configuración de Verifacti

        Si hay un api_config_id en el contexto, usa esa configuración específica.
        Si no, usa la configuración por defecto de la compañía actual.
        """
        # Verificar si hay una configuración de API específica en el contexto
        api_config_id = self._context.get('verifacti_api_config_id')

        if api_config_id:
            api_config = self.env['verifacti.api.config'].browse(api_config_id)
            if api_config.exists():
                return {
                    'api_key': api_config.api_key,
                    'api_url': api_config.api_url or 'https://api.verifacti.com',
                    'config_name': api_config.name,
                    'company_name': api_config.company_id.name,
                }

        # Fallback: usar configuración por defecto de la compañía actual
        company = self.env.company
        if company.verifacti_default_api_config_id:
            api_config = company.verifacti_default_api_config_id
            return {
                'api_key': api_config.api_key,
                'api_url': api_config.api_url or 'https://api.verifacti.com',
                'config_name': api_config.name,
                'company_name': api_config.company_id.name,
            }

        # Si no hay configuración, lanzar error
        raise UserError(
            _('No se ha encontrado una configuración de API Verifacti.\n'
              'Por favor, configure al menos una configuración de API en:\n'
              'Verifacti → Configuración → Configuraciones API')
        )

    @api.model
    def _make_request(self, method, endpoint, data=None, params=None):
        """Realizar petición HTTP a la API de Verifacti"""
        config = self._get_config()

        if not config['api_key']:
            raise UserError(_('No se ha configurado la API Key de Verifacti'))

        url = f"{config['api_url']}{endpoint}"
        headers = {
            'Authorization': f"Bearer {config['api_key']}",
            'Content-Type': 'application/json'
        }

        start_time = time.time()
        error = None
        response_data = None
        status_code = None

        try:
            response = requests.request(
                method=method,
                url=url,
                json=data,
                params=params,
                headers=headers,
                timeout=30
            )

            status_code = response.status_code
            duration = (time.time() - start_time) * 1000  # ms

            # Intentar parsear respuesta JSON
            try:
                response_data = response.json()
            except:
                response_data = {'text': response.text}

            # Log de la llamada
            self.env['verifacti.api.log'].sudo().log_api_call(
                endpoint=endpoint,
                method=method,
                request_data=data,
                response_data=response_data,
                status_code=status_code,
                duration=duration
            )

            # Verificar errores HTTP
            response.raise_for_status()

            return response_data

        except requests.exceptions.RequestException as e:
            error = str(e)
            duration = (time.time() - start_time) * 1000

            # Intentar obtener detalles del error de la respuesta
            error_details = error
            if status_code and response_data:
                try:
                    error_details = f"{error}\n\nDetalles de la API: {json.dumps(response_data, indent=2)}"
                except:
                    error_details = f"{error}\n\nRespuesta: {response_data}"

            # Log del error
            self.env['verifacti.api.log'].sudo().log_api_call(
                endpoint=endpoint,
                method=method,
                request_data=data,
                response_data=response_data,
                status_code=status_code or 0,
                error=error,
                duration=duration
            )

            raise UserError(_('Error en llamada a API: %s') % error_details)

    # ==================== VERIFACTU API ENDPOINTS ====================

    @api.model
    def health_check(self):
        """GET /verifactu/health - Estado de la API"""
        return self._make_request('GET', '/verifactu/health')

    @api.model
    def get_invoice_status(self, serie, numero, fecha_expedicion, fecha_operacion=None):
        """POST /verifactu/status - Consultar estado de una factura en AEAT

        Args:
            serie: Serie de la factura
            numero: Número de la factura
            fecha_expedicion: Fecha de expedición (formato DD-MM-YYYY)
            fecha_operacion: Fecha de operación (formato DD-MM-YYYY), opcional
        """
        payload = {
            'serie': serie,
            'numero': numero,
            'fecha_expedicion': fecha_expedicion,
        }

        if fecha_operacion:
            payload['fecha_operacion'] = fecha_operacion

        return self._make_request('POST', '/verifactu/status', data=payload)

    @api.model
    def get_registration_status(self, uuid):
        """GET /verifactu/status?uuid=xxx - Consultar estado de un registro de facturación

        Args:
            uuid: Identificador único del registro
        """
        params = {'uuid': uuid}
        return self._make_request('GET', '/verifactu/status', params=params)

    @api.model
    def create_invoice(self, invoice_data):
        """POST /verifactu/create - Crear una factura nueva

        Args:
            invoice_data: Diccionario con los datos de la factura según API Verifacti

        Returns:
            Dict con uuid, estado, url, qr, huella
        """
        return self._make_request('POST', '/verifactu/create', data=invoice_data)

    @api.model
    def create_invoices_bulk(self, invoices_data):
        """POST /verifactu/create_bulk - Crear facturas en lote (hasta 50)

        Args:
            invoices_data: Lista de diccionarios con datos de facturas

        Returns:
            Lista de dicts con uuid, estado, url, qr, huella para cada factura
        """
        if len(invoices_data) > 50:
            raise UserError(_('Solo se pueden enviar hasta 50 facturas en lote'))

        return self._make_request('POST', '/verifactu/create_bulk', data=invoices_data)

    @api.model
    def modify_invoice(self, invoice_data):
        """PUT /verifactu/modify - Subsanar una factura existente

        Args:
            invoice_data: Diccionario con los datos de la factura a subsanar

        Returns:
            Dict con uuid, estado, url, qr
        """
        return self._make_request('PUT', '/verifactu/modify', data=invoice_data)

    @api.model
    def cancel_invoice(self, serie, numero, fecha_expedicion, rechazo_previo='N',
                      sin_registro_previo='N', incidencia=None):
        """POST /verifactu/cancel - Anular una factura

        Args:
            serie: Serie de la factura
            numero: Número de la factura
            fecha_expedicion: Fecha de expedición (formato DD-MM-YYYY)
            rechazo_previo: 'N' o 'S' si fue rechazada previamente
            sin_registro_previo: 'N' o 'S' si no existe en AEAT
            incidencia: 'S' si hay incidencia

        Returns:
            Dict con uuid, estado
        """
        payload = {
            'serie': serie,
            'numero': numero,
            'fecha_expedicion': fecha_expedicion,
            'rechazo_previo': rechazo_previo,
            'sin_registro_previo': sin_registro_previo,
        }

        if incidencia:
            payload['incidencia'] = incidencia

        return self._make_request('POST', '/verifactu/cancel', data=payload)

    @api.model
    def list_invoices(self, ejercicio, periodo, serie=None, numero=None,
                     rango_fecha_expedicion=None, fecha_expedicion=None,
                     paginacion=None):
        """POST /verifactu/list - Listar facturas presentadas en AEAT

        Args:
            ejercicio: Ejercicio (YYYY)
            periodo: Periodo (MM)
            serie: Serie de la factura (opcional)
            numero: Número de la factura (opcional)
            rango_fecha_expedicion: Dict con 'desde' y 'hasta' (opcional)
            fecha_expedicion: Fecha de expedición (opcional)
            paginacion: Dict con 'num_serie' y 'fecha_expedicion' (opcional)

        Returns:
            Dict con 'paginacion' (N/S) y 'data' (lista de facturas)
        """
        payload = {
            'ejercicio': ejercicio,
            'periodo': periodo,
        }

        if serie:
            payload['serie'] = serie
        if numero:
            payload['numero'] = numero
        if rango_fecha_expedicion:
            payload['rango_fecha_expedicion'] = rango_fecha_expedicion
        if fecha_expedicion:
            payload['fecha_expedicion'] = fecha_expedicion
        if paginacion:
            payload['paginacion'] = paginacion

        return self._make_request('POST', '/verifactu/list', data=payload)

    @api.model
    def export_xmls(self, ejercicio, periodo, token=None):
        """POST /verifactu/export - Exportar XMLs en lotes

        Args:
            ejercicio: Ejercicio (YYYY)
            periodo: Periodo (MM)
            token: Token de paginación (opcional)

        Returns:
            Dict con 'urls' (lista de URLs de XMLs) y 'token' (para paginación)
        """
        payload = {
            'ejercicio': ejercicio,
            'periodo': periodo,
        }

        if token:
            payload['token'] = token

        return self._make_request('POST', '/verifactu/export', data=payload)

    @api.model
    def download_xml(self, serie, numero):
        """POST /verifactu/downloadXML - Descargar XMLs de una factura

        Args:
            serie: Serie de la factura
            numero: Número de la factura

        Returns:
            Lista de dicts con uuid, operacion, xml_req, xml_res
        """
        payload = {
            'serie': serie,
            'numero': numero,
        }

        return self._make_request('POST', '/verifactu/downloadXML', data=payload)

    @api.model
    def get_declaracion_responsable(self):
        """GET /verifactu/declaracion_responsable - Obtener declaración responsable

        Returns:
            Dict con 'url' y 'sistema_informatico' (nombre, id, version)
        """
        return self._make_request('GET', '/verifactu/declaracion_responsable')

    @api.model
    def test_connection(self):
        """Probar conexión con la API"""
        config = self._get_config()

        if not config['api_key']:
            raise UserError(_('Debe configurar la API Key'))

        try:
            response = self.health_check()

            if response.get('estado') == 'OK':
                return {
                    'success': True,
                    'message': _('Conexión exitosa'),
                    'nif': response.get('nif'),
                    'entorno': response.get('entorno'),
                }
            else:
                raise UserError(_('Respuesta inesperada de la API'))

        except Exception as e:
            raise UserError(_('Error al probar conexión: %s') % str(e))

    # ==================== HELPER METHODS ====================

    @api.model
    def prepare_invoice_line(self, base_imponible, tipo_impositivo=None, cuota_repercutida=None,
                           impuesto='01', calificacion_operacion='S1', clave_regimen='01',
                           operacion_exenta=None, base_imponible_a_coste=None,
                           tipo_recargo_equivalencia=None, cuota_recargo_equivalencia=None):
        """Preparar línea de factura según formato API Verifacti

        Args:
            base_imponible: Base imponible de la línea
            tipo_impositivo: Tipo impositivo (0, 2, 4, 5, 7.5, 10, 21)
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
            'base_imponible': str(base_imponible),
            'impuesto': impuesto,
        }

        if tipo_impositivo is not None:
            line['tipo_impositivo'] = str(tipo_impositivo)
        if cuota_repercutida is not None:
            line['cuota_repercutida'] = str(cuota_repercutida)
        if calificacion_operacion:
            line['calificacion_operacion'] = calificacion_operacion
        if clave_regimen:
            line['clave_regimen'] = clave_regimen
        if operacion_exenta:
            line['operacion_exenta'] = operacion_exenta
        if base_imponible_a_coste is not None:
            line['base_imponible_a_coste'] = str(base_imponible_a_coste)
        if tipo_recargo_equivalencia is not None:
            line['tipo_recargo_equivalencia'] = str(tipo_recargo_equivalencia)
        if cuota_recargo_equivalencia is not None:
            line['cuota_recargo_equivalencia'] = str(cuota_recargo_equivalencia)

        return line

    @api.model
    def format_date(self, date_obj):
        """Convertir fecha de Odoo a formato Verifacti (DD-MM-YYYY)"""
        if not date_obj:
            return None
        return date_obj.strftime('%d-%m-%Y')
