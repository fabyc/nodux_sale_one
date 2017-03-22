#! -*- coding: utf8 -*-

#This file is part of Tryton.  The COPYRIGHT file at the top level of
#this repository contains the full copyright notices and license terms.

from trytond.pool import *
from trytond.model import fields
from trytond.pyson import Eval
from trytond.pyson import Id
from trytond.transaction import Transaction
import base64
__all__ = ['User']
__metaclass__ = PoolMeta


class User:
    __name__ = 'res.user'

    limit = fields.Integer('Sales Limit', states={
        'readonly': Eval('unlimited', True)
    })
    unlimited = fields.Boolean('Unlimited Sales')

    tpv = fields.Many2One('sale.sequence', 'TPV')

    @classmethod
    def __setup__(cls):
        super(User, cls).__setup__()

    @staticmethod
    def default_limit():
        return 10

    @staticmethod
    def default_unlimited():
        return False

    @fields.depends('tpv', 'id')
    def on_change_tpv(self):
        origin = str(self.tpv)
        def in_group():
            pool = Pool()
            ModelData = pool.get('ir.model.data')
            User = pool.get('res.user')
            Group = pool.get('res.group')
            Module = pool.get('ir.module')
            group = Group(ModelData.get_id('nodux_sale_one',
                            'group_change_tpv'))
            transaction = Transaction()
            user_id = transaction.user
            if user_id == 0:
                user_id = transaction.context.get('user', user_id)
            if user_id == 0:
                return True
            user = User(user_id)
            return origin and group in user.groups

        if not in_group():
            self.tpv = None
            self.raise_user_error('No puede modificar el punto de Venta')

    @classmethod
    def view_attributes(cls):
        return super(User, cls).view_attributes() + [
            ('//page[@id="sales"]', 'states', {
                    'invisible': ~Eval('id').in_([1]),
                    })]
