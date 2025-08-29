# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import json

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
import requests

class AccountMove(models.Model):
    _inherit = "account.move"

    ba_edi_fiskalni_broj = fields.Char(
        string="Fiskalni račun:",
        help="Broj fiskalnog računa"
    )

    def button_draft(self):
        for move in self:
            bs_edi = move.edi_document_ids.filtered(lambda doc: doc.edi_format_id.code == "ba_fiskalne_1_00")
            if bs_edi.state == 'sent':
                raise ValidationError(
                    "Fiskalizirani dokument se ne može vratiti u pripremu"
                    )
        return super(AccountMove, self).button_draft()

    def button_cancel_posted_moves(self):
        #"""Mark the edi.document related to this move to be canceled."""
        #reason_and_remarks_not_set = self.env["account.move"]
        for move in self:
            bs_edi = move.edi_document_ids.filtered(lambda doc: doc.edi_format_id.code == "ba_fiskalne_1_00")
            # check submitted E-invoice does not have reason and remarks
            # because it's needed to cancel E-invoice
            #if send_l10n_bs_edi and (not move.l10n_bs_edi_cancel_reason or not move.l10n_bs_edi_cancel_remarks):
            #    reason_and_remarks_not_set += move

            if bs_edi.state == 'sent':
                raise ValidationError(
                    "Fiskalizirana faktura se se ne može vratiti u pripremu"
                    )
        return super().button_cancel_posted_moves()

    def _get_ba_edi_response_json(self):
        # koristi štampa fakture
        self.ensure_one()
        ba_edi = self.edi_document_ids.filtered(lambda i: i.edi_format_id.code == "ba_fiskalne_1_00"
            and i.state in ("sent", "to_cancel"))
        if ba_edi:
            return json.loads(ba_edi.sudo().attachment_id.raw.decode("utf-8"))
        else:
            return { "invoiceNumber": "0" }

    def fiskalni_duplikat(self):
        self.ensure_one()
        ba_edi = self.edi_document_ids.filtered(lambda i: i.edi_format_id.code == "ba_fiskalne_1_00"
            and i.state in ("sent"))
        if not ba_edi:
            ValidationError("Fiskalne funkcije nisu podešene?!")

        #action = self.env["ir.actions.act_window"]._for_xml_id(
        #    "l10n_bs_edi.action_fiskalne_funkcije"
        #)
        #action["res_id"] = self.id
        #
        ##return {'type': 'ir.actions.act_window_close'}
    
        #return action

        for rec in self:
            rec.name
            if rec.move_type == 'out_invoice':
                tip = 'F'
            elif rec.move_type == 'out_refund':
                tip = 'R'
            else:
                ValidationError('nepostojeći tip dokumenta?!')
            api_host=rec.company_id.sudo().l10n_bs_edi_api_host
            pin=rec.company_id.sudo().l10n_bs_edi_pin
            _url = f"{api_host}/{pin}/duplikat/{tip}/{rec.ba_edi_fiskalni_broj}"
            headers = {
                "Content-type": "application/json",
                "accept": "application/json"
            }

            response = requests.get(url=_url, headers=headers)

            error_msg = "FPRINT: GREŠKA duplikat!"
            if response.status_code == 200:
                response_json = response.json()
                if response_json.get("status") == "OK":
                    return True
                else:
                    ValidationError(error_msg)




    #def action_view_assets(self):
    #    assets = (
    #        self.env["account.asset.line"]
    #        .search([("move_id", "=", self.id)])
    #        .mapped("asset_id")
    #    )
    #    action = self.env.ref("account_asset_management.account_asset_action")
    #    action_dict = action.sudo().read()[0]
    #    if len(assets) == 1:
    #        res = self.env.ref(
    #            "account_asset_management.account_asset_view_form", False
    #        )
    #        action_dict["views"] = [(res and res.id or False, "form")]
    #        action_dict["res_id"] = assets.id
    #    elif assets:
    #        action_dict["domain"] = [("id", "in", assets.ids)]
    #    else:
    #        action_dict = {"type": "ir.actions.act_window_close"}
    #    return action_dict

    #def _get_ba_edi_fiskresponse_json(self):
    #    # koristi štampa fakture
    #    self.ensure_one()
    #    ba_edi = self.edi_document_ids.filtered(lambda i: i.edi_format_id.code == "ba_fiskalne_1_00"
    #        and i.state in ("sent", "to_cancel"))
    #    if ba_edi:
    #        return json.loads(ba_edi.sudo().attachment_id.raw.decode("utf-8"))
    #    else:
    #        return { "invoiceNumber": "0" }
        
    #@api.model
    #def _l10n_bs_edi_is_managing_invoice_negative_lines_allowed(self):
    #    """ Negative lines are not allowed by the Bosnian government making some features unavailable like sale_coupon
    #    or global discounts. This method allows odoo to distribute the negative discount lines to each others lines
    #    with same HSN code making such features available even for Bosnian people.
    #    :return: True if odoo needs to distribute the negative discount lines, False otherwise.
    #    """
    #    param_name = 'l10n_bs_edi.manage_invoice_negative_lines'
    #    return bool(self.env['ir.config_parameter'].sudo().get_param(param_name))
