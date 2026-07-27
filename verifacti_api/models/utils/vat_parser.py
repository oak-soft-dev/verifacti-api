# -*- coding: utf-8 -*-
"""
Parser de VAT/NIF para múltiples países
========================================

Utilidad para parsear y validar números de identificación fiscal (VAT/NIF/CIF)
de España y otros países de la UE.

Soporta:
- NIFs españoles (12345678A)
- NIEs españoles (X1234567A, Y1234567A, Z1234567A)
- CIFs españoles (A12345678)
- VATs de la UE (con prefijo de país)
- VATs de terceros países

Uso:
    from odoo.addons.verifacti_api.models.utils.vat_parser import VatParser

    result = VatParser.parse("ES12345678A", country_code="ES")
    # result = {
    #     'is_valid': True,
    #     'is_spanish': True,
    #     'country_code': 'ES',
    #     'vat_number': '12345678A',
    #     'vat_type': 'NIF',
    #     'formatted_vat': 'ES12345678A'
    # }
"""

import re
from odoo.exceptions import ValidationError
from odoo import _


class VatParser:
    """Parser y validador de VAT/NIF/CIF para VeriFactu"""

    # Países de la Unión Europea (27 países)
    EU_COUNTRIES = frozenset([
        "AT",  # Austria
        "BE",  # Bélgica
        "BG",  # Bulgaria
        "CY",  # Chipre
        "CZ",  # República Checa
        "DE",  # Alemania
        "DK",  # Dinamarca
        "EE",  # Estonia
        "EL",  # Grecia (código especial, también GR)
        "FI",  # Finlandia
        "FR",  # Francia
        "HR",  # Croacia
        "HU",  # Hungría
        "IE",  # Irlanda
        "IT",  # Italia
        "LT",  # Lituania
        "LU",  # Luxemburgo
        "LV",  # Letonia
        "MT",  # Malta
        "NL",  # Países Bajos
        "PL",  # Polonia
        "PT",  # Portugal
        "RO",  # Rumanía
        "SE",  # Suecia
        "SI",  # Eslovenia
        "SK",  # Eslovaquia
    ])

    # Patrones regex para VAT españoles
    SPANISH_NIE_PATTERN = r"^[XYZ]\d{7}[A-Z]$"  # Extranjeros residentes
    SPANISH_NIF_PATTERN = r"^\d{8}[A-Z]$"       # Personas físicas
    SPANISH_CIF_PATTERN = r"^[A-W]\d{7}[A-Z0-9]$"  # Personas jurídicas

    @classmethod
    def parse(cls, vat, country_code=None):
        """
        Parsear y validar VAT/NIF

        Args:
            vat (str): Número de VAT/NIF a parsear
            country_code (str, optional): Código de país ISO de 2 letras

        Returns:
            dict: Diccionario con información del VAT parseado
            {
                'is_valid': bool,
                'is_spanish': bool,
                'country_code': str,
                'vat_number': str,  # Sin prefijo de país
                'vat_type': str,    # 'NIF', 'NIE', 'CIF', 'VAT_EU', 'VAT_FOREIGN'
                'formatted_vat': str,  # Formato completo con prefijo
                'id_type': str,     # Para API: '02' (UE) o '04' (No-UE)
            }

        Raises:
            ValidationError: Si el VAT no puede ser parseado
        """
        if not vat:
            raise ValidationError(_("El VAT/NIF no puede estar vacío"))

        # Normalizar: mayúsculas y sin espacios
        vat_clean = vat.strip().upper().replace(' ', '').replace('-', '')

        # Intentar detectar tipo de VAT
        result = None

        # 1. Verificar si es VAT español (sin prefijo)
        if cls._is_spanish_vat(vat_clean):
            result = cls._parse_spanish_vat(vat_clean)

        # 2. Verificar si tiene prefijo de país (2 letras al inicio)
        elif len(vat_clean) >= 2 and vat_clean[:2].isalpha():
            prefix = vat_clean[:2]
            vat_number = vat_clean[2:]

            if prefix == "ES":
                # VAT español con prefijo ES
                if cls._is_spanish_vat(vat_number):
                    result = cls._parse_spanish_vat(vat_number)
                else:
                    raise ValidationError(_(
                        "El VAT '%s' tiene prefijo ES pero no es un NIF/NIE/CIF válido"
                    ) % vat)

            elif prefix in cls.EU_COUNTRIES or prefix == "GR":  # GR es Grecia
                # VAT de la UE
                result = {
                    'is_valid': True,
                    'is_spanish': False,
                    'country_code': prefix,
                    'vat_number': vat_number,
                    'vat_type': 'VAT_EU',
                    'formatted_vat': vat_clean,
                    'id_type': '02',  # Código API VeriFactu para UE
                }

            else:
                # VAT de país tercero (no-UE)
                result = {
                    'is_valid': True,
                    'is_spanish': False,
                    'country_code': prefix,
                    'vat_number': vat_number,
                    'vat_type': 'VAT_FOREIGN',
                    'formatted_vat': vat_clean,
                    'id_type': '04',  # Código API VeriFactu para terceros países
                }

        # 3. Si no tiene prefijo y no es español, usar country_code del partner
        elif country_code:
            country_upper = country_code.strip().upper()

            if country_upper == "ES":
                raise ValidationError(_(
                    "El VAT '%s' está asociado a España pero no tiene formato válido.\n"
                    "Formatos válidos:\n"
                    "• NIF: 12345678A\n"
                    "• NIE: X1234567A\n"
                    "• CIF: A12345678"
                ) % vat)

            elif country_upper in cls.EU_COUNTRIES or country_upper == "GR":
                result = {
                    'is_valid': True,
                    'is_spanish': False,
                    'country_code': country_upper,
                    'vat_number': vat_clean,
                    'vat_type': 'VAT_EU',
                    'formatted_vat': f"{country_upper}{vat_clean}",
                    'id_type': '02',
                }

            else:
                result = {
                    'is_valid': True,
                    'is_spanish': False,
                    'country_code': country_upper,
                    'vat_number': vat_clean,
                    'vat_type': 'VAT_FOREIGN',
                    'formatted_vat': f"{country_upper}{vat_clean}",
                    'id_type': '04',
                }

        else:
            raise ValidationError(_(
                "No se pudo parsear el VAT '%s'.\n\n"
                "Soluciones:\n"
                "1. Asegúrate de que el formato sea correcto:\n"
                "   • España: 12345678A, X1234567A, A12345678\n"
                "   • Con prefijo: ES12345678A, DE123456789, etc.\n"
                "2. O configura el país del contacto en su ficha"
            ) % vat)

        return result

    @classmethod
    def _is_spanish_vat(cls, vat_clean):
        """Verificar si es un VAT español válido (NIF, NIE o CIF)"""
        return any([
            re.match(cls.SPANISH_NIE_PATTERN, vat_clean),
            re.match(cls.SPANISH_NIF_PATTERN, vat_clean),
            re.match(cls.SPANISH_CIF_PATTERN, vat_clean),
        ])

    @classmethod
    def _parse_spanish_vat(cls, vat_clean):
        """Parsear VAT español y determinar tipo (NIF, NIE o CIF)"""
        vat_type = None

        if re.match(cls.SPANISH_NIE_PATTERN, vat_clean):
            vat_type = 'NIE'
        elif re.match(cls.SPANISH_NIF_PATTERN, vat_clean):
            vat_type = 'NIF'
        elif re.match(cls.SPANISH_CIF_PATTERN, vat_clean):
            vat_type = 'CIF'

        return {
            'is_valid': True,
            'is_spanish': True,
            'country_code': 'ES',
            'vat_number': vat_clean,
            'vat_type': vat_type,
            'formatted_vat': f"ES{vat_clean}",
            'id_type': None,  # No aplica para España (usa campo "nif" directamente)
        }

    @classmethod
    def format_for_verifacti(cls, vat, country_code=None):
        """
        Formatear VAT para envío a API VeriFactu

        Args:
            vat (str): VAT a formatear
            country_code (str, optional): Código de país

        Returns:
            dict: Datos formateados para VeriFactu
            {
                'nif': str,  # Solo para España (sin prefijo)
                'id_otro': dict,  # Para extranjeros
                    {
                        'codigo_pais': str,
                        'id_type': str,  # '02' (UE) o '04' (No-UE)
                        'id': str
                    }
            }
        """
        parsed = cls.parse(vat, country_code)

        if parsed['is_spanish']:
            # España: campo "nif" sin prefijo
            return {
                'nif': parsed['vat_number']
            }
        else:
            # Extranjero: campo "id_otro" con estructura completa
            return {
                'id_otro': {
                    'codigo_pais': parsed['country_code'],
                    'id_type': parsed['id_type'],
                    'id': parsed['vat_number']
                }
            }
