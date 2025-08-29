# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    l10n_bs_edi_api_host = fields.Char("Fiskalizacijski server npr http://fisk.test.com:3556", groups="base.group_system")
    l10n_bs_edi_api_key = fields.Char("Api key", groups="base.group_system")
    l10n_bs_edi_pin = fields.Char("PIN", groups="base.group_system")
    
    #l10n_bs_edi_token_validity = fields.Datetime("E-invoice (IN) Valid Until", groups="base.group_system")
    l10n_bs_edi_production_env = fields.Boolean(
        string="Fiskalne funkcije u produkciji",
        help="Postaviti DA kada želimo aktivirati sistem u produkciji",
        groups="base.group_system",
    )

    def _l10n_bs_edi_token_is_valid(self):
        #self.ensure_one()
        #if self.l10n_bs_edi_token and self.l10n_bs_edi_token_validity > fields.Datetime.now():
        #    return True
        #return False
        return True
