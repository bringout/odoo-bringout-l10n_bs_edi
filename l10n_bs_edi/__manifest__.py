# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
{
    "name": """Bosnia and Herzegovina FBiH - fiskalizacija (legacy)""",
    "version": "1.1.0",
    "category": "Accounting/Localizations/EDI",
    "depends": [
        "account_edi",
        "l10n_bs",
    ],
    "description": """
Bosnian - E Fiskalizacija
==============================

    """,
    "data": [
        "data/account_edi_data.xml",
        "views/res_config_settings_views.xml",
        "views/edi_pdf_report.xml",
        "views/account_move_views.xml",
    ],
    #"demo": [
    #    "demo/demo_company.xml",
    #],
    "installable": True,
    "license": "AGPL-3",
}
