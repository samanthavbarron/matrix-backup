import unittest
import importlib

class TestImport(unittest.TestCase):

    def test_import(self):
        importlib.import_module('src')