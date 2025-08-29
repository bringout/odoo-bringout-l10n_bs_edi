# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import re
import json
import pytz
import markupsafe
import requests
from datetime import datetime

from collections import defaultdict

from odoo import models, fields, api, _
from odoo.tools import html_escape, float_is_zero, float_compare
from odoo.exceptions import AccessError, ValidationError
#from odoo.addons.iap import jsonrpc
import logging

_logger = logging.getLogger(__name__)

#DEFAULT_IAP_ENDPOINT = "https://l10n-in-edi.api.odoo.com"
#DEFAULT_IAP_TEST_ENDPOINT = "https://l10n-in-edi-demo.api.odoo.com"

IN_GOTOVINA = ('NAČIN PLAĆANJA: GOTOVINA', 'PLAĆANJE GOTOVINOM')
IN_KARTICA = ('NAČIN PLAĆANJA: KARTICA', 'PLAĆANJE KARTICOM')

class AccountEdiFormat(models.Model):
    _inherit = "account.edi.format"

    def _is_enabled_by_default_on_journal(self, journal):
        self.ensure_one()
        if self.code == "ba_fiskalne_1_00":
            return journal.company_id.country_id.code == 'BA'
        return super()._is_enabled_by_default_on_journal(journal)

    #def _get_l10n_bs_base_tags(self):
    #    return (
    #       self.env.ref('tax_group_vat_17').ids
    #       + self.env.ref('tax_group_vat_17_kp').ids
    #    )

    def _get_ba_tax_tags(self):
        return (
           self.env.ref('l10n_bs.tax_tag_E').ids
           
           + self.env.ref("l10n_bs.tax_tag_K").ids
           #+ self.env.ref("l10n_bs.tax_tag_K_base").ids
           + self.env.ref("l10n_bs.tax_tag_A").ids
           #+ self.env.ref("l10n_bs.tax_tag_A_base").ids
        )

    def _get_ba_non_taxable_tags(self):
        return (
          self.env.ref('l10n_bs.tax_tag_E_base').ids
        )

    def _get_move_applicability(self, move):
        # EXTENDS account_edi
        self.ensure_one()
        if self.code != 'ba_fiskalne_1_00':
            return super()._get_move_applicability(move)
        is_taxable = any(move_line_tag.id in self._get_ba_tax_tags() for move_line_tag in move.line_ids.tax_tag_ids)
        if move.is_sale_document(include_receipts=True) and move.country_code == 'BA' and is_taxable:
            return {
                'post': self._ba_edi_post_invoice,
                #'post_batching': self._ba_edi_post_batch,
                # nije moguc cancel
                'cancel': self._l10n_ba_edi_cancel_invoice,
                #'cancel': self._ba_edi_post_invoice, # radi testiranja, cancel proces isti kao i post
                'edi_content': self._l10n_bs_edi_invoice_content,
            }

    #def _ba_edi_post_batch(self, account_move):
    #    print(account_move)

    def _needs_web_services(self):
        self.ensure_one()
        return self.code == "ba_fiskalne_1_00" or super()._needs_web_services()

    def _l10n_bs_edi_invoice_content(self, invoice):
        return json.dumps(self._ba_edi_generate_invoice_json(invoice)).encode()

    def _l10n_bs_edi_extract_digits(self, string):
        if not string:
            return string
        matches = re.findall(r"\d+", string)
        result = "".join(matches)
        return result

    def _check_move_configuration(self, move):
        if self.code != "ba_fiskalne_1_00":
            return super()._check_move_configuration(move)
        error_message = []
        error_message += self._ba_validate_partner(move.partner_id)
        error_message += self._ba_validate_partner(move.company_id.partner_id, is_company=True)
        if not re.match("^.{1,16}$", move.name):
            error_message.append(_("Broj fakture ne smije biti veći od 16 znakova"))
        all_base_tags = self._get_ba_tax_tags() + self._get_ba_non_taxable_tags()
        for line in move.invoice_line_ids.filtered(lambda line: line.display_type not in ('line_note', 'line_section', 'rounding')):
            if line.display_type == 'product' and line.discount < 0:
                error_message.append(_("Negativni popust nije dozvoljen %s", line.name))
            if not line.tax_tag_ids or not any(move_line_tag.id in all_base_tags for move_line_tag in line.tax_tag_ids):
                error_message.append(_(
                    """Postaviti odgovarajuću stopu PDV na liniju "%s" """, line.product_id.name))
        return error_message

    #def _l10n_bs_edi_get_iap_buy_credits_message(self, company):
    #    url = self.env["iap.account"].get_credits_url(service_name="l10n_bs_edi")
    #    return markupsafe.Markup("""<p><b>%s</b></p><p>%s <a href="%s">%s</a></p>""") % (
    #        _("You have insufficient credits to send this document!"),
    #        _("Please buy more credits and retry: "),
    #        url,
    #        _("Buy Credits")
    #    )


    
    def _ba_edi_post_invoice(self, invoice):
        json_data = self._ba_edi_generate_invoice_json(invoice)
  
        api_host=invoice.company_id.sudo().l10n_bs_edi_api_host
        api_key=invoice.company_id.sudo().l10n_bs_edi_api_key

        _url = f"{api_host}/api/invoices"
        #_url_ping = f"{api_host}/api/ping"

        headers = {
            "Authorization": "Bearer %s" % api_key,
            "Content-type": "application/json",
            "accept": "application/json"
        }

        response = requests.post(url=_url, json=json_data, headers=headers)
        #response = requests.post(url=_url_ping, json={"msg": "ping"}) #, headers=headers)
        
        success = False
        error_msg = "FPRINT: GREŠKA pri štampanju fiskalnog računa!"

        if response.status_code == 200:
            response_json = response.json()
            if response_json.get("invoiceNumber"):
                #json_dump = json.dumps(response.get("data"))
                json_dump = json.dumps(response_json)
                json_name = "%s_fiskalni.json" % (invoice.name.replace("/", "_"))
                attachment = self.env["ir.attachment"].create({
                    "name": json_name,
                    "raw": json_dump.encode(),
                    "res_model": "account.move",
                    "res_id": invoice.id,
                    "mimetype": "application/json",
                })
                invoice.ba_edi_fiskalni_broj = response_json.get('invoiceNumber')
                success = True
            else:
                error_msg = response_json.get("message")
                success = False
                
                
        else:
            success = False

        if success:
            return {
                    invoice: {
                        "success": True, 
                        "attachment": attachment
                    }
            }
        else: 
            return {
                invoice: {
                    "success": False,
                    "error": error_msg,
                    "blocking_level": "error"
                }
            }
            

        #if response.get("error"):
        #    error = response["error"]
        #    error_codes = [e.get("code") for e in error]
        #    if "1005" in error_codes:
        #        # Invalid token eror then create new token and send generate request again.
        #        # This happen when authenticate called from another odoo instance with same credentials (like. Demo/Test)
        #        authenticate_response = self._l10n_bs_edi_authenticate(invoice.company_id)
        #        if not authenticate_response.get("error"):
        #            error = []
        #            response = self._l10n_bs_edi_generate(invoice.company_id, generate_json)
        #            if response.get("error"):
        #                error = response["error"]
        #                error_codes = [e.get("code") for e in error]
        #    if "2150" in error_codes:
        #        # Get IRN by details in case of IRN is already generated
        #        # this happens when timeout from the Government portal but IRN is generated
        #        response = self._l10n_bs_edi_get_irn_by_details(invoice.company_id, {
        #            "doc_type": invoice.move_type == "out_refund" and "CRN" or "INV",
        #            "doc_num": invoice.name,
        #            "doc_date": invoice.invoice_date and invoice.invoice_date.strftime("%d/%m/%Y") or False,
        #        })
        #        if not response.get("error"):
        #            error = []
        #            odoobot = self.env.ref("base.partner_root")
        #            invoice.message_post(author_id=odoobot.id, body=_(
        #                "Somehow this invoice had been submited to government before." \
        #                "<br/>Normally, this should not happen too often" \
        #                "<br/>Just verify value of invoice by uploade json to government website " \
        #                "<a href='https://einvoice1.gst.gov.in/Others/VSignedInvoice'>here<a>."
        #            ))
        #    if "no-credit" in error_codes:
        #        return {invoice: {
        #            "success": False,
        #            "error": "vrati nesto od fiskalnog servera",
        #            #"error": self._l10n_bs_edi_get_iap_buy_credits_message(invoice.company_id),
        #            "blocking_level": "error",
        #        }}
        #    elif error:
        #        error_message = "<br/>".join(["[%s] %s" % (e.get("code"), html_escape(e.get("message"))) for e in error])
        #        return {invoice: {
        #            "success": False,
        #            "error": error_message,
        #            "blocking_level": ("404" in error_codes) and "warning" or "error",
        #        }}
        #if not response.get("error"):
        

    def _l10n_ba_edi_cancel_invoice(self, invoice):
        return { invoice: {
                    "success": False,
                    "error": "Fiskalizirani dokumenti se ne mogu vraćati u pripremu",
                    "blocking_level": "error",
                }}
    

    #def _l10n_bs_edi_cancel_invoice(self, invoice):
    #    l10n_bs_edi_response_json = invoice._get_ba_edi_response_json()
    #    cancel_json = {
    #        "Irn": l10n_bs_edi_response_json.get("Irn"),
    #        #"CnlRsn": invoice.ba_edi_cancel_reason,
    #        #"CnlRem": invoice.ba_edi_cancel_remarks,
    #    }
    #    response = self._l10n_bs_edi_cancel(invoice.company_id, cancel_json)
    #    if response.get("error"):
    #        error = response["error"]
    #        error_codes = [e.get("code") for e in error]
    #        if "1005" in error_codes:
    #            # Invalid token eror then create new token and send generate request again.
    #            # This happen when authenticate called from another odoo instance with same credentials (like. Demo/Test)
    #            authenticate_response = self._l10n_bs_edi_authenticate(invoice.company_id)
    #            if not authenticate_response.get("error"):
    #                error = []
    #                response = self._l10n_bs_edi_cancel(invoice.company_id, cancel_json)
    #                if response.get("error"):
    #                    error = response["error"]
    #                    error_codes = [e.get("code") for e in error]
    #        if "9999" in error_codes:
    #            response = {}
    #            error = []
    #            odoobot = self.env.ref("base.partner_root")
    #            invoice.message_post(author_id=odoobot.id, body=_(
    #                "Somehow this invoice had been cancelled to government before." \
    #                "<br/>Normally, this should not happen too often" \
    #                "<br/>Just verify by logging into government website " \
    #                "<a href='https://einvoice1.gst.gov.in'>here<a>."
    #            ))
    #        if "no-credit" in error_codes:
    #            return {invoice: {
    #                "success": False,
    #                "error": self._l10n_bs_edi_get_iap_buy_credits_message(invoice.company_id),
    #                "blocking_level": "error",
    #            }}
    #        if error:
    #            error_message = "<br/>".join(["[%s] %s" % (e.get("code"), html_escape(e.get("message"))) for e in error])
    #            return {invoice: {
    #                "success": False,
    #                "error": error_message,
    #                "blocking_level": ("404" in error_codes) and "warning" or "error",
    #            }}
    #    if not response.get("error"):
    #        json_dump = json.dumps(response.get("data", {}))
    #        json_name = "%s_cancel_einvoice.json" % (invoice.name.replace("/", "_"))
    #        attachment = False
    #        if json_dump:
    #            attachment = self.env["ir.attachment"].create({
    #                "name": json_name,
    #                "raw": json_dump.encode(),
    #                "res_model": "account.move",
    #                "res_id": invoice.id,
    #                "mimetype": "application/json",
    #            })
    #        return {invoice: {"success": True, "attachment": attachment}}

    def _ba_validate_partner(self, partner, is_company=False):
        self.ensure_one()
        message = []
        
        if partner.country_id.code == "BA":
            if not re.match("^\d{13}$", partner.company_registry or ""):
                message.append(f"- ID broj mora biti 13 znakova: '{partner.company_registry}'")
            if not re.match("^\d{12}$", partner.vat or ""):
                # nije setovana fiskalna pozicija, ili je setovana fiskalna pozicija ali nije NE-PDV Obveznik
                if (not partner.property_account_position_id) and (partner.property_account_position_id and not (partner.property_account_position_id.name.upper() == 'NE-PDV OBVEZNIK')):
                    # NE-PDV obveznike preskoči
                    message.append(f"- PDV broj mora biti 12 znakova: '{partner.vat}'")
        if not re.match("^.{3,100}$", partner.street or ""):
            message.append(_("- Ulica min 3, max 100 znakova"))
        if partner.street2 and not re.match("^.{3,100}$", partner.street2):
            message.append(_("- Ulica2 should be min 3, 100 znakova"))
        if not re.match("^.{3,100}$", partner.city or ""):
            message.append(_("- Grad mora imati min 3 max 100 znakova"))
        if partner.country_id.code == "BA" and not re.match("^.{3,50}$", partner.state_id.name or ""):
            message.append(_("- Kanton mora biti 3-50 znakova"))
        #if partner.country_id.code == "BA" and not re.match("^[0-9]{5,}$", partner.zip or ""):
        #    message.append(_("- Poštanski broj mora imati 5 cifri"))
        #if partner.phone and not re.match("^[0-9]{10,12}$",
        #    self._l10n_bs_edi_extract_digits(partner.phone)
        #):
        #    message.append(_("- Mobile number should be minimum 10 or maximum 12 digits"))
        if partner.email and (
            not re.match(r"^[a-zA-Z0-9+_.-]+@[a-zA-Z0-9.-]+$", partner.email)
            or not re.match("^.{6,100}$", partner.email)
        ):
            message.append(_("- email adresa treba biti validna, ne može imati više od 100 znakova"))
        if message:
            message.insert(0, "%s" %(partner.display_name))
        return message

    def _get_ba_seller_buyer(self, move):
        return {
            "seller": move.company_id.partner_id,
            "buyer": move.partner_id,
        }

    #@api.model
    #def _get_l10n_bs_edi_partner_details(self, partner, set_vat=True, set_phone_and_email=True,
    #        is_overseas=False, pos_state_id=False):
    #    """
    #        Create the dictionary based partner details
    #        if set_vat is true then, vat(GSTIN) and legal name(LglNm) is added
    #        if set_phone_and_email is true then phone and email is add
    #        if set_pos is true then state code from partner or passed state_id is added as POS(place of supply)
    #        if is_overseas is true then pin is 999999 and GSTIN(vat) is URP and Stcd is .
    #        if pos_state_id is passed then we use set POS
    #    """
    #    #zip_digits = self._l10n_bs_edi_extract_digits(partner.zip)
    #    partner_details = {
    #        "Addr1": partner.street or "",
    #        "Loc": partner.city or "",
    #        #"Pin": zip_digits and int(zip_digits) or "",
    #        #"Stcd": partner.state_id.l10n_bs_tin or "",
    #    }
    #    if partner.street2:
    #        partner_details.update({"Addr2": partner.street2})
    #    if set_phone_and_email:
    #        if partner.email:
    #            partner_details.update({"Em": partner.email})
    #        if partner.phone:
    #            partner_details.update({"Ph": self._l10n_bs_edi_extract_digits(partner.phone)})
    #    #if pos_state_id:
    #    #    partner_details.update({"POS": pos_state_id.l10n_bs_tin or ""})
    #    if set_vat:
    #        partner_details.update({
    #            "LglNm": partner.commercial_partner_id.name,
    #            "GSTIN": partner.vat or "URP",
    #        })
    #    else:
    #        partner_details.update({"Nm": partner.name or partner.commercial_partner_id.name})
    #    # For no country I would suppose it is India, so not sure this is super right
    #    #if is_overseas and (not partner.country_id or partner.country_id.code != 'IN'):
    #    #    partner_details.update({
    #    #        "GSTIN": "URP",
    #    #        "Pin": 999999,
    #    #        "Stcd": "96",
    #    #        "POS": "96",
    #    #    })
    #    return partner_details

    @api.model
    def _round_value(self, amount, precision_digits=2):
        """
            This method is call for rounding.
            If anything is wrong with rounding then we quick fix in method
        """
        value = round(amount, precision_digits)
        # avoid -0.0
        return value if value else 0.0


