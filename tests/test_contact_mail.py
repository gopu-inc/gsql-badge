import os
import unittest
from unittest.mock import patch

from utils.contact_mail import (
    ContactDeliveryError,
    send_contact_email,
    validate_contact_message,
)


class ContactMailTests(unittest.TestCase):
    def test_validate_contact_message_trims_fields(self):
        result = validate_contact_message(
            '  Ada  ',
            ' ada@example.com ',
            '  Question  ',
            '  Please help me with this package.  ',
        )

        self.assertEqual(result, (
            'Ada',
            'ada@example.com',
            'Question',
            'Please help me with this package.',
        ))

    def test_validate_contact_message_rejects_header_injection(self):
        with self.assertRaises(ValueError):
            validate_contact_message(
                'Ada', 'ada@example.com', 'Question\r\nBcc: other@example.com',
                'Please help me with this package.',
            )

    @patch.dict(os.environ, {}, clear=True)
    def test_delivery_requires_smtp_configuration(self):
        with self.assertRaisesRegex(ContactDeliveryError, 'not configured'):
            send_contact_email(
                'Ada',
                'ada@example.com',
                'Question',
                'Please help me with this package.',
                'info@iddet.space',
            )

    def test_delivery_rejects_invalid_smtp_destination_and_port(self):
        config = {'SMTP_HOST': 'smtp.example.test', 'SMTP_PORT': '70000'}
        with self.assertRaisesRegex(ContactDeliveryError, 'CONTACT_EMAIL'):
            send_contact_email(
                'Ada', 'ada@example.com', 'Question',
                'Please help me with this package.', 'not-an-email', environ=config,
            )
        with self.assertRaisesRegex(ContactDeliveryError, 'SMTP_PORT'):
            send_contact_email(
                'Ada', 'ada@example.com', 'Question',
                'Please help me with this package.', 'info@iddet.space', environ=config,
            )

    @patch.dict(os.environ, {
        'SMTP_HOST': 'smtp.example.test',
        'SMTP_PORT': '587',
        'SMTP_SECURITY': 'starttls',
        'SMTP_USERNAME': 'mailer@example.test',
        'SMTP_PASSWORD': 'test-password',
    }, clear=True)
    @patch('utils.contact_mail.smtplib.SMTP')
    def test_delivery_uses_fixed_recipient_and_reply_to(self, smtp_factory):
        server = smtp_factory.return_value.__enter__.return_value

        send_contact_email(
            'Ada',
            'ada@example.com',
            'Question',
            'Please help me with this package.',
            'info@iddet.space',
        )

        server.starttls.assert_called_once()
        sent_email = server.send_message.call_args.args[0]
        self.assertEqual(sent_email['To'], 'info@iddet.space')
        self.assertEqual(sent_email['Reply-To'], 'ada@example.com')


if __name__ == '__main__':
    unittest.main()
