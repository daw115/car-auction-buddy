"""
Gmail client dla pobierania i wysyłania emaili.
Obsługuje zarówno OAuth2 jak i App Password (2FA).
"""
import os
import imaplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import smtplib
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()


@dataclass
class EmailMessage:
    """Reprezentacja emaila."""
    id: str
    subject: str
    sender: str
    body: str
    date: datetime
    is_read: bool = False


class GmailClient:
    """Klient Gmail z obsługą App Password."""

    def __init__(self):
        self.email_address = os.getenv("GMAIL_ADDRESS")
        self.app_password = os.getenv("GMAIL_APP_PASSWORD")
        self.imap_server = "imap.gmail.com"
        self.smtp_server = "smtp.gmail.com"
        self.smtp_port = 587

        if not self.email_address or not self.app_password:
            raise ValueError("GMAIL_ADDRESS i GMAIL_APP_PASSWORD muszą być ustawione w .env")

    def connect_imap(self) -> imaplib.IMAP4_SSL:
        """Łączy się z serwerem IMAP."""
        mail = imaplib.IMAP4_SSL(self.imap_server)
        mail.login(self.email_address, self.app_password)
        return mail

    def fetch_unread_emails(self, folder: str = "INBOX", limit: int = 10) -> List[EmailMessage]:
        """
        Pobiera nieprzeczytane emaile z określonego folderu.

        Args:
            folder: Nazwa folderu (domyślnie INBOX)
            limit: Maksymalna liczba emaili do pobrania

        Returns:
            Lista obiektów EmailMessage
        """
        return self._fetch_emails(folder=folder, limit=limit, search_criteria='UNSEEN')

    def fetch_recent_emails(self, folder: str = "INBOX", limit: int = 10) -> List[EmailMessage]:
        """Pobiera ostatnie emaile niezależnie od statusu przeczytania."""
        return self._fetch_emails(folder=folder, limit=limit, search_criteria='ALL')

    def _fetch_emails(self, folder: str, limit: int, search_criteria: str) -> List[EmailMessage]:
        mail = self.connect_imap()

        try:
            mail.select(folder)

            status, messages = mail.search(None, search_criteria)
            if status != "OK":
                return []

            email_ids = messages[0].split()
            email_ids = email_ids[-limit:]

            emails = []
            for email_id in email_ids:
                # BODY.PEEK[] nie oznacza wiadomości jako przeczytanej
                status, msg_data = mail.fetch(email_id, '(BODY.PEEK[])')
                if status != "OK":
                    continue

                for response_part in msg_data:
                    if not isinstance(response_part, tuple):
                        continue

                    msg = email.message_from_bytes(response_part[1])
                    subject = self._decode_header(msg.get("Subject", ""))
                    sender = self._decode_header(msg.get("From", ""))
                    date_str = msg.get("Date", "")

                    try:
                        date = email.utils.parsedate_to_datetime(date_str)
                    except Exception:
                        date = datetime.now()

                    body = self._get_email_body(msg)

                    emails.append(EmailMessage(
                        id=email_id.decode(),
                        subject=subject,
                        sender=sender,
                        body=body,
                        date=date,
                        is_read=(search_criteria != 'UNSEEN')
                    ))

            return emails
        finally:
            mail.close()
            mail.logout()

    def mark_as_read(self, email_id: str, folder: str = "INBOX"):
        """Oznacza email jako przeczytany."""
        mail = self.connect_imap()

        try:
            mail.select(folder)
            mail.store(email_id.encode(), '+FLAGS', '\\Seen')
        finally:
            mail.close()
            mail.logout()

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        attachments: Optional[List[str]] = None,
        html: bool = False
    ):
        """
        Wysyła email z opcjonalnymi załącznikami.

        Args:
            to: Adres odbiorcy
            subject: Temat emaila
            body: Treść emaila
            attachments: Lista ścieżek do plików do załączenia
            html: Czy treść jest w formacie HTML
        """
        msg = MIMEMultipart()
        msg['From'] = self.email_address
        msg['To'] = to
        msg['Subject'] = subject

        # Dodaj treść
        if html:
            msg.attach(MIMEText(body, 'html'))
        else:
            msg.attach(MIMEText(body, 'plain'))

        # Dodaj załączniki
        if attachments:
            for file_path in attachments:
                self._attach_file(msg, file_path)

        # Wyślij email
        with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
            server.starttls()
            server.login(self.email_address, self.app_password)
            server.send_message(msg)

    def _decode_header(self, header: str) -> str:
        """Dekoduje nagłówek emaila."""
        if not header:
            return ""

        decoded_parts = email.header.decode_header(header)
        result = []

        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                result.append(part.decode(encoding or 'utf-8', errors='ignore'))
            else:
                result.append(part)

        return ''.join(result)

    def _get_email_body(self, msg: email.message.Message) -> str:
        """Wyciąga treść emaila."""
        body = ""

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))

                if content_type == "text/plain" and "attachment" not in content_disposition:
                    try:
                        body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                        break
                    except:
                        pass
        else:
            try:
                body = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
            except:
                body = str(msg.get_payload())

        return body.strip()

    def _attach_file(self, msg: MIMEMultipart, file_path: str):
        """Dodaje załącznik do emaila."""
        with open(file_path, 'rb') as f:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(f.read())

        encoders.encode_base64(part)

        filename = os.path.basename(file_path)
        part.add_header(
            'Content-Disposition',
            f'attachment; filename= {filename}'
        )

        msg.attach(part)
