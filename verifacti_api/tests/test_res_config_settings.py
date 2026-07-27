# -*- coding: utf-8 -*-

from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError


class TestResConfigSettings(TransactionCase):
    """
    Tests para la configuración de VeriFacti en res.config.settings
    """

    def setUp(self):
        super(TestResConfigSettings, self).setUp()
        self.company = self.env.ref('base.main_company')
        self.IrConfigParameter = self.env['ir.config_parameter'].sudo()

    def _get_param_key(self, param):
        """Helper para generar claves de parámetros"""
        return f'verifacti_api.company_{self.company.id}.{param}'

    def _get_config_value(self, param, default=''):
        """Helper para leer configuración"""
        return self.IrConfigParameter.get_param(
            self._get_param_key(param),
            default=default
        )

    def _set_config_value(self, param, value):
        """Helper para escribir configuración"""
        self.IrConfigParameter.set_param(
            self._get_param_key(param),
            str(value)
        )

    def test_default_values_through_settings(self):
        """
        Test: Verificar valores por defecto mediante res.config.settings
        """
        settings = self.env['res.config.settings'].create({})

        # Los valores por defecto se establecen en get_values()
        self.assertEqual(
            settings.verifacti_max_retries,
            3,
            "El número de reintentos por defecto debe ser 3"
        )
        self.assertEqual(
            settings.verifacti_retry_delay,
            2,
            "El delay de reintentos por defecto debe ser 2 segundos"
        )
        self.assertFalse(
            settings.verifacti_auto_send_enabled,
            "El envío automático debe estar deshabilitado por defecto"
        )
        self.assertEqual(
            settings.verifacti_max_bulk_limit,
            10,
            "El límite de operaciones masivas por defecto debe ser 10"
        )

    def test_set_api_key(self):
        """
        Test: Configurar API key de VeriFacti mediante settings
        """
        api_key = 'test_api_key_abcdef123456'

        settings = self.env['res.config.settings'].create({
            'verifacti_api_key': api_key,
        })
        settings.execute()

        saved_key = self._get_config_value('api_key')
        self.assertEqual(
            saved_key,
            api_key,
            "La API key debe guardarse correctamente en ir.config_parameter"
        )

    def test_set_api_url(self):
        """
        Test: Configurar URL de API de VeriFacti
        """
        api_url = 'https://api.custom.verifacti.com'

        settings = self.env['res.config.settings'].create({
            'verifacti_api_url': api_url,
        })
        settings.execute()

        saved_url = self._get_config_value('api_url')
        self.assertEqual(
            saved_url,
            api_url,
            "La URL de API debe guardarse correctamente"
        )

    def test_enable_auto_send(self):
        """
        Test: Habilitar envío automático
        """
        settings = self.env['res.config.settings'].create({
            'verifacti_auto_send_enabled': True,
        })
        settings.execute()

        is_enabled = self._get_config_value('auto_send_enabled')
        self.assertEqual(
            is_enabled,
            'True',
            "El envío automático debe habilitarse correctamente"
        )

    def test_configure_retries(self):
        """
        Test: Configurar reintentos y delay
        """
        settings = self.env['res.config.settings'].create({
            'verifacti_max_retries': 5,
            'verifacti_retry_delay': 3,
        })
        settings.execute()

        self.assertEqual(self._get_config_value('max_retries'), '5')
        self.assertEqual(self._get_config_value('retry_delay'), '3')

    def test_configure_system_load(self):
        """
        Test: Configurar control de carga del sistema
        """
        settings = self.env['res.config.settings'].create({
            'verifacti_check_system_load': True,
            'verifacti_max_system_load': 3.5,
        })
        settings.execute()

        self.assertEqual(self._get_config_value('check_system_load'), 'True')
        self.assertEqual(self._get_config_value('max_system_load'), '3.5')

    def test_sector_especial_configuration(self):
        """
        Test: Configurar sector especial (límite 3.000€)
        """
        settings = self.env['res.config.settings'].create({
            'verifacti_sector_especial': True,
        })
        settings.execute()

        is_special = self._get_config_value('sector_especial')
        self.assertEqual(
            is_special,
            'True',
            "El sector especial debe configurarse correctamente"
        )

    def test_bulk_limit_configuration(self):
        """
        Test: Configurar límite de operaciones masivas
        """
        settings = self.env['res.config.settings'].create({
            'verifacti_max_bulk_limit': 25,
        })
        settings.execute()

        limit = self._get_config_value('max_bulk_limit')
        self.assertEqual(
            limit,
            '25',
            "El límite de operaciones masivas debe actualizarse correctamente"
        )

    def test_min_invoice_date_configuration(self):
        """
        Test: Configurar fecha mínima de facturas
        """
        settings = self.env['res.config.settings'].create({
            'verifacti_min_invoice_date': '2025-01-01',
        })
        settings.execute()

        min_date = self._get_config_value('min_invoice_date')
        self.assertEqual(
            min_date,
            '2025-01-01',
            "La fecha mínima debe configurarse correctamente"
        )

    def test_action_resume_auto_send_not_paused(self):
        """
        Test: Intentar reanudar envío cuando no está pausado
        """
        settings = self.env['res.config.settings'].create({})

        # Asegurarse de que no está pausado
        self._set_config_value('auto_send_paused', 'False')

        with self.assertRaises(UserError) as context:
            settings.action_resume_verifacti_auto_send()

        self.assertIn('pausado', str(context.exception))

    def test_action_resume_auto_send_when_paused(self):
        """
        Test: Reanudar envío automático después de pausa
        """
        from odoo import fields

        # Pausar manualmente
        self._set_config_value('auto_send_paused', 'True')
        self._set_config_value('auto_send_paused_reason', 'Test pause')
        self._set_config_value('auto_send_paused_since', str(fields.Datetime.now()))

        settings = self.env['res.config.settings'].create({})

        # Reanudar
        result = settings.action_resume_verifacti_auto_send()

        # Verificar que se reanudó
        is_paused = self._get_config_value('auto_send_paused')
        self.assertEqual(is_paused, 'False', "Debe estar reanudado")

        # Verificar que retorna notificación
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get('type'), 'ir.actions.client')

    def test_multiple_companies_independent_config(self):
        """
        Test: Configuración independiente por compañía
        """
        # Crear segunda compañía
        company2 = self.env['res.company'].create({
            'name': 'Test Company 2',
        })

        # Configurar diferentes API keys para cada compañía
        self._set_config_value('api_key', 'sk_test_company_1_demo_key')

        IrConfigParameter2 = self.env['ir.config_parameter'].sudo()
        IrConfigParameter2.set_param(
            f'verifacti_api.company_{company2.id}.api_key',
            'sk_test_company_2_demo_key'
        )

        # Verificar que cada compañía tiene su propia configuración
        key1 = self._get_config_value('api_key')
        key2 = IrConfigParameter2.get_param(
            f'verifacti_api.company_{company2.id}.api_key',
            default=''
        )

        self.assertEqual(key1, 'sk_test_company_1_demo_key')
        self.assertEqual(key2, 'sk_test_company_2_demo_key')
        self.assertNotEqual(key1, key2, "Las configuraciones deben ser independientes")

    def test_get_values_loads_correctly(self):
        """
        Test: get_values() carga correctamente desde ir.config_parameter
        """
        # Establecer valores directamente en ir.config_parameter
        self._set_config_value('api_key', 'test_key_123')
        self._set_config_value('max_retries', '7')
        self._set_config_value('auto_send_enabled', 'True')

        # Crear settings y verificar que carga los valores
        settings = self.env['res.config.settings'].create({})

        self.assertEqual(settings.verifacti_api_key, 'test_key_123')
        self.assertEqual(settings.verifacti_max_retries, 7)
        self.assertTrue(settings.verifacti_auto_send_enabled)

    def test_set_values_saves_correctly(self):
        """
        Test: set_values() guarda correctamente en ir.config_parameter
        """
        settings = self.env['res.config.settings'].create({
            'verifacti_api_key': 'new_key_456',
            'verifacti_max_retries': 8,
            'verifacti_auto_send_enabled': False,
        })
        settings.execute()

        # Verificar directamente en ir.config_parameter
        self.assertEqual(self._get_config_value('api_key'), 'new_key_456')
        self.assertEqual(self._get_config_value('max_retries'), '8')
        self.assertEqual(self._get_config_value('auto_send_enabled'), 'False')
