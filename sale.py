#! -*- coding: utf8 -*-

from decimal import Decimal
from datetime import datetime
from trytond.model import Workflow, ModelView, ModelSQL, fields
from trytond.pool import PoolMeta, Pool
from trytond.transaction import Transaction
from trytond.pyson import Bool, Eval, Not, If, PYSONEncoder, Id
from trytond.wizard import (Wizard, StateView, StateAction, StateTransition,
    Button)
from trytond.modules.company import CompanyReport
from trytond.pyson import If, Eval, Bool, PYSONEncoder, Id
from trytond.transaction import Transaction
from trytond.pool import Pool, PoolMeta
from trytond.report import Report
conversor = None
try:
    from numword import numword_es
    conversor = numword_es.NumWordES()
except:
    print("Warning: Does not possible import numword module!")
    print("Please install it...!")
import pytz
from datetime import datetime,timedelta
import time


__all__ = ['Sale', 'SaleLine','SalePaymentForm', 'WizardSalePayment',
'SaleReportPos', 'PrintReportSalesStart', 'PrintReportSales', 'ReportSales',
'StatementLine', 'SalePaymentReport', 'PrintReportPaymentsStart',
'PrintReportPayments', 'ReportPayments', 'SequenceSale']

_ZERO = Decimal(0)

