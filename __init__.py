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
        SalePaymentForm,
        Company,
        PrintReportSalesStart,
        User,
        StatementLine,
        module='nodux_sale_one', type_='model')
    Pool.register(
        WizardSalePayment,
        PrintReportSales,
        module='nodux_sale_one', type_='wizard')
    Pool.register(
        SaleReportPos,
        ReportSales,
        SalePaymentReport,
        module='nodux_sale_one', type_='report')
