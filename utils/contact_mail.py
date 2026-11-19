import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr


_EMAIL_PATTERN = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


class ContactDeliveryError(RuntimeError):
    pass


def validate_contact_message(name, sender_email, subject, body):
    if not all(isinstance(value, str) for value in (name, sender_email, subject, body)):
        raise ValueError('All contact fields must be text.')

    name = name.strip()
    sender_email = sender_email.strip()
    subject = subject.strip()
    body = body.strip()

    if not name or len(name) > 100 or any(ord(char) < 32 for char in name):
        raise ValueError('Name must be between 1 and 100 characters.')
    if len(sender_email) > 254 or not _EMAIL_PATTERN.fullmatch(sender_email):
        raise ValueError('Enter a valid email address.')
    if not subject or len(subject) > 150 or any(char in subject for char in '\r\n'):
        raise ValueError('Subject must be between 1 and 150 characters.')
    if len(body) < 10 or len(body) > 5000 or '\x00' in body:
        raise ValueError('Message must be between 10 and 5,000 characters.')

    return name, sender_email, subject, body


def send_contact_email(name, sender_email, subject, body, recipient, environ=None):
    name, sender_email, subject, body = validate_contact_message(
        name, sender_email, subject, body
    )
    config = os.environ if environ is None else environ
    host = config.get('SMTP_HOST', '').strip()
    if not host:
        raise ContactDeliveryError('Contact email delivery is not configured.')
    if not isinstance(recipient, str) or not _EMAIL_PATTERN.fullmatch(recipient):
        raise ContactDeliveryError('CONTACT_EMAIL must be a valid email address.')

    try:
        port = int(config.get('SMTP_PORT', '587'))
    except ValueError as error:
        raise ContactDeliveryError('SMTP_PORT must be a valid port number.') from error
    if not 1 <= port <= 65535:
        raise ContactDeliveryError('SMTP_PORT must be between 1 and 65535.')

    username = config.get('SMTP_USERNAME', '').strip()
    password = config.get('SMTP_PASSWORD', '')
    if bool(username) != bool(password):
        raise ContactDeliveryError('SMTP_USERNAME and SMTP_PASSWORD must be set together.')

    security = config.get('SMTP_SECURITY', 'starttls').strip().lower()
    if security not in ('ssl', 'starttls', 'none'):
        raise ContactDeliveryError('SMTP_SECURITY must be ssl, starttls, or none.')

    from_address = config.get('SMTP_FROM_EMAIL', username or recipient).strip()
    if not _EMAIL_PATTERN.fullmatch(from_address):
        raise ContactDeliveryError('SMTP_FROM_EMAIL must be a valid email address.')

    email = EmailMessage()
    email['From'] = formataddr(('Zarch Hub', from_address))
    email['To'] = recipient
    email['Reply-To'] = sender_email
    email['Subject'] = f'[Zarch Hub] {subject}'
    email.set_content(f'From: {name} <{sender_email}>\n\n{body}')

    try:
        if security == 'ssl':
            with smtplib.SMTP_SSL(
                host, port, timeout=15, context=ssl.create_default_context()
            ) as server:
                if username:
                    server.login(username, password)
                server.send_message(email)
        else:
            with smtplib.SMTP(host, port, timeout=15) as server:
                server.ehlo()
                if security == 'starttls':
                    server.starttls(context=ssl.create_default_context())
                    server.ehlo()
                if username:
                    server.login(username, password)
                server.send_message(email)
    except (OSError, smtplib.SMTPException, UnicodeError) as error:
        raise ContactDeliveryError('The contact email could not be delivered.') from error