#    def _ba_edi_generate_invoice_json_managing_negative_lines(self, invoice, json_payload):
#        """Set negative lines against positive lines as discount with same HSN code and tax rate
#
#            With negative lines
#
#            product name | hsn code | unit price | qty | discount | total
#            =============================================================
#            product A    | 123456   | 1000       | 1   | 100      |  900
#            product B    | 123456   | 1500       | 2   | 0        | 3000
#            Discount     | 123456   | -300       | 1   | 0        | -300
#
#            Converted to without negative lines
#
#            product name | hsn code | unit price | qty | discount | total
#            =============================================================
#            product A    | 123456   | 1000       | 1   | 100      |  900
#            product B    | 123456   | 1500       | 2   | 300      | 2700
#
#            totally discounted lines are kept as 0, though
#        """
#        def discount_group_key(line_vals):
#            return "%s-%s"%(line_vals['HsnCd'], line_vals['GstRt'])
#
#        def put_discount_on(discount_line_vals, other_line_vals):
#            discount = discount_line_vals['AssAmt'] * -1
#            discount_to_allow = other_line_vals['AssAmt']
#            if float_compare(discount_to_allow, discount, precision_rounding=invoice.currency_id.rounding) < 0:
#                # Update discount line, needed when discount is more then max line, in short remaining_discount is not zero
#                discount_line_vals.update({
#                    'AssAmt': self._round_value(discount_line_vals['AssAmt'] + other_line_vals['AssAmt']),
#                    'IgstAmt': self._round_value(discount_line_vals['IgstAmt'] + other_line_vals['IgstAmt']),
#                    'CgstAmt': self._round_value(discount_line_vals['CgstAmt'] + other_line_vals['CgstAmt']),
#                    'SgstAmt': self._round_value(discount_line_vals['SgstAmt'] + other_line_vals['SgstAmt']),
#                    'CesAmt': self._round_value(discount_line_vals['CesAmt'] + other_line_vals['CesAmt']),
#                    'CesNonAdvlAmt': self._round_value(discount_line_vals['CesNonAdvlAmt'] + other_line_vals['CesNonAdvlAmt']),
#                    'StateCesAmt': self._round_value(discount_line_vals['StateCesAmt'] + other_line_vals['StateCesAmt']),
#                    'StateCesNonAdvlAmt': self._round_value(discount_line_vals['StateCesNonAdvlAmt'] + other_line_vals['StateCesNonAdvlAmt']),
#                    'OthChrg': self._round_value(discount_line_vals['OthChrg'] + other_line_vals['OthChrg']),
#                    'TotItemVal': self._round_value(discount_line_vals['TotItemVal'] + other_line_vals['TotItemVal']),
#                })
#                other_line_vals.update({
#                    'Discount': self._round_value(other_line_vals['Discount'] + discount_to_allow),
#                    'AssAmt': 0.00,
#                    'IgstAmt': 0.00,
#                    'CgstAmt': 0.00,
#                    'SgstAmt': 0.00,
#                    'CesAmt': 0.00,
#                    'CesNonAdvlAmt': 0.00,
#                    'StateCesAmt': 0.00,
#                    'StateCesNonAdvlAmt': 0.00,
#                    'OthChrg': 0.00,
#                    'TotItemVal': 0.00,
#                })
#                return False
#            other_line_vals.update({
#                'Discount': self._round_value(other_line_vals['Discount'] + discount),
#                'AssAmt': self._round_value(other_line_vals['AssAmt'] + discount_line_vals['AssAmt']),
#                'IgstAmt': self._round_value(other_line_vals['IgstAmt'] + discount_line_vals['IgstAmt']),
#                'CgstAmt': self._round_value(other_line_vals['CgstAmt'] + discount_line_vals['CgstAmt']),
#                'SgstAmt': self._round_value(other_line_vals['SgstAmt'] + discount_line_vals['SgstAmt']),
#                'CesAmt': self._round_value(other_line_vals['CesAmt'] + discount_line_vals['CesAmt']),
#                'CesNonAdvlAmt': self._round_value(other_line_vals['CesNonAdvlAmt'] + discount_line_vals['CesNonAdvlAmt']),
#                'StateCesAmt': self._round_value(other_line_vals['StateCesAmt'] + discount_line_vals['StateCesAmt']),
#                'StateCesNonAdvlAmt': self._round_value(other_line_vals['StateCesNonAdvlAmt'] + discount_line_vals['StateCesNonAdvlAmt']),
#                'OthChrg': self._round_value(other_line_vals['OthChrg'] + discount_line_vals['OthChrg']),
#                'TotItemVal': self._round_value(other_line_vals['TotItemVal'] + discount_line_vals['TotItemVal']),
#            })
#            return True
#
#        discount_lines = []
#        for discount_line in json_payload['ItemList'].copy(): #to be sure to not skip in the loop:
#            if discount_line['AssAmt'] < 0:
#                discount_lines.append(discount_line)
#                json_payload['ItemList'].remove(discount_line)
#        if not discount_lines:
#            return json_payload
#
#        lines_grouped_and_sorted = defaultdict(list)
#        for line in sorted(json_payload['ItemList'], key=lambda i: i['AssAmt'], reverse=True):
#            lines_grouped_and_sorted[discount_group_key(line)].append(line)
#
#        for discount_line in discount_lines:
#            apply_discount_on_lines = lines_grouped_and_sorted.get(discount_group_key(discount_line), [])
#            for apply_discount_on in apply_discount_on_lines:
#                if put_discount_on(discount_line, apply_discount_on):
#                    break
#        return json_payload

