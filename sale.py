#! -*- coding: utf8 -*-

# This file is part of sale_pos module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
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
'SaleReportPos', 'PrintReportSalesStart', 'PrintReportSales', 'ReportSales']

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
    reference = fields.Char('Reference', readonly=True, select=True)
    description = fields.Char('Description',
        states={
            'readonly': Eval('state') != 'draft',
            },
        depends=['state'])
    state = fields.Selection([
        ('draft', 'Draft'),
        ('quotation', 'Quotation'),
        ('confirmed', 'Confirmed'),
        ('done', 'Done'),
        ('anulled', 'Anulled'),
    ], 'State', readonly=True, required=True)
    sale_date = fields.Date('Sale Date',
        states={
            'readonly': ~Eval('state').in_(['draft', 'quotation']),
            'required': ~Eval('state').in_(['draft', 'quotation', 'cancel']),
            },
        depends=['state'])
    party = fields.Many2One('party.party', 'Party', required=True, select=True,
        states={
            'readonly': ((Eval('state') != 'draft')),
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
            'readonly': Eval('state') != 'draft',
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

    @classmethod
    def __register__(cls, module_name):
        cursor = Transaction().cursor
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
                ('done', 'anull'),
                ))

        cls._buttons.update({
                'wizard_sale_payment': {
                    'invisible': Eval('state') == 'done',
                    'readonly': Not(Bool(Eval('lines'))),
                    },
                'quote': {
                    'invisible': Eval('state') != 'draft',
                    'readonly': ~Eval('lines', []),
                    },
                'anull': {
                    'invisible': Eval('state') == 'draft',
                    'readonly': Not(Bool(Eval('lines'))),
                    },
                })
        cls._states_cached = ['confirmed', 'processing', 'done', 'cancel']

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

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
        res = {
            'untaxed_amount': Decimal('0.0'),
            'tax_amount': Decimal('0.0'),
            'total_amount': Decimal('0.0'),
            }
        if self.lines:
            res['untaxed_amount'] = reduce(lambda x, y: x + y,
                [(getattr(l, 'amount', None) or Decimal(0))
                    for l in self.lines if l.type == 'line'], Decimal(0)
                )
            res['total_amount'] = reduce(lambda x, y: x + y,
                [(getattr(l, 'amount_w_tax', None) or Decimal(0))
                    for l in self.lines if l.type == 'line'], Decimal(0)
                )
        if self.currency:
            res['untaxed_amount'] = self.currency.round(res['untaxed_amount'])
            res['total_amount'] = self.currency.round(res['total_amount'])
        res['tax_amount'] = res['total_amount'] - res['untaxed_amount']
        if self.currency:
            res['tax_amount'] = self.currency.round(res['tax_amount'])
        return res


    def get_tax_amount(self):
        tax = _ZERO
        taxes = _ZERO

        for line in self.lines:
            if line.type != 'line':
                continue
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
            tax = line.unit_price * value
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
            for line in sale.lines:
                product = line.product.template
                product.total = line.product.template.total + line.quantity
                product.save()
        cls.write([s for s in sales], {
                'state': 'anulled',
                })


    @classmethod
    @ModelView.button_action('nodux_sale_one.wizard_sale_payment')
    def wizard_sale_payment(cls, sales):
        pass

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

    @classmethod
    def __setup__(cls):
        super(SaleLine, cls).__setup__()

        # Allow edit product, quantity and unit in lines without parent sale
        for fname in ('product', 'quantity', 'unit'):
            field = getattr(cls, fname)
            if field.states.get('readonly'):
                del field.states['readonly']

    @staticmethod
    def default_type():
        return 'line'

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
        if self.unit:
            context['uom'] = self.unit.id
        else:
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
            return {}
        res = {}

        party = None
        party_context = {}
        if self.sale and self.sale.party:
            party = self.sale.party
            if party.lang:
                party_context['language'] = party.lang.code

        category = self.product.default_uom.category
        if not self.unit or self.unit not in category.uoms:
            res['unit'] = self.product.default_uom.id
            self.unit = self.product.default_uom
            res['unit.rec_name'] = self.product.default_uom.rec_name
            res['unit_digits'] = self.product.default_uom.digits

        with Transaction().set_context(self._get_context_sale_price()):
            res['unit_price'] = Product.get_sale_price([self.product],
                    self.quantity or 0)[self.product.id]
            if res['unit_price']:
                res['unit_price'] = res['unit_price'].quantize(
                    Decimal(1) / 10 ** self.__class__.unit_price.digits[1])
        if not self.description:
            with Transaction().set_context(party_context):
                res['description'] = Product(self.product.id).rec_name

        self.unit_price = res['unit_price']
        self.type = 'line'
        res['amount'] = self.on_change_with_amount()
        res['description'] =  Product(self.product.id).name
        return res


    @fields.depends('product', 'quantity', 'unit',
        '_parent_sale.currency', '_parent_sale.party',
        '_parent_sale.sale_date')
    def on_change_quantity(self):
        Product = Pool().get('product.product')

        if not self.product:
            return {}
        res = {}

        with Transaction().set_context(
                self._get_context_sale_price()):
            res['unit_price'] = Product.get_sale_price([self.product],
                self.quantity or 0)[self.product.id]
            if res['unit_price']:
                res['unit_price'] = res['unit_price'].quantize(
                    Decimal(1) / 10 ** self.__class__.unit_price.digits[1])
        return res

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

        def compute_amount_with_tax(line):

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

            tax_amount = line.unit_price * value
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

    @classmethod
    def __setup__(cls):
        super(WizardSalePayment, cls).__setup__()

    def default_start(self, fields):
        pool = Pool()
        Sale = pool.get('sale.sale')
        sale = Sale(Transaction().context['active_id'])

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
        user = User(Transaction().user)
        limit = user.limit

        sales = Sale.search_count([('state', '=', 'done')])
        if sales > limit and user.unlimited != True:
            self.raise_user_error(u'Ha excedido el límite de Ventas, contacte con el Administrador de NODUX')
        active_id = Transaction().context.get('active_id', False)
        sale = Sale(active_id)

        for line in sale.lines:
            total = line.product.template.total
            if (total <= 0)| (line.quantity > total):
                self.raise_user_error('No tiene Stock del Producto %s', line.product.name)
            else:
                template = line.product.template
                template.total = total - line.quantity
                template.save()
        Company = pool.get('company.company')
        company = Company(Transaction().context.get('company'))

        if not sale.reference:
            reference = company.sequence_sale
            company.sequence_sale = company.sequence_sale + 1
            company.save()
            sale.reference = str(reference)

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

        return 'end'


