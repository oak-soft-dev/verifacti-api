# -*- coding: utf-8 -*-

from odoo.tests.common import TransactionCase
from unittest.mock import patch, Mock
import json


class VeriFactiTestCase(TransactionCase):
    """
    Clase base para tests de VeriFacti API
    Proporciona setup común y métodos de ayuda
    """

    def setUp(self):
        super(VeriFactiTestCase, self).setUp()

        # Mock de peticiones HTTP para evitar llamadas reales a la API
        self.mock_requests_patcher = patch('requests.request')
        self.mock_requests = self.mock_requests_patcher.start()

        # Configurar respuesta por defecto exitosa
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'uuid': 'test-uuid-12345',
            'estado': 'Correcto',
            'qr': 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==',
            'huella': 'ABC123DEF456789',
            'url': 'https://verifacti.com/verify/test-uuid-12345',
        }
        mock_response.text = json.dumps(mock_response.json.return_value)
        mock_response.raise_for_status = Mock()

        self.mock_requests.return_value = mock_response

        # Configurar empresa con datos de VeriFacti
        self.company = self.env.ref('base.main_company')
        self.company.write({
            'country_id': self.env.ref('base.es').id,  # Requerido en Odoo 15+ para validación de impuestos
        })

        # Configurar VeriFacti mediante ir.config_parameter
        self.IrConfigParameter = self.env['ir.config_parameter'].sudo()
        self._set_verifacti_config('api_key', 'sk_test_demo_key_for_testing_purposes_12345678')
        self._set_verifacti_config('api_url', 'https://api.test.verifacti.com')
        self._set_verifacti_config('max_retries', '3')
        self._set_verifacti_config('retry_delay', '2')
        self._set_verifacti_config('auto_send_enabled', 'False')
        self._set_verifacti_config('max_bulk_limit', '10')
        self._set_verifacti_config('check_system_load', 'False')

        # Partner (cliente)
        self.partner = self.env['res.partner'].create({
            'name': 'Test Customer',
            'vat': 'ES12345678Z',
            'street': 'Calle Test 123',
            'city': 'Madrid',
            'zip': '28001',
            'country_id': self.env.ref('base.es').id,
        })

        # Producto
        self.product = self.env['product.product'].create({
            'name': 'Test Product',
            'type': 'service',
            'list_price': 100.0,
            'standard_price': 50.0,
        })

        # Cuenta contable para facturas
        # En Odoo 15: usar user_type_id
        user_type_receivable = self.env.ref('account.data_account_type_receivable', raise_if_not_found=False)
        if not user_type_receivable:
            user_type_receivable = self.env['account.account.type'].search([('type', '=', 'receivable')], limit=1)

        self.account_receivable = self.env['account.account'].search([
            ('user_type_id', '=', user_type_receivable.id)
        ], limit=1)

        if not self.account_receivable:
            self.account_receivable = self.env['account.account'].create({
                'name': 'Test Receivable',
                'code': 'TEST430',
                'user_type_id': user_type_receivable.id,
                'reconcile': True,
            })

        # Cuenta de ingresos
        # En Odoo 15: usar user_type_id
        user_type_income = self.env.ref('account.data_account_type_revenue', raise_if_not_found=False)
        if not user_type_income:
            user_type_income = self.env['account.account.type'].search([('type', '=', 'other')], limit=1)

        self.account_revenue = self.env['account.account'].search([
            ('user_type_id', '=', user_type_income.id)
        ], limit=1)

        if not self.account_revenue:
            self.account_revenue = self.env['account.account'].create({
                'name': 'Test Revenue',
                'code': 'TEST700',
                'user_type_id': user_type_income.id,
            })

        # Actualizar partner con cuenta por cobrar
        self.partner.property_account_receivable_id = self.account_receivable

        # Diario
        self.journal = self.env['account.journal'].search([
            ('type', '=', 'sale'),
            ('company_id', '=', self.company.id)
        ], limit=1)

        if not self.journal:
            self.journal = self.env['account.journal'].create({
                'name': 'Test Sales Journal',
                'code': 'TSALE',
                'type': 'sale',
            })

        # Impuesto (IVA 21%)
        self.tax = self.env['account.tax'].search([
            ('type_tax_use', '=', 'sale'),
            ('amount', '=', 21.0),
            ('company_id', '=', self.company.id)
        ], limit=1)

        if not self.tax:
            # En Odoo 13: tax_group_id no tiene country_id
            tax_group = self.env['account.tax.group'].search([], limit=1)

            if not tax_group:
                tax_group = self.env['account.tax.group'].create({
                    'name': 'IVA',
                })

            self.tax = self.env['account.tax'].create({
                'name': 'IVA 21%',
                'type_tax_use': 'sale',
                'amount': 21.0,
                'amount_type': 'percent',
                'tax_group_id': tax_group.id,
            })

    def tearDown(self):
        """Detener patchers de mock"""
        self.mock_requests_patcher.stop()
        super(VeriFactiTestCase, self).tearDown()

    def create_test_invoice(self, invoice_type='out_invoice', state='draft', **kwargs):
        """
        Crea una factura de prueba

        :param invoice_type: Tipo de factura (out_invoice, out_refund, etc.)
        :param state: Estado inicial (draft, posted)
        :param kwargs: Parámetros adicionales
        :return: Factura creada
        """
        invoice_vals = {
            'type': invoice_type,  # Odoo 13 usa type
            'partner_id': kwargs.get('partner_id', self.partner.id),
            'journal_id': kwargs.get('journal_id', self.journal.id),
            'invoice_line_ids': [(0, 0, {
                'name': kwargs.get('product_name', 'Test Product Line'),
                'product_id': kwargs.get('product_id', self.product.id),
                'quantity': kwargs.get('quantity', 1.0),
                'price_unit': kwargs.get('price_unit', 100.0),
                'account_id': self.account_revenue.id,
                'tax_ids': [(6, 0, [self.tax.id])] if kwargs.get('with_tax', True) else [],
            })],
        }

        # Merge additional kwargs
        invoice_vals.update({k: v for k, v in kwargs.items()
                           if k not in ['partner_id', 'journal_id', 'product_name',
                                       'product_id', 'quantity', 'price_unit', 'with_tax']})

        invoice = self.env['account.move'].create(invoice_vals)

        # Si se solicita estado posted, validar la factura
        if state == 'posted':
            invoice.action_post()

        return invoice

    def _mock_verifacti_success_response(self):
        """
        Simula una respuesta exitosa de VeriFacti API
        """
        return {
            'success': True,
            'data': {
                'uuid': 'test-uuid-12345',
                'registrationStatus': 'Correcto',
                'qrCode': 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==',
                'huella': 'ABC123DEF456789',
                'url': 'https://verifacti.com/verify/test-uuid-12345',
            }
        }

    def _mock_verifacti_error_response(self):
        """
        Simula una respuesta de error de VeriFacti API
        """
        return {
            'success': False,
            'error': {
                'code': 'VF001',
                'message': 'Error de validación en datos de factura',
            }
        }

    def _get_param_key(self, param):
        """Helper para generar claves de parámetros de configuración"""
        return f'verifacti_api.company_{self.company.id}.{param}'

    def _set_verifacti_config(self, param, value):
        """Helper para establecer configuración de VeriFacti"""
        self.IrConfigParameter.set_param(
            self._get_param_key(param),
            str(value)
        )

    def _get_verifacti_config(self, param, default=''):
        """Helper para leer configuración de VeriFacti"""
        return self.IrConfigParameter.get_param(
            self._get_param_key(param),
            default=default
        )