class Sale(Workflow, ModelSQL, ModelView):
    'Sale'
    __name__ = 'sale.sale'
    _rec_name = 'reference'

    company = fields.Many2One('company.company', 'Company', required=True,
        states={
            'readonly': (Eval('state') != 'draft') | Eval('lines', [0]),
            },
        domain=[
            ('id', If(Eval('context', {}).contains('company'), '=', '!='),
                Eval('context', {}).get('company', -1)),
            ],
        depends=['state'], select=True)
    reference = fields.Char('Number', readonly=True, select=True)
    description = fields.Char('Description',
        states={
            'readonly': ~Eval('state').in_(['draft', 'quotation']),
            },
        depends=['state'])
    state = fields.Selection([
        ('draft', 'Draft'),
        ('quotation', 'Quotation'),
        ('confirmed', 'Confirmed'),
        ('done', 'Done'),
        ('anulled', 'Anulled'),
    ], 'State', readonly=True, required=True)
    sale_date = fields.Date('Sale Date', required=True,
        states={
            'readonly': ~Eval('state').in_(['draft', 'quotation']),
            },
        depends=['state'])
    party = fields.Many2One('party.party', 'Party', required=True, select=True,
        states={
            'readonly': ~Eval('state').in_(['draft', 'quotation']),
            },
        depends=['state'])
    party_lang = fields.Function(fields.Char('Party Language'),
        'on_change_with_party_lang')

    currency = fields.Many2One('currency.currency', 'Currency', required=True,
        states={
            'readonly': (Eval('state') != 'draft') |
                (Eval('lines', [0]) & Eval('currency', 0)),
            },
        depends=['state'])
    currency_digits = fields.Function(fields.Integer('Currency Digits'),
        'on_change_with_currency_digits')
    lines = fields.One2Many('sale.line', 'sale', 'Lines', states={
            'readonly': ~Eval('state').in_(['draft', 'quotation']),
            },
        depends=['party', 'state'])
    comment = fields.Text('Comment')
    untaxed_amount = fields.Function(fields.Numeric('Untaxed',
            digits=(16, Eval('currency_digits', 2)),
            depends=['currency_digits']), 'get_amount')
    untaxed_amount_cache = fields.Numeric('Untaxed Cache',
        digits=(16, Eval('currency_digits', 2)),
        readonly=True,
        depends=['currency_digits'])
    tax_amount = fields.Function(fields.Numeric('Tax',
            digits=(16, Eval('currency_digits', 2)),
            depends=['currency_digits']), 'get_amount')
    tax_amount_cache = fields.Numeric('Tax Cache',
        digits=(16, Eval('currency_digits', 2)),
        readonly=True,
        depends=['currency_digits'])
    total_amount = fields.Function(fields.Numeric('Total',
            digits=(16, Eval('currency_digits', 2)),
            depends=['currency_digits']), 'get_amount')
    total_amount_cache = fields.Numeric('Total Tax',
        digits=(16, Eval('currency_digits', 2)),
        readonly=True,
        depends=['currency_digits'])

    paid_amount = fields.Numeric('Paid Amount', readonly=True)
    residual_amount = fields.Numeric('Residual Amount', readonly=True)
    days = fields.Integer('Credit days', states={
            'readonly': ~Eval('state').in_(['draft', 'quotation']),
            })
    state_date = fields.Function(fields.Char('State dy Date', readonly=True), 'get_state_date')
    payments = fields.One2Many('sale.payments', 'sale', 'Payments', readonly=True)
    price_list = fields.Many2One('product.price_list', 'PriceList')
    sale_note = fields.Boolean('Sale Note', states={
        'readonly': (Eval('state') != 'draft'),
    })

    @classmethod
    def __register__(cls, module_name):
        transaction = Transaction()
        cursor = transaction.connection.cursor()
        sql_table = cls.__table__()

        super(Sale, cls).__register__(module_name)
        cls._order.insert(0, ('sale_date', 'DESC'))
        cls._order.insert(1, ('id', 'DESC'))

    @classmethod
    def __setup__(cls):
        super(Sale, cls).__setup__()
        cls._transitions |= set((
                ('draft', 'quotation'),
                ('draft', 'confirmed'),
                ('draft', 'done'),
                ('quotation', 'confirmed'),
                ('quotation', 'done'),
                ('confirmed', 'done'),
                ('done', 'anulled'),
                ))

        cls._buttons.update({
                'wizard_sale_payment': {
                    'invisible': (Eval('state').in_(['done', 'anulled'])),
                    'readonly': Not(Bool(Eval('lines'))),
                    },
                'quote': {
                    'invisible': Eval('state') != 'draft',
                    'readonly': ~Eval('lines', []),
                    },
                'anull': {
                    'invisible': (Eval('state').in_(['draft', 'anulled', 'confirm'])),
                    'readonly': Not(Bool(Eval('lines'))),
                    },
                })

        cls._states_cached = ['confirmed', 'processing', 'done', 'cancel']

    @classmethod
    def delete(cls, sales):
        for sale in sales:
            if (sale.state == 'confirmed'):
                cls.raise_user_error('No puede eliminar la venta %s,\nporque ya ha sido confirmada',(sale.reference))
            if (sale.state == 'done'):
                cls.raise_user_error('No puede eliminar la venta %s,\nporque ya ha sido realizada',(sale.reference))
            if (sale.state == 'anulled'):
                cls.raise_user_error('No puede eliminar la venta %s,\nporque ha sido anulada',(sale.reference))
        super(Sale, cls).delete(sales)

    @staticmethod
    def default_party():
        User = Pool().get('res.user')
        user = User(Transaction().user)
        return user.company.default_party.id if user.company and user.company.default_party else None

    @classmethod
    def copy(cls, sales, default=None):
        Date = Pool().get('ir.date')
        date = Date.today()
        if default is None:
            default = {}
        default = default.copy()
        default['state'] = 'draft'
        default['reference'] = None
        default['paid_amount'] = Decimal(0.0)
        default['residual_amount'] = None
        default['sale_date'] = date
        default['payments'] = None
        return super(Sale, cls).copy(sales, default=default)

    @classmethod
    def get_state_date(cls, sales, names):
        pool = Pool()
        Date = pool.get('ir.date')
        date = Date.today()
        result = {n: {s.id: Decimal(0) for s in sales} for n in names}
        for name in names:
            for sale in sales:
                days = (date - sale.sale_date).days
                if sale.days >= days:
                    result[name][sale.id] = ''
                else:
                    result[name][sale.id] = 'vencida'

        return result

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    @staticmethod
    def default_days():
        return 0

    @staticmethod
    def default_sale_date():
        date = Pool().get('ir.date')
        return date.today()

    @staticmethod
    def default_paid_amount():
        return Decimal(0.0)

    @staticmethod
    def default_state():
        return 'draft'

    @staticmethod
    def default_currency():
        Company = Pool().get('company.company')
        company = Transaction().context.get('company')
        if company:
            return Company(company).currency.id

    @staticmethod
    def default_currency_digits():
        Company = Pool().get('company.company')
        company = Transaction().context.get('company')
        if company:
            return Company(company).currency.digits
        return 2

    @fields.depends('currency')
    def on_change_with_currency_digits(self, name=None):
        if self.currency:
            return self.currency.digits
        return 2

    @fields.depends('party')
    def on_change_with_party_lang(self, name=None):
        Config = Pool().get('ir.configuration')
        if self.party and self.party.lang:
            return self.party.lang.code
        return Config.get_language()

    @fields.depends('lines', 'currency', 'party')
    def on_change_lines(self):
        self.untaxed_amount = Decimal('0.0')
        self.tax_amount = Decimal('0.0')
        self.total_amount = Decimal('0.0')

        if self.lines:
            self.untaxed_amount = reduce(lambda x, y: x + y,
                [(getattr(l, 'amount', None) or Decimal(0))
                    for l in self.lines if l.type == 'line'], Decimal(0)
                )
            self.total_amount = reduce(lambda x, y: x + y,
                [(getattr(l, 'amount_w_tax', None) or Decimal(0))
                    for l in self.lines if l.type == 'line'], Decimal(0)
                )

        if self.currency:
            self.untaxed_amount = self.currency.round(self.untaxed_amount)
            self.total_amount = self.currency.round(self.total_amount)
        self.tax_amount = self.total_amount - self.untaxed_amount
        if self.currency:
            self.tax_amount = self.currency.round(self.tax_amount)

    @fields.depends('days', 'party')
    def on_change_days(self, name=None):
        if self.party:
            if self.party.type_document == '07':
                self.days = 0
            elif self.party.vat_number == '9999999999999':
                self.days = 0
            elif self.party.name.lower() == 'consumidor final':
                self.days = 0

    def get_tax_amount(self):
        tax = _ZERO
        taxes = _ZERO


        for line in self.lines:
            if line.type != 'line':
                continue
            if line.product:
                if line.product.taxes_category == True:
                    impuesto = line.product.category.taxes
                else:
                    impuesto = line.product.taxes
                if impuesto == 'iva0':
                    value = Decimal(0.0)
                elif impuesto == 'no_iva':
                    value = Decimal(0.0)
                elif impuesto == 'iva12':
                    value = Decimal(0.12)
                elif impuesto == 'iva14':
                    value = Decimal(0.14)
                else:
                    value = Decimal(0.0)
                tax = (line.unit_price*Decimal(line.quantity)) * value
                taxes += tax

        return (self.currency.round(taxes))

    @classmethod
    def get_amount(cls, sales, names):
        untaxed_amount = {}
        tax_amount = {}
        total_amount = {}

        if {'tax_amount', 'total_amount'} & set(names):
            compute_taxes = True
        else:
            compute_taxes = False
        # Sort cached first and re-instanciate to optimize cache management
        sales = sorted(sales, key=lambda s: s.state in cls._states_cached,
            reverse=True)
        sales = cls.browse(sales)
        for sale in sales:
            if (sale.state in cls._states_cached
                    and sale.untaxed_amount_cache is not None
                    and sale.tax_amount_cache is not None
                    and sale.total_amount_cache is not None):
                untaxed_amount[sale.id] = sale.untaxed_amount_cache
                if compute_taxes:
                    tax_amount[sale.id] = sale.tax_amount_cache
                    total_amount[sale.id] = sale.total_amount_cache
            else:
                untaxed_amount[sale.id] = sum(
                    (line.amount for line in sale.lines
                        if line.type == 'line'), _ZERO)
                if compute_taxes:
                    tax_amount[sale.id] = sale.get_tax_amount()
                    total_amount[sale.id] = (
                        untaxed_amount[sale.id] + tax_amount[sale.id])

        result = {
            'untaxed_amount': untaxed_amount,
            'tax_amount': tax_amount,
            'total_amount': total_amount,
            }
        for key in result.keys():
            if key not in names:
                del result[key]
        return result

    def get_amount2words(self, value):
        if conversor:
            return (conversor.cardinal(int(value))).upper()
        else:
            return ''

    @classmethod
    @ModelView.button
    @Workflow.transition('quotation')
    def quote(cls, sales):
        cls.write([s for s in sales], {
                'state': 'quotation',
                })

    @classmethod
    @ModelView.button
    @Workflow.transition('anulled')
    def anull(cls, sales):
        for sale in sales:
            cls.raise_user_warning('anull%s' % sale.reference,
                   'Esta seguro de anular la venta: "%s"', (sale.reference))
            for line in sale.lines:
                product = line.product.template
                if product.type == "goods":
                    if line.unit == product.default_uom:
                        product.total = Decimal(line.product.template.total) + Decimal(line.quantity)
                        product.save()
                    else:
                        product.total = Decimal(str(round(Decimal(line.product.template.total + Decimal(line.quantity * line.unit.factor)),8)))
                        product.save()

        cls.write([s for s in sales], {
                'state': 'anulled',
                })


    @classmethod
    @ModelView.button_action('nodux_sale_one.wizard_sale_payment')
    def wizard_sale_payment(cls, sales):
        pass

