# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.

from trytond.pool import Pool
from .sale import *
from .company import *
from .user import *

def register():
    Pool.register(
        Sale,
        SaleLine,
        SequenceSale,
        SalePaymentForm,
        Company,
        PrintReportSalesStart,
        User,
        StatementLine,
        PrintReportPaymentsStart,
        PrintCloseCashStart,
        module='nodux_sale_one', type_='model')
    Pool.register(
        WizardSalePayment,
        PrintReportSales,
        PrintReportPayments,
        PrintCloseCash,
        module='nodux_sale_one', type_='wizard')
    Pool.register(
        SaleReportPos,
        ReportSales,
        SalePaymentReport,
        ReportPayments,
        CloseCash,
        module='nodux_sale_one', type_='report')
