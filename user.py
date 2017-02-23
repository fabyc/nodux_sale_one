#! -*- coding: utf8 -*-

#This file is part of Tryton.  The COPYRIGHT file at the top level of
#this repository contains the full copyright notices and license terms.

from trytond.pool import *
from trytond.model import fields
from trytond.pyson import Eval
from trytond.pyson import Id
import base64
__all__ = ['User']
__metaclass__ = PoolMeta


class User:
    __name__ = 'res.user'

    limit = fields.Integer('Sales Limit')
    unlimited = fields.Boolean('Unlimited Sales')

    @classmethod
    def __setup__(cls):
        super(User, cls).__setup__()

    @staticmethod
    def default_limit():
        return 10

    @staticmethod
    def default_unlimited():
        return False

    @classmethod
    def view_attributes(cls):
        return super(User, cls).view_attributes() + [
            ('//page[@id="sales"]', 'states', {
                    'invisible': ~Eval('id').in_([1]),
                    })]