class StatementLine(ModelSQL, ModelView):
    'Statement Line'
    __name__ = 'sale.payments'

    sequence = fields.Integer('Sequence')
    sale = fields.Many2One('sale.sale', 'Sale', ondelete='RESTRICT')
    date = fields.Date('Date', readonly=True)
    amount = fields.Numeric('Amount', readonly = True)

class SequenceSale(ModelSQL, ModelView):
    'Point of Sale'
    __name__ = 'sale.sequence'

    name = fields.Char('Name', required=True)
    sequence_sale = fields.Integer('Sequence Sale', required=True)
    sequence_sale_note = fields.Integer('Sequence Sale Note', required=True)
    emision = fields.Char('Emission Point', required=True)

class SaleLine(ModelSQL, ModelView):
    'Sale Line'
    __name__ = 'sale.line'
    _rec_name = 'description'
    sale = fields.Many2One('sale.sale', 'Sale', ondelete='CASCADE',
        select=True)
    sequence = fields.Integer('Sequence')
    type = fields.Selection([
        ('line', 'Line'),
        ], 'Type', select=True, required=True)
    quantity = fields.Float('Quantity',
        digits=(16, Eval('unit_digits', 2)),
        states={
            'invisible': Eval('type') != 'line',
            'required': Eval('type') == 'line',
            'readonly': ~Eval('_parent_sale', {}),
            },
        depends=['type', 'unit_digits'])
    unit = fields.Many2One('product.uom', 'Unit',
            states={
                'required': Bool(Eval('product')),
                'invisible': Eval('type') != 'line',
                'readonly': ~Eval('_parent_sale', {}),
            },
        domain=[
            If(Bool(Eval('product_uom_category')),
                ('category', '=', Eval('product_uom_category')),
                ('category', '!=', -1)),
            ],
        depends=['product', 'type', 'product_uom_category'])
    unit_digits = fields.Function(fields.Integer('Unit Digits'),
        'on_change_with_unit_digits')
    product = fields.Many2One('product.product', 'Product',
        states={
            'invisible': Eval('type') != 'line',
            'readonly': ~Eval('_parent_sale', {}),
            }, depends=['type'])
    product_uom_category = fields.Function(
        fields.Many2One('product.uom.category', 'Product Uom Category'),
        'on_change_with_product_uom_category')
    unit_price = fields.Numeric('Unit Price', digits=(16, 4),
        states={
            'invisible': Eval('type') != 'line',
            'required': Eval('type') == 'line',
            }, depends=['type'])
    amount = fields.Function(fields.Numeric('Amount',
            digits=(16, Eval('_parent_sale', {}).get('currency_digits', 2)),
            states={
                'invisible': ~Eval('type').in_(['line', 'subtotal']),
                'readonly': ~Eval('_parent_sale'),
                },
            depends=['type']), 'get_amount')
    description = fields.Text('Description', size=None, required=True)

    unit_price_w_tax = fields.Function(fields.Numeric('Unit Price with Tax',
            digits=(16, Eval('_parent_sale', {}).get('currency_digits',
                    Eval('currency_digits', 2))),
            states={
                'invisible': Eval('type') != 'line',
                },
            depends=['type', 'currency_digits']), 'get_price_with_tax')
    amount_w_tax = fields.Function(fields.Numeric('Amount with Tax',
            digits=(16, Eval('_parent_sale', {}).get('currency_digits',
                    Eval('currency_digits', 2))),
            states={
                'invisible': ~Eval('type').in_(['line', 'subtotal']),
                },
            depends=['type', 'currency_digits']), 'get_price_with_tax')
    currency_digits = fields.Function(fields.Integer('Currency Digits'),
        'on_change_with_currency_digits')
    currency = fields.Many2One('currency.currency', 'Currency',
        states={
            'required': ~Eval('sale'),
            },
        depends=['sale'])

    discount = fields.Numeric('Percent Discount', states={
        'invisible': Eval('desglose', True),
    })
    desglose = fields.Boolean('Aplicar descuento con desglose')
    discount_desglose = fields.Numeric('Discount', states={
        'invisible': ~Eval('desglose', True),
    })


    @classmethod
    def __setup__(cls):
        super(SaleLine, cls).__setup__()

        # Allow edit product, quantity and unit in lines without parent sale
        for fname in ('product', 'quantity', 'unit'):
            field = getattr(cls, fname)
            if field.states.get('readonly'):
                del field.states['readonly']

        if 'discount_desglose' not in cls.unit_price_w_tax.on_change_with:
            cls.unit_price_w_tax.on_change_with.add('discount_desglose')
        if 'discount_desglose' not in cls.amount_w_tax.on_change_with:
            cls.amount_w_tax.on_change_with.add('discount_desglose')
        if 'discount_desglose' not in cls.amount.on_change_with:
            cls.amount.on_change_with.add('discount_desglose')

        if 'discount' not in cls.unit_price_w_tax.on_change_with:
            cls.unit_price_w_tax.on_change_with.add('discount')
        if 'discount' not in cls.amount_w_tax.on_change_with:
            cls.amount_w_tax.on_change_with.add('discount')
        if 'discount' not in cls.amount.on_change_with:
            cls.amount.on_change_with.add('discount')

        cls.quantity.on_change.add('_parent_sale.price_list')
        cls.unit.on_change.add('_parent_sale.price_list')
        cls.product.on_change.add('_parent_sale.price_list')

    @staticmethod
    def default_type():
        return 'line'

    @staticmethod
    def default_quantity():
        return 1

    @staticmethod
    def default_unit_digits():
        return 2

    @staticmethod
    def default_sale():
        if Transaction().context.get('sale'):
            return Transaction().context.get('sale')
        return None

    @staticmethod
    def default_currency_digits():
        Company = Pool().get('company.company')
        if Transaction().context.get('company'):
            company = Company(Transaction().context['company'])
            return company.currency.digits
        return 2

    @staticmethod
    def default_currency():
        Company = Pool().get('company.company')
        if Transaction().context.get('company'):
            company = Company(Transaction().context['company'])
            return company.currency.id

    @fields.depends('unit')
    def on_change_with_unit_digits(self, name=None):
        if self.unit:
            return self.unit.digits
        return 2

    @fields.depends('product')
    def on_change_with_product_uom_category(self, name=None):
        if self.product:
            return self.product.default_uom_category.id

    def _get_context_sale_price(self):
        context = {}
        if getattr(self, 'sale', None):
            if getattr(self.sale, 'currency', None):
                context['currency'] = self.sale.currency.id
            if getattr(self.sale, 'party', None):
                context['customer'] = self.sale.party.id
            if getattr(self.sale, 'sale_date', None):
                context['sale_date'] = self.sale.sale_date
        if self.sale and getattr(self.sale, 'price_list', None):
            context['price_list'] = self.sale.price_list.id
        if self.unit:
            context['uom'] = self.unit.id
        else:
            if self.product:
                context['uom'] = self.product.default_uom.id
        return context

    @fields.depends('currency')
    def on_change_with_currency_digits(self, name=None):
        if self.currency:
            return self.currency.digits
        return 2

    def get_amount(self, name):
        if self.type == 'line':
            return self.on_change_with_amount()
        elif self.type == 'subtotal':
            amount = Decimal('0.0')
            for line2 in self.sale.lines:
                if line2.type == 'line':
                    amount += line2.sale.currency.round(
                        Decimal(str(line2.quantity)) * line2.unit_price)
                elif line2.type == 'subtotal':
                    if self == line2:
                        break
                    amount = Decimal('0.0')
            return amount
        return Decimal('0.0')

    @fields.depends('product', 'unit', 'quantity', 'description',
        '_parent_sale.party', '_parent_sale.currency',
        '_parent_sale.sale_date')
    def on_change_product(self):
        Product = Pool().get('product.product')
        if not self.product:
            return
        party = None
        party_context = {}
        if self.sale and self.sale.party:
            party = self.sale.party
            if party.lang:
                party_context['language'] = party.lang.code

        category = self.product.default_uom.category
        if not self.unit or self.unit not in category.uoms:
            self.unit = self.product.default_uom.id
            self.unit = self.product.default_uom
            self.unit.rec_name = self.product.default_uom.rec_name
            self.unit_digits = self.product.default_uom.digits

        with Transaction().set_context(self._get_context_sale_price()):
            self.unit_price = Product.get_sale_price([self.product],
                    self.quantity or 0)[self.product.id]
            if self.unit_price:
                self.unit_price = self.unit_price.quantize(
                    Decimal(1) / 10 ** self.__class__.unit_price.digits[1])

        self.unit_price = self.unit_price
        self.type = 'line'
        self.amount = self.on_change_with_amount()
        self.description =  self.product.name
        self.discount = Decimal(0.0)
        self.discount_desglose = Decimal(0.0)

    @fields.depends('product', 'unit', 'quantity', 'description',
        '_parent_sale.currency', 'unit_price', 'discount')
    def on_change_discount(self):
        Product = Pool().get('product.product')
        if not self.product:
            return

        if self.discount > Decimal(0.0) and self.discount < Decimal(100.0) \
            and self.unit_price:
            self.unit_price = Product.get_sale_price([self.product],
                self.quantity or 0)[self.product.id]
            discount = self.discount
            self.unit_price= self.unit_price - (self.unit_price  * discount)
            self.unit_price.quantize(
                    Decimal(1) / 10 ** self.__class__.unit_price.digits[1])
            self.discount_desglose = Decimal(0.0)
        else:
            self.unit_price = Product.get_sale_price([self.product],
                self.quantity or 0)[self.product.id]
            if self.unit_price:
                self.unit_price = self.unit_price.quantize(
                    Decimal(1) / 10 ** self.__class__.unit_price.digits[1])
            self.discount = Decimal(0.0)
            self.discount_desglose = Decimal(0.0)

    @fields.depends('product', 'unit', 'quantity', 'description',
        '_parent_sale.currency', 'unit_price', 'discount', 'discount_desglose')
    def on_change_discount_desglose(self):
        Product = Pool().get('product.product')
        if not self.product:
            return

        if self.discount_desglose > Decimal(0.0) and self.unit_price:

            desglose = self.discount_desglose
            rate = 0
            if self.quantity:
                if self.product.taxes_category == True:
                    if self.product.category.taxes == "iva0":
                        rate = 0
                    elif self.product.category.taxes =="no_iva":
                        rate = 0
                    elif self.product.category.taxes == "iva12":
                        rate = 0.12
                    elif self.product.category.taxes == "iva14":
                        rate = 0.14
                else:
                    if self.product.taxes == "iva0":
                        rate = 0
                    elif self.product.taxes =="no_iva":
                        rate = 0
                    elif self.product.taxes == "iva12":
                        rate = 0.12
                    elif self.product.taxes == "iva14":
                        rate = 0.14

                porcentaje = Decimal(1 + rate)
                unit_price = (desglose / porcentaje)

            self.unit_price = unit_price
            self.unit_price.quantize(
                    Decimal(1) / 10 ** self.__class__.unit_price.digits[1])
            self.discount = Decimal(0.0)
        else:
            self.unit_price = Product.get_sale_price([self.product],
                self.quantity or 0)[self.product.id]
            if self.unit_price:
                self.unit_price = self.unit_price.quantize(
                    Decimal(1) / 10 ** self.__class__.unit_price.digits[1])
            self.discount = Decimal(0.0)
            self.discount_desglose = Decimal(0.0)

    @fields.depends('product', 'quantity', 'unit',
        '_parent_sale.currency', '_parent_sale.party',
        '_parent_sale.sale_date', 'description', 'discount')
    def on_change_quantity(self):
        Product = Pool().get('product.product')
        if self.product:
            if self.discount:
                if self.discount > Decimal(0.0) and self.discount < Decimal(0.0):
                    self.unit_price = self.unit_price*self.quantity
                    if self.unit_price:
                        self.unit_price = self.unit_price.quantize(
                            Decimal(1) / 10 ** self.__class__.unit_price.digits[1])
            else:
                with Transaction().set_context(
                        self._get_context_sale_price()):
                    self.unit_price = Product.get_sale_price([self.product],
                        self.quantity or 0)[self.product.id]
                    if self.unit_price:
                        self.unit_price = self.unit_price.quantize(
                            Decimal(1) / 10 ** self.__class__.unit_price.digits[1])

    @fields.depends(methods=['quantity'])
    def on_change_unit(self):
        self.on_change_quantity()

    @fields.depends('type', 'quantity', 'unit_price', 'unit',
        '_parent_sale.currency')
    def on_change_with_amount(self):
        if self.type == 'line':
            currency = self.sale.currency if self.sale else None
            amount = Decimal(str(self.quantity or '0.0')) * \
                (self.unit_price or Decimal('0.0'))
            if currency:
                return currency.round(amount)
            return amount
        return Decimal('0.0')

    @classmethod
    def get_price_with_tax(cls, lines, names):
        pool = Pool()
        amount_w_tax = {}
        unit_price_w_tax = {}
        tax_amount = Decimal(0.0)
        value = Decimal(0.0)

        def compute_amount_with_tax(line):
            tax_amount = Decimal(0.0)
            if line.product.taxes_category == True:
                impuesto = line.product.category.taxes
            else:
                impuesto = line.product.taxes
            if impuesto == 'iva0':
                value = Decimal(0.0)
            elif impuesto == 'no_iva':
                value = Decimal(0.0)
            elif impuesto == 'iva12':
                value = Decimal(0.12)
            elif impuesto == 'iva14':
                value = Decimal(0.14)
            else:
                value = Decimal(0.0)

            if line.unit_price:
                tax_amount = (line.unit_price * Decimal(line.quantity)) * value
            return line.get_amount(None) + tax_amount

        for line in lines:
            amount = Decimal('0.0')
            unit_price = Decimal('0.0')
            currency = (line.sale.currency if line.sale else line.currency)

            if line.type == 'line':
                if line.quantity and line.product:
                    amount = compute_amount_with_tax(line)
                    unit_price = amount / Decimal(str(line.quantity))
                elif line.product:
                    old_quantity = line.quantity
                    line.quantity = 1.0
                    unit_price = compute_amount_with_tax(line)
                    line.quantity = old_quantity

            # Only compute subtotals if the two fields are provided to speed up

            if currency:
                amount = currency.round(amount)
            amount_w_tax[line.id] = amount
            unit_price_w_tax[line.id] = unit_price

        result = {
            'amount_w_tax': amount_w_tax,
            'unit_price_w_tax': unit_price_w_tax,
            }
        for key in result.keys():
            if key not in names:
                del result[key]
        return result

    @fields.depends('type', 'unit_price', 'quantity', 'taxes', 'sale',
        '_parent_sale.currency', 'currency', 'product')
    def on_change_with_unit_price_w_tax(self, name=None):
        if not self.sale:
            self.sale = Transaction().context.get('sale')
        return SaleLine.get_price_with_tax([self],
            ['unit_price_w_tax'])['unit_price_w_tax'][self.id]

    @fields.depends('type', 'unit_price', 'quantity', 'taxes', 'sale',
        '_parent_sale.currency', 'currency', 'product')
    def on_change_with_amount_w_tax(self, name=None):
        if not self.sale:
            self.sale = Transaction().context.get('sale')
        return SaleLine.get_price_with_tax([self],
            ['amount_w_tax'])['amount_w_tax'][self.id]

