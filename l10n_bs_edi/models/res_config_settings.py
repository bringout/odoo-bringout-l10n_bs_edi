# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, _
from odoo.exceptions import UserError, RedirectWarning


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    l10n_bs_edi_api_host = fields.Char("Fiskalni host url", related="company_id.l10n_bs_edi_api_host", readonly=False)
    l10n_bs_edi_api_key = fields.Char("Fiskalni api key", related="company_id.l10n_bs_edi_api_key", readonly=False)
    l10n_bs_edi_pin = fields.Char("Fiskalni pin", related="company_id.l10n_bs_edi_pin", readonly=False)
    
    l10n_bs_edi_production_env = fields.Boolean(
        string="Fiskalne fuknkcije aktivirane",
        related="company_id.l10n_bs_edi_production_env",
        readonly=False
    )

    def l10n_bs_check_vat_number(self):
        if not self.company_id.vat:
            action = {
                    "view_mode": "form",
                    "res_model": "res.company",
                    "type": "ir.actions.act_window",
                    "res_id" : self.company_id.id,
                    "views": [[self.env.ref("base.view_company_form").id, "form"]],
            }
            raise RedirectWarning(_("Molimo unesite PDV broj za preduzeće."), action, _('Idi na preduzeće'))

    def l10n_bs_edi_test(self):
        self.l10n_bs_check_vat_number()
        self.env["account.edi.format"]._l10n_bs_edi_authenticate(self.company_id)
        if not self.company_id.sudo()._l10n_bs_edi_token_is_valid():
            raise UserError(_("Incorrect username or password, or the GST number on company does not match."))
        return {
              'type': 'ir.actions.client',
              'tag': 'display_notification',
              'params': {
                  'type': 'info',
                  'sticky': False,
                  'message': _("API credentials validated successfully"),
              }
          }