class SaleReportPos(Report):
    __name__ = 'sale.sale_pos'

    @classmethod
    def parse(cls, report, records, data, localcontext):
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
        localcontext['user'] = user
        localcontext['company'] = user.company
        localcontext['subtotal_0'] = cls._get_subtotal_0(Sale, sale)
        localcontext['subtotal_12'] = cls._get_subtotal_12(Sale, sale)
        localcontext['subtotal_14'] = cls._get_subtotal_14(Sale, sale)
        localcontext['amount2words']=cls._get_amount_to_pay_words(Sale, sale)
        localcontext['decimales'] = decimales
        return super(SaleReportPos, cls).parse(report, records, data,
                localcontext=localcontext)

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

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    @staticmethod
    def default_date():
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
            }
        return action, data

    def transition_print_(self):
        return 'end'

class ReportSales(Report):
    __name__ = 'nodux_sale_one.report_sales'

    @classmethod
    def parse(cls, report, objects, data, localcontext):
        pool = Pool()
        User = pool.get('res.user')
        user = User(Transaction().user)
        Date = pool.get('ir.date')
        Company = pool.get('company.company')
        Sale = pool.get('sale.sale')
        fecha = data['date']
        total_ventas =  Decimal(0.0)
        total_iva =  Decimal(0.0)
        subtotal_total =  Decimal(0.0)
        subtotal14 = Decimal(0.0)
        subtotal0 = Decimal(0.0)
        subtotal12 = Decimal(0.0)
        total_recibido = Decimal(0.0)
        total_por_cobrar = Decimal(0.0)
        company = Company(data['company'])
        sales = Sale.search([('sale_date', '=', fecha), ('state','!=', 'draft')])

        if sales:
            for s in sales:
                if s.total_amount > Decimal(0.0):
                    total_ventas += s.total_amount
                    total_iva += s.tax_amount
                    subtotal_total += s.untaxed_amount
                    total_recibido += s.paid_amount
                    total_por_cobrar += s.residual_amount

                    for line in s.lines:
                        if line.product.taxes_category == True:
                            impuesto = line.product.category.taxes
                        else:
                            impuesto = line.product.taxes

                        if impuesto == 'iva0' or impuesto == 'no_iva':
                            subtotal0= subtotal0 + (line.amount)
                        if impuesto == 'iva14':
                            subtotal14= subtotal14 + (line.amount)
                        if impuesto == 'iva12':
                            subtotal12= subtotal12 + (line.amount)

        if company.timezone:
            timezone = pytz.timezone(company.timezone)
            dt = datetime.now()
            hora = datetime.astimezone(dt.replace(tzinfo=pytz.utc), timezone)
        else:
            company.raise_user_error('Configure la zona Horaria de la empresa')

        localcontext['company'] = company
        localcontext['fecha'] = fecha.strftime('%d/%m/%Y')
        localcontext['hora'] = hora.strftime('%H:%M:%S')
        localcontext['fecha_im'] = hora.strftime('%d/%m/%Y')
        localcontext['total_ventas'] = total_ventas
        localcontext['sales'] = sales
        localcontext['total_iva'] = total_iva
        localcontext['subtotal_total'] = subtotal_total
        localcontext['subtotal14'] = subtotal14
        localcontext['subtotal0'] = subtotal0


        return super(ReportSales, cls).parse(report, objects, data, localcontext)