class SalePaymentForm(ModelView, ModelSQL):
    'Sale Payment Form'
    __name__ = 'sale.payment.form'

    payment_amount = fields.Numeric('Payment amount', required=True,
        digits=(16, Eval('currency_digits', 2)),
        depends=['currency_digits'])
    currency_digits = fields.Integer('Currency Digits')
    party = fields.Many2One('party.party', 'Party', readonly=True)


class WizardSalePayment(Wizard):
    'Wizard Sale Payment'
    __name__ = 'sale.payment'
    start = StateView('sale.payment.form',
        'nodux_sale_one.sale_payment_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Pay', 'pay_', 'tryton-ok', default=True),
        ])
    pay_ = StateTransition()
    print_ = StateAction('nodux_sale_one.report_sale_pos')

    @classmethod
    def __setup__(cls):
        super(WizardSalePayment, cls).__setup__()

    def default_start(self, fields):
        pool = Pool()
        Sale = pool.get('sale.sale')
        sale = Sale(Transaction().context['active_id'])

        if sale.days > 0:
            if sale.residual_amount > Decimal(0.0):
                payment_amount = sale.residual_amount
            else:
                payment_amount = Decimal(0.0)
        else:
            if sale.residual_amount > Decimal(0.0):
                payment_amount = sale.residual_amount
            else:
                payment_amount = sale.total_amount
        return {
            'payment_amount': payment_amount,
            'currency_digits': sale.currency_digits,
            'party': sale.party.id,
            }

    def transition_pay_(self):
        pool = Pool()
        Date = pool.get('ir.date')
        Sale = pool.get('sale.sale')
        User = pool.get('res.user')
        Payment = pool.get('sale.payments')
        user, = User.search([('id', '=', 1)])
        limit = user.limit
        form = self.start
        sales = Sale.search_count([('state', '=', 'done')])
        if sales == limit and user.unlimited != True:
            self.raise_user_error(u'Ha excedido el límite de Ventas, contacte con el Administrador de NODUX')
        active_id = Transaction().context.get('active_id', False)
        sale = Sale(active_id)

        if sale.residual_amount > Decimal(0.0):
            if form.payment_amount > sale.residual_amount:
                self.raise_user_error('No puede pagar un monto mayor al valor pendiente %s', str(sale.residual_amount ))

        if form.payment_amount > sale.total_amount:
            self.raise_user_error('No puede pagar un monto mayor al monto total %s', str(sale.total_amount ))

        if sale.party.customer == True:
            pass
        else:
            party = sale.party
            party.customer = True
            party.save()

        for line in sale.lines:
            if (sale.state == 'draft') | (sale.state == 'quotation'):
                if line.product.template.type == "goods":
                    total = line.product.template.total
                    if line.unit == line.product.template.default_uom:
                        if (total <= 0)| (line.quantity > total):
                            origin = str(sale)
                            def in_group():
                                pool = Pool()
                                ModelData = pool.get('ir.model.data')
                                User = pool.get('res.user')
                                Group = pool.get('res.group')
                                Module = pool.get('ir.module')
                                group = Group(ModelData.get_id('nodux_sale_one',
                                                'group_stock_force'))
                                transaction = Transaction()
                                user_id = transaction.user
                                if user_id == 0:
                                    user_id = transaction.context.get('user', user_id)
                                if user_id == 0:
                                    return True
                                user = User(user_id)
                                return origin and group in user.groups
                            if not in_group():
                                self.raise_user_error('No tiene Stock del Producto %s', line.product.name)
                            else:
                                self.raise_user_warning('no_stock_%s' % line.id,
                                       'No hay stock suficiente del producto: "%s"'
                                    'para realizar la venta.', (line.product.name))

                            template = line.product.template
                            if total == None:
                                template.total = Decimal(line.quantity) * Decimal(-1)
                                template.save()
                            else:
                                template.total = Decimal(total) - Decimal(line.quantity)
                                template.save()
                        else:
                            template = line.product.template
                            template.total = Decimal(total) - Decimal(line.quantity)
                            template.save()
                    else:
                        if (total <= 0)| ((line.quantity * line.unit.factor) > total):
                            origin = str(sale)
                            def in_group():
                                pool = Pool()
                                ModelData = pool.get('ir.model.data')
                                User = pool.get('res.user')
                                Group = pool.get('res.group')
                                Module = pool.get('ir.module')
                                group = Group(ModelData.get_id('nodux_sale_one',
                                                'group_stock_force'))
                                transaction = Transaction()
                                user_id = transaction.user
                                if user_id == 0:
                                    user_id = transaction.context.get('user', user_id)
                                if user_id == 0:
                                    return True
                                user = User(user_id)
                                return origin and group in user.groups
                            if not in_group():
                                self.raise_user_error('No tiene Stock del Producto %s', line.product.name)
                            else:
                                self.raise_user_warning('no_stock_%s' % line.id,
                                       'No hay stock suficiente del producto: "%s"'
                                    'para realizar la venta.', (line.product.name))

                            template = line.product.template
                            if total == None:
                                template.total = Decimal(str(round(Decimal(Decimal(line.quantity * line.unit.factor) * Decimal(-1)),8)))
                                template.save()
                            else:
                                template.total = Decimal(str(round(Decimal(total - Decimal(line.quantity * line.unit.factor)),8)))
                                template.save()
                        else:
                            template = line.product.template
                            template.total = Decimal(str(round(Decimal(total - Decimal(line.quantity * line.unit.factor)),8)))
                            template.save()

        Company = pool.get('company.company')
        company = Company(Transaction().context.get('company'))
        user_transaction = User(Transaction().user)

        if sale.sale_note == True:
            if not sale.reference:
                if user_transaction.tpv:
                    tpv = user_transaction.tpv
                else:
                    self.raise_user_error('El usuario no tiene configurado punto de Emision')
                reference = tpv.sequence_sale_note
                sucursal = company.sucursal
                emision = tpv.emision
                tpv.sequence_sale_note = tpv.sequence_sale_note + 1
                tpv.save()
                if len(str(reference)) == 1:
                    reference_end = '00000000' + str(reference)
                elif len(str(reference)) == 2:
                    reference_end = '0000000' + str(reference)
                elif len(str(reference)) == 3:
                    reference_end = '000000' + str(reference)
                elif len(str(reference)) == 4:
                    reference_end = '00000' + str(reference)
                elif len(str(reference)) == 5:
                    reference_end = '0000' + str(reference)
                elif len(str(reference)) == 6:
                    reference_end = '000' + str(reference)
                elif len(str(reference)) == 7:
                    reference_end = '00' + str(reference)
                elif len(str(reference)) == 8:
                    reference_end = '0' + str(reference)
                sale.reference = str(sucursal)+'-'+str(emision)+'-'+reference_end

        else:
            if not sale.reference:
                if user_transaction.tpv:
                    tpv = user_transaction.tpv
                else:
                    self.raise_user_error('El usuario no tiene configurado punto de Emision')
                reference = tpv.sequence_sale
                sucursal = company.sucursal
                emision = tpv.emision
                tpv.sequence_sale = tpv.sequence_sale + 1
                tpv.save()
                if len(str(reference)) == 1:
                    reference_end = '00000000' + str(reference)
                elif len(str(reference)) == 2:
                    reference_end = '0000000' + str(reference)
                elif len(str(reference)) == 3:
                    reference_end = '000000' + str(reference)
                elif len(str(reference)) == 4:
                    reference_end = '00000' + str(reference)
                elif len(str(reference)) == 5:
                    reference_end = '0000' + str(reference)
                elif len(str(reference)) == 6:
                    reference_end = '000' + str(reference)
                elif len(str(reference)) == 7:
                    reference_end = '00' + str(reference)
                elif len(str(reference)) == 8:
                    reference_end = '0' + str(reference)
                sale.reference = str(sucursal)+'-'+str(emision)+'-'+reference_end

        form = self.start

        if sale.paid_amount > Decimal(0.0):
            sale.paid_amount = sale.paid_amount + form.payment_amount
        else:
            sale.paid_amount = form.payment_amount

        sale.residual_amount = sale.total_amount - sale.paid_amount
        sale.description = sale.reference
        if sale.residual_amount == Decimal(0.0):
            sale.state = 'done'
        else:
            sale.state = 'confirmed'
        sale.save()

        payment = Payment()
        payment.sale = sale
        payment.amount = form.payment_amount
        payment.date = Date.today()
        payment.save()

        if sale.sale_note == True:
            return 'end'
        else:
            if sale.state == 'done':
                if len (sale.payments) == 1:
                    return 'print_'
                    return'end'
                else:
                    return 'end'
            elif len (sale.payments) == 1:
                return 'print_'
                return'end'
            else:
                return 'end'

    def transition_print_(self):
        return 'end'

    def do_print_(self, action):
        data = {}
        data['id'] = Transaction().context['active_ids'].pop()
        data['ids'] = [data['id']]
        return action, data

