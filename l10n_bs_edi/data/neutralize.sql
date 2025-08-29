-- disable l10n_bs_edi integration
UPDATE res_company
   SET l10n_bs_edi_production_env = false,
       l10n_bs_edi_api_key = NULL,
       l10n_bs_edi_api_host = NULL;
