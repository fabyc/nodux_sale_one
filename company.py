#! -*- coding: utf8 -*-

import string
from trytond.model import ModelView, ModelSQL, fields, Workflow
from trytond.pyson import Eval
from trytond.pool import Pool, PoolMeta
import hashlib
import base64

__all__ = ['Company']
__metaclass__ = PoolMeta

class Company():
    'Company'
    __name__ = 'company.company'

    sequence_sale = fields.Integer('Sequence Sale')
    sucursal = fields.Char('Sucursal')
    emision = fields.Char('Emission Point')

    @classmethod
    def __setup__(cls):
        super(Company, cls).__setup__()

    @staticmethod
    def default_sequence_sale():
        return 1

    @staticmethod
    def default_sucursal():
        return '001'

    @staticmethod
    def default_emision():
        return '001'