class SaleReportPos(Report):
    __name__ = 'sale.sale_pos'

    @classmethod
    def __setup__(cls):
        super(SaleReportPos, cls).__setup__()

    @classmethod
    def get_context(cls, records, data):
        pool = Pool()
        User = pool.get('res.user')
        Sale = pool.get('sale.sale')
        sale = records[0]
        if sale.total_amount:
            d = str(sale.total_amount).split('.')
            decimales = d[1]
            decimales = decimales[0:2]
        else:
            decimales='0.0'

        user = User(Transaction().user)
        report_context = super(SaleReportPos, cls).get_context(records, data)
        report_context['user'] = user
        report_context['company'] = user.company
        report_context['subtotal_0'] = cls._get_subtotal_0(Sale, sale)
        report_context['subtotal_12'] = cls._get_subtotal_12(Sale, sale)
        report_context['subtotal_14'] = cls._get_subtotal_14(Sale, sale)
        report_context['amount2words']=cls._get_amount_to_pay_words(Sale, sale)
        report_context['decimales'] = decimales
        if user.company.timezone:
            timezone = pytz.timezone(user.company.timezone)
            dt = datetime.now()
            hora = datetime.astimezone(dt.replace(tzinfo=pytz.utc), timezone)
        else:
            sale.raise_user_error('Configure la zona Horaria de su empresa')

        report_context['fecha'] = sale.sale_date.strftime('%d/%m/%Y')
        report_context['hora'] = hora.strftime('%H:%M:%S')

        return report_context


    @classmethod
    def _get_amount_to_pay_words(cls, Sale, sale):
        amount_to_pay_words = Decimal(0.0)
        if sale.total_amount and conversor:
            amount_to_pay_words = sale.get_amount2words(sale.total_amount)
        return amount_to_pay_words

    @classmethod
    def _get_subtotal_14(cls, Sale, sale):
        subtotal14 = Decimal(0.00)
        pool = Pool()

        for line in sale.lines:

            if line.product.taxes_category == True:
                impuesto = line.product.category.taxes
            else:
                impuesto = line.product.taxes

            if impuesto == 'iva14':
                subtotal14= subtotal14 + (line.amount)

        return subtotal14

    @classmethod
    def _get_subtotal_12(cls, Sale, sale):
        subtotal12 = Decimal(0.00)

        for line in sale.lines:

            if line.product.taxes_category == True:
                impuesto = line.product.category.taxes
            else:
                impuesto = line.product.taxes

            if impuesto == 'iva12':
                subtotal12= subtotal12 + (line.amount)

        return subtotal12

    @classmethod
    def _get_subtotal_0(cls, Sale, sale):
        subtotal0 = Decimal(0.00)

        for line in sale.lines:

            if line.product.taxes_category == True:
                impuesto = line.product.category.taxes
            else:
                impuesto = line.product.taxes

            if impuesto == 'iva0' or impuesto == 'no_iva':
                subtotal0= subtotal0 + (line.amount)

        return subtotal0

