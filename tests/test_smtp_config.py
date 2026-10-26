import importlib.util
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from flask import Flask


# Import the isolated loader without starting the app or connecting to its database.
spec = importlib.util.spec_from_file_location(
    '_smtp_config_tests', Path(__file__).resolve().parents[1] / 'app' / 'smtp_config.py')
smtp_config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smtp_config)


class SmtpConfigTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'smtp.env'
        self.app = Flask('smtp_config_tests')
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def write(self, value):
        self.path.write_text(value, encoding='utf-8-sig')

    def test_missing_file_does_not_change_config(self):
        before = dict(self.app.config)
        smtp_config.configurar_smtp_desde_archivo(self.app, self.path)
        self.assertEqual(dict(self.app.config), before)

    def test_loads_mail_settings_without_exporting_environment(self):
        self.write('SMTP_HOST=smtp.gmail.com\nSMTP_PASSWORD=fake-test-secret\n'
                   'SMTP_USE_TLS=true\nSOPORTE_TERRENO_DESTINATARIOS=soporte@example.test\n')
        smtp_config.configurar_smtp_desde_archivo(self.app, self.path)
        self.assertEqual(self.app.config['SMTP_HOST'], 'smtp.gmail.com')
        self.assertEqual(self.app.config['SMTP_PASSWORD'], 'fake-test-secret')
        self.assertEqual(self.app.config['SMTP_USE_TLS'], 'true')
        self.assertEqual(self.app.config['SOPORTE_TERRENO_DESTINATARIOS'], 'soporte@example.test')
        self.assertNotIn('SMTP_PASSWORD', os.environ)

    def test_environment_and_explicit_app_config_take_priority(self):
        self.write('SMTP_HOST=file.example.test\nSMTP_PASSWORD=file-secret\n')
        self.app.config['SMTP_HOST'] = 'app.example.test'
        os.environ['SMTP_PASSWORD'] = 'environment-secret'
        smtp_config.configurar_smtp_desde_archivo(self.app, self.path)
        self.assertEqual(self.app.config['SMTP_HOST'], 'app.example.test')
        self.assertNotIn('SMTP_PASSWORD', self.app.config)
        self.assertEqual(os.environ['SMTP_PASSWORD'], 'environment-secret')

    def test_ignores_unrelated_settings_and_does_not_expand_secrets(self):
        self.write('DATABASE_URL=not-a-real-database\nSECRET_KEY=must-not-load\n'
                   'SMTP_PASSWORD=fake-${SECRET_KEY}\nSMTP_HOST\n')
        smtp_config.configurar_smtp_desde_archivo(self.app, self.path)
        self.assertNotIn('DATABASE_URL', self.app.config)
        self.assertIsNone(self.app.config['SECRET_KEY'])
        self.assertEqual(self.app.config['SMTP_PASSWORD'], 'fake-${SECRET_KEY}')
        self.assertNotIn('SMTP_HOST', self.app.config)

    def test_blank_password_remains_unconfigured(self):
        self.write('SMTP_PASSWORD=\n')
        smtp_config.configurar_smtp_desde_archivo(self.app, self.path)
        self.assertEqual(self.app.config['SMTP_PASSWORD'], '')


if __name__ == '__main__':
    unittest.main()