#    def _ba_edi_generate_invoice_json_0(self, invoice):
#        tax_details = self._ba_prepare_edi_tax_details(invoice)
#        tax_details_by_code = self._get_ba_tax_details_by_pdv_code(tax_details.get("tax_details", {}))
#   
#        aggregated_items = {
#        }
#
#        for tax_detail in tax_details_by_code:
#            if not tax_detail['pdv_code'] in aggregated_items:
#                aggregated_items[ tax_detail['pdv_code'] ] = {
#                    'base_amount': tax_detail['base_amount'],
#                    'tax_amount': tax_detail['tax_amount'],
#                    'tax_rate': tax_detail['tax_rate'],
#                    'product_type': tax_detail['product_type'],
#                    'move_type': tax_detail['move_type'],
#                    'quantity': 1,
#                }
#            else:
#                aggregated_items[ tax_detail['pdv_code'] ]['base_amount'] += tax_detail['base_amount']
#                aggregated_items[ tax_detail['pdv_code'] ]['tax_amount'] += tax_detail['tax_amount']
#                if aggregated_items[ tax_detail['pdv_code'] ]['product_type'] != tax_detail['product_type']:
#                    aggregated_items[ tax_detail['pdv_code'] ]['product_type'] = 'mixed'
#
#        seller = invoice.company_id.partner_id
#        buyer = invoice.partner_id
#
#        json_payload = {
#            "seller": { 
#                "name": seller.display_name,
#                "email": seller.email,
#                "vat": seller.vat, 
#                "id": seller.company_registry,
#                "country": seller.country_code
#            },
#            "buyer": { 
#                "name": buyer.display_name,
#                "email": buyer.email,
#                "vat": buyer.vat, 
#                "id": buyer.company_registry,
#                "country": buyer.country_code
#            },
#            "sign": invoice.is_inbound() and 1 or -1, # faktura 1, storno -1
#            "rounding_amount": sum(line.balance for line in invoice.line_ids if line.display_type == 'rounding'),
#            "currency": invoice.currency_id.name,  # BAM - Bosna i Hercegovina
#
#            "items": tax_details_by_code,
#
#            # sabrano u jednu stavku dict objekat
#            # {
#            #   'E': { 
#            #           'base_amount': 200.00,
#            #           'tax_amount':  34.00,
#            #           'tax_rate': 17,
#            #           'product_type': (service, product, mixed),
#            #           'quantity': 1,
#            #   }
#            # }
#            "aggregated_items": aggregated_items
#        }
#  
#        return json_payload
   
    def _ba_edi_generate_invoice_json(self, invoice):
        tax_details = self._ba_prepare_edi_tax_details(invoice)
        tax_details_by_code = self._get_ba_tax_details_by_pdv_code(tax_details.get("tax_details", {}))
   
        aggregated_items = {
        }

        invoice_type = "Normal"  # Normal, Copy
        transaction_type = "Sale" # Sale, Refund
        stornirati_fiskalni_number = ""
        stornirati_fiskalni_datum = ""
        nacin_placanja = "WireTransfer"

        for tax_detail in tax_details_by_code:
            nacin_placanja = tax_detail["nacin_placanja"]
            if not tax_detail['pdv_code'] in aggregated_items:
                if tax_detail['move_type'] == "out_refund":
                    transaction_type = "Refund"
                    stornirati_fiskalni_number = tax_detail["refund_ref_number"]
                    stornirati_fiskalni_datum = tax_detail["refund_ref_date"]

                aggregated_items[ tax_detail['pdv_code'] ] = {
                    'base_amount': tax_detail['base_amount'],
                    'tax_amount': tax_detail['tax_amount'],
                    'tax_rate': tax_detail['tax_rate'],
                    'product_type': tax_detail['product_type'],
                    'quantity': 1,
                }
            else:
                aggregated_items[ tax_detail['pdv_code'] ]['base_amount'] += tax_detail['base_amount']
                aggregated_items[ tax_detail['pdv_code'] ]['tax_amount'] += tax_detail['tax_amount']
                if aggregated_items[ tax_detail['pdv_code'] ]['product_type'] != tax_detail['product_type']:
                    aggregated_items[ tax_detail['pdv_code'] ]['product_type'] = 'mixed'

        #seller = invoice.company_id.partner_id
        customer = {
            "idBroj": invoice.partner_id.company_registry,
            "naziv": invoice.partner_id.name,
            "adresa": invoice.partner_id.street,
            "ptt": invoice.partner_id.zip,
            "grad": invoice.partner_id.city
        }

        invoice_items = []

        totalInovice = 0
        for key in aggregated_items.keys():
            pdv_code = key
            invoice_items.append ({
                "name": f"St.{invoice.name}",
                "labels": [ pdv_code ],  # PDV taxe 
                
                "baseAmount": self._round_value(aggregated_items[key]["base_amount"]), # bez PDV
                "taxAmount": self._round_value(aggregated_items[key]["tax_amount"]), # iznos PDV
                "unitPrice": self._round_value(aggregated_items[key]["base_amount"] + aggregated_items[key]["tax_amount"]),
                "discount": self._round_value(0),
                "quantity": aggregated_items[key]["quantity"],

                "totalAmount": self._round_value(aggregated_items[key]["base_amount"] + aggregated_items[key]["tax_amount"]),
            })
            totalInovice += aggregated_items[key]["base_amount"] + aggregated_items[key]["tax_amount"]

        payments = [
            {
                "amount": self._round_value(totalInovice),
                "paymentType": nacin_placanja     # "Cash", "Card", "WireTransfer", "Other"
            }
        ]

        json_payload = {
           "invoiceRequest": {
               "referentDocumentNumber": stornirati_fiskalni_number,
               "referentDocumentDT": stornirati_fiskalni_datum.strftime("%Y-%m-%d") if stornirati_fiskalni_datum else "",
               "erpDocument": invoice.name,
               "invoiceType": invoice_type,    # Normal, Copy
               "transactionType": transaction_type,   # Sale, Refund
               "payment": payments,
               "items": invoice_items,
               "cashier": "000001",
               "customer": customer
            },
        }
  
        return json_payload
       
    @api.model
    def _ba_prepare_edi_tax_details(self, move, in_foreign=False, filter_invl_to_apply=None):
        def ba_grouping_key_generator(base_line, tax_values):
            invl = base_line['record']
            tax = tax_values['tax_repartition_line'].tax_id
            tags = tax_values['tax_repartition_line'].tag_ids

            move_type = invl.move_id.move_type # 'out_invoice', 'out_refund'
            payment_term = invl.move_id.invoice_payment_term_id.name
            nacin_placanja = 'WireTransfer'
            if payment_term:
                if payment_term.upper() in IN_GOTOVINA:
                    nacin_placanja = 'Cash'
                elif payment_term and payment_term.upper() in IN_KARTICA:
                    nacin_placanja = 'Card'

            # ako je storno račun, način plaćanja se može navesti samo u opisu računa
            #if move_type == "out_refund":
            if invl.move_id.narration:
                if any(token in invl.move_id.narration.upper() for token in IN_GOTOVINA):
                    nacin_placanja = 'Cash'
                elif any(token in invl.move_id.narration.upper() for token in IN_KARTICA):
                    nacin_placanja = 'Card'

            refund_ref_number = None
            refund_ref_date = None
            if move_type == 'out_refund':
                refund_ref_number = invl.move_id.reversed_entry_id.ba_edi_fiskalni_broj
                refund_ref_date = invl.move_id.reversed_entry_id.invoice_date

            pdv_code = "other"
            #if not invl.currency_id.is_zero(tax_values['tax_amount_currency']):
            for pdv_tag in [ "A", "E", "K"]:
                if any(tag in tags for tag in self.env.ref("l10n_bs.tax_tag_%s"%(pdv_tag))):
                    pdv_code = pdv_tag
            return {
                "move_type": move_type,
                "nacin_placanja": nacin_placanja,
                "refund_ref_number": refund_ref_number,
                "refund_ref_date": refund_ref_date,
                "tax": tax,
                "base_product_id": invl.product_id,
                "tax_product_id": invl.product_id,
                "base_product_uom_id": invl.product_uom_id,
                "tax_product_uom_id": invl.product_uom_id,
                "pdv_code": pdv_code,
            }

        def ba_filter_to_apply(base_line, tax_values):
            if base_line['record'].display_type == 'rounding':
                return False
            return True

        return move._prepare_edi_tax_details(
            filter_to_apply=ba_filter_to_apply,
            grouping_key_generator=ba_grouping_key_generator,
            filter_invl_to_apply=filter_invl_to_apply,
        )

    @api.model
    def _get_ba_tax_details_by_pdv_code(self, tax_details):
        items = []
        for tax_detail in tax_details.values():
            if 'pdv_code' in tax_detail:
                # move_lines
                # tax_detail["records"] - stavke racuna
                # ovo je jedna stavka
                stavke = []

                # tip_proizvoda = service, product
                #  select pt.detailed_type tip_proizvoda, account_move_line.name, tax_audit, tax_base_amount, account_account_tag_account_move_line_rel.*, account_account_tag.name from account_move_line 
                #   --join account_move_line_account_tax_rel on account_move_line.id=account_move_line_account_tax_rel.account_move_line_id 
                #   join account_account_tag_account_move_line_rel  on account_account_tag_account_move_line_rel.account_move_line_id=account_move_line.id
                #   left join account_account_tag on  account_account_tag.id=account_account_tag_account_move_line_rel.account_account_tag_id 
                #   left join product_product pr on pr.id=account_move_line.product_id 
                #   left join product_template pt on pt.id=pr.product_tmpl_id
                #   where move_name = 'INV/2025/00054'
   
                for move_line in tax_detail["records"]:
                    stavke.append(
                        { 
                          "name": move_line.name,
                          "quantity": move_line.quantity,
                          "unit_price": move_line.price_unit,
                          "discount_percent": move_line.discount,
                          "product_type": move_line.product_id.product_tmpl_id.detailed_type
                        }
                    )

                item = { 
                        'move_type': tax_detail["move_type"],
                        'nacin_placanja': tax_detail["nacin_placanja"],
                        'refund_ref_number': tax_detail["refund_ref_number"],
                        'refund_ref_date': tax_detail["refund_ref_date"],
                        'pdv_code': tax_detail["pdv_code"],
                        'base_amount': tax_detail["base_amount"],
                        'tax_amount': tax_detail["tax_amount"],
                        'tax_rate': tax_detail["tax"].amount,
                        'move_lines': stavke,
                        'artikal': tax_detail["base_product_id"].name,
                        'jmj': tax_detail["base_product_id"].uom_id.name,
                        'quantity': 1,
                        'unit_price': tax_detail["base_amount"],
                        'discount_percent': 0,
                        'product_type': 'service'
                    }
                
                if len(stavke) == 1:
                    item['quantity'] = stavke[0]["quantity"]
                    item['unit_price'] = stavke[0]["unit_price"]
                    item['discount_percent'] = stavke[0]["discount_percent"]
                    item['product_type'] = stavke[0]["product_type"]

                items.append(item)
             
        return items

    

    #@api.model
    #def _l10n_bs_edi_connect_to_server(self, company, url_path, params):
    #    #user_token = self.env["iap.account"].get("l10n_bs_edi")
    #    params.update({
    #        #"account_token": user_token.account_token,
    #        "dbuuid": self.env["ir.config_parameter"].sudo().get_param("database.uuid"),
    #        "username": company.sudo().l10n_bs_edi_username,
    #        "gstin": company.vat,
    #    })
    #    if company.sudo().l10n_bs_edi_production_env:
    #        default_endpoint = DEFAULT_IAP_ENDPOINT
    #    else:
    #        default_endpoint = DEFAULT_IAP_TEST_ENDPOINT
    #    endpoint = self.env["ir.config_parameter"].sudo().get_param("l10n_bs_edi.endpoint", default_endpoint)
    #    url = "%s%s" % (endpoint, url_path)
    #    try:
    #        return jsonrpc(url, params=params, timeout=25)
    #    except AccessError as e:
    #        _logger.warning("Connection error: %s", e.args[0])
    #        return {
    #            "error": [{
    #                "code": "404",
    #                "message": _("Unable to connect to the online E-invoice service."
    #                    "The web service may be temporary down. Please try again in a moment.")
    #            }]
    #        }

    #@api.model
    #def _l10n_bs_edi_authenticate(self, company):
    #    params = {"password": company.sudo().l10n_bs_edi_password}
    #    response = self._l10n_bs_edi_connect_to_server(company, url_path="/iap/l10n_bs_edi/1/authenticate", params=params)
    #    # validity data-time in Bosnian standard time(UTC+05:30) so remove that gap and store in odoo
    #    if "data" in response:
    #        tz = pytz.timezone("Asia/Kolkata")
    #        local_time = tz.localize(fields.Datetime.to_datetime(response["data"]["TokenExpiry"]))
    #        utc_time = local_time.astimezone(pytz.utc)
    #        company.sudo().l10n_bs_edi_token_validity = fields.Datetime.to_string(utc_time)
    #        company.sudo().l10n_bs_edi_token = response["data"]["AuthToken"]
    #    return response

    #@api.model
    #def _l10n_bs_edi_generate(self, company, json_payload):
    #    #token = self._l10n_bs_edi_get_token(company)
    #    #if not token:
    #    #    return self._l10n_bs_edi_no_config_response()
    #    params = {
    #        #"auth_token": token,
    #        "json_payload": json_payload,
    #    }
    #    return self._l10n_bs_edi_connect_to_server(company, url_path="/iap/l10n_bs_edi/1/generate", params=params)

    #@api.model
    #def _l10n_bs_edi_get_irn_by_details(self, company, json_payload):
    #    #token = self._l10n_bs_edi_get_token(company)
    #    #if not token:
    #    #    return self._l10n_bs_edi_no_config_response()
    #    params = {
    #        #"auth_token": token,
    #    }
    #    params.update(json_payload)
    #    return self._l10n_bs_edi_connect_to_server(
    #        company,
    #        url_path="/iap/l10n_bs_edi/1/getirnbydocdetails",
    #        params=params,
    #    )

    @api.model
    def _l10n_bs_edi_cancel(self, company, json_payload):
        token = self._l10n_bs_edi_get_token(company)
        if not token:
            return self._l10n_bs_edi_no_config_response()
        params = {
            "auth_token": token,
            "json_payload": json_payload,
        }
        return self._l10n_bs_edi_connect_to_server(company, url_path="/iap/l10n_bs_edi/1/cancel", params=params)