class PrintReportSalesStart(ModelView):
    'Print Report Sales Start'
    __name__ = 'nodux_sale_one.print_report_sale.start'

    company = fields.Many2One('company.company', 'Company', required=True)
    date = fields.Date("Sale Date", required= True)
    date_end = fields.Date("Sale Date End", required= True)

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    @staticmethod
    def default_date():
        date = Pool().get('ir.date')
        return date.today()

    @staticmethod
    def default_date_end():
        date = Pool().get('ir.date')
        return date.today()

class PrintReportSales(Wizard):
    'Print Report Sales'
    __name__ = 'nodux_sale_one.print_report_sale'
    start = StateView('nodux_sale_one.print_report_sale.start',
        'nodux_sale_one.print_sale_report_start_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Print', 'print_', 'tryton-print', default=True),
            ])
    print_ = StateAction('nodux_sale_one.report_sales')

    def do_print_(self, action):
        data = {
            'company': self.start.company.id,
            'date' : self.start.date,
            'date_end' : self.start.date_end,
            }
        return action, data

    def transition_print_(self):
        return 'end'

class ReportSales(Report):
    __name__ = 'nodux_sale_one.report_sales'

    @classmethod
    def __setup__(cls):
        super(ReportSales, cls).__setup__()

    @classmethod
    def get_context(cls, records, data):
        pool = Pool()
        User = pool.get('res.user')
        user = User(Transaction().user)
        Date = pool.get('ir.date')
        Company = pool.get('company.company')
        Sale = pool.get('sale.sale')
        fecha = data['date']
        fecha_fin = data['date_end']
        total_ventas =  Decimal(0.0)
        total_iva =  Decimal(0.0)
        subtotal_total =  Decimal(0.0)
        subtotal14 = Decimal(0.0)
        subtotal0 = Decimal(0.0)
        subtotal12 = Decimal(0.0)
        totalv = Decimal(0.0)
        ivav = Decimal(0.0)
        totalnv = Decimal(0.0)
        ivanv = Decimal(0.0)
        subtotal14nv = Decimal(0.0)
        subtotal0nv = Decimal(0.0)
        subtotal12nv = Decimal(0.0)
        total_recibido = Decimal(0.0)
        total_por_cobrar = Decimal(0.0)
        ventas_credito = Decimal(0.0)

        company = Company(data['company'])
        sales = Sale.search([('sale_date', '>=', fecha), ('sale_date', '<=', fecha_fin), ('state','in', ['done','confirmed'])])

        if sales:
            for s in sales:
                if s.total_amount > Decimal(0.0):
                    if s.days > 0 and s.sale_note == False:
                        ventas_credito = s.total_amount
                    if s.sale_note == True:
                        totalnv += s.total_amount
                        ivanv += s.tax_amount
                    else:
                        totalv += s.total_amount
                        ivav += s.tax_amount

                    total_ventas += s.total_amount
                    total_iva += s.tax_amount
                    subtotal_total += s.untaxed_amount
                    total_recibido += s.paid_amount
                    if s.residual_amount != None:
                        total_por_cobrar += s.residual_amount

                    for line in s.lines:
                        if line.product.taxes_category == True:
                            impuesto = line.product.category.taxes
                        else:
                            impuesto = line.product.taxes

                        if impuesto == 'iva0' or impuesto == 'no_iva':
                            if s.sale_note == True:
                                subtotal0nv = subtotal0nv + line.amount
                            else:
                                subtotal0= subtotal0 + (line.amount)
                        if impuesto == 'iva14':
                            if s.sale_note == True:
                                subtotal14nv = subtotal14nv + line.amount
                            else:
                                subtotal14= subtotal14 + (line.amount)
                        if impuesto == 'iva12':
                            if s.sale_note == True:
                                subtotal12nv = subtotal12nv + line.amount
                            else:
                                subtotal12= subtotal12 + (line.amount)

        if company.timezone:
            timezone = pytz.timezone(company.timezone)
            dt = datetime.now()
            hora = datetime.astimezone(dt.replace(tzinfo=pytz.utc), timezone)
        else:
            company.raise_user_error('Configure la zona Horaria de la empresa')

        report_context = super(ReportSales, cls).get_context(records, data)

        report_context['company'] = company
        report_context['fecha'] = fecha.strftime('%d/%m/%Y')
        report_context['fecha_fin'] = fecha_fin.strftime('%d/%m/%Y')
        report_context['hora'] = hora.strftime('%H:%M:%S')
        report_context['fecha_im'] = hora.strftime('%d/%m/%Y')
        report_context['total_ventas'] = total_ventas
        report_context['sales'] = sales
        report_context['total_iva'] = total_iva
        report_context['subtotal_total'] = subtotal_total
        report_context['subtotal14'] = subtotal14
        report_context['subtotal0'] = subtotal0
        report_context['total_ventas_creditos'] = ventas_credito
        report_context['totalv'] = totalv
        report_context['subtotal14nv'] = subtotal14nv
        report_context['subtotal0nv'] = subtotal0nv
        report_context['totalnv'] = totalnv
        report_context['ivav'] = ivav
        report_context['ivanv'] = ivanv
        return report_context


class PrintReportPaymentsStart(ModelView):
    'Print Report Payment Start'
    __name__ = 'nodux_sale_one.print_report_payment.start'

    company = fields.Many2One('company.company', 'Company', required=True)
    date = fields.Date("Payment Date", required= True)
    date_end = fields.Date("Payment Date End", required= True)

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    @staticmethod
    def default_date():
        date = Pool().get('ir.date')
        return date.today()

    @staticmethod
    def default_date_end():
        date = Pool().get('ir.date')
        return date.today()

class PrintReportPayments(Wizard):
    'Print Report Payments'
    __name__ = 'nodux_sale_one.print_report_payment'
    start = StateView('nodux_sale_one.print_report_payment.start',
        'nodux_sale_one.print_payment_report_start_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Print', 'print_', 'tryton-print', default=True),
            ])
    print_ = StateAction('nodux_sale_one.report_payments')

    def do_print_(self, action):
        data = {
            'company': self.start.company.id,
            'date' : self.start.date,
            'date_end' : self.start.date_end,
            }
        return action, data

    def transition_print_(self):
        return 'end'

class ReportPayments(Report):
    __name__ = 'nodux_sale_one.report_payments'

    @classmethod
    def get_context(cls, records, data):
        pool = Pool()
        User = pool.get('res.user')
        user = User(Transaction().user)
        Date = pool.get('ir.date')
        Company = pool.get('company.company')
        Sale = pool.get('sale.sale')
        Payments = pool.get('sale.payments')
        fecha = data['date']
        fecha_fin = data['date_end']
        total_pagos = Decimal(0.0)
        company = Company(data['company'])
        payments = Payments.search([('date', '>=', fecha), ('date', '<=', fecha_fin), ('amount', '>', 0)])

        if payments:
            for p in payments:
                if p.sale.days > 0:
                    if p.amount > Decimal(0.0):
                        total_pagos += p.amount

        if company.timezone:
            timezone = pytz.timezone(company.timezone)
            dt = datetime.now()
            hora = datetime.astimezone(dt.replace(tzinfo=pytz.utc), timezone)
        else:
            company.raise_user_error('Configure la zona Horaria de la empresa')

        report_context = super(ReportPayments, cls).get_context(records, data)
        report_context['company'] = company
        report_context['fecha'] = fecha.strftime('%d/%m/%Y')
        report_context['fecha_fin'] = fecha_fin.strftime('%d/%m/%Y')
        report_context['hora'] = hora.strftime('%H:%M:%S')
        report_context['fecha_im'] = hora.strftime('%d/%m/%Y')
        report_context['payments'] = payments
        report_context['total_pagos'] = total_pagos
        return report_context

class SalePaymentReport(Report):
    __name__ = 'sale.sale_payment_report'

    @classmethod
    def __setup__(cls):
        super(SalePaymentReport, cls).__setup__()

    @classmethod
    def get_context(cls, records, data):
        pool = Pool()
        User = pool.get('res.user')
        Sale = pool.get('sale.sale')
        sale = records[0]

        user = User(Transaction().user)

        report_context = super(SalePaymentReport, cls).get_context(records, data)

        report_context['user'] = user
        report_context['company'] = user.company

        return report_context
