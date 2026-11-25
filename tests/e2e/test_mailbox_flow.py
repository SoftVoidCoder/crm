import unittest
import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient

from main import app
from database import get_connection
from tests.test_helpers import create_test_user, delete_test_user
from routers.communications import _parse_exchange_ews_messages


class MailboxFlowE2ETests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.user = create_test_user(role="Директор", name_prefix="Director Test")
        login = self.client.post("/api/login", json={"email": self.user["email"], "password": self.user["password"]})
        self.assertEqual(login.status_code, 200)

    def tearDown(self):
        conn = get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM email_attachments WHERE message_id IN (SELECT id FROM email_messages WHERE sender_email LIKE 'qa-mailbox-%')")
        c.execute("DELETE FROM email_messages WHERE sender_email LIKE 'qa-mailbox-%'")
        c.execute("DELETE FROM email_account_owners WHERE account_id IN (SELECT id FROM email_accounts WHERE address LIKE 'qa-mailbox-%')")
        c.execute("DELETE FROM email_accounts WHERE address LIKE 'qa-mailbox-%'")
        conn.commit()
        conn.close()
        delete_test_user(self.user["email"])

    def test_mailbox_configuration_and_feed_visibility(self):
        account_res = self.client.post(
            "/api/email/accounts",
            json={
                "label": "QA Mailbox",
                "address": "qa-mailbox-e2e@example.com",
                "login": "qa-mailbox-e2e@example.com",
                "password": "mail-pass-1",
                "imap_host": "imap.invalid",
                "imap_port": 993,
                "smtp_host": "smtp.invalid",
                "smtp_port": 465,
                "smtp_login": "qa-mailbox-e2e@example.com",
                "smtp_password": "mail-pass-1",
                "inbox_folder": "INBOX",
                "archive_folder": "Archive",
                "is_default": 0,
                "is_active": 0,
            },
        )
        self.assertEqual(account_res.status_code, 200)
        account_id = account_res.json()["id"]

        conn = get_connection()
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO email_messages (
                account_id, uid, folder, subject, sender, sender_email, body_preview, body_text,
                received_at, is_read, is_archived, is_deleted, created_at, synced_at, delivery_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, ?, ?, ?)
            """,
            (
                account_id,
                "uid-e2e-1",
                "INBOX",
                "Smoke email",
                "QA Sender",
                "qa-mailbox-sender@example.com",
                "preview",
                "full body",
                "11.04.2026 12:00",
                1,
                1,
                "received",
            ),
        )
        conn.commit()
        conn.close()

        app_html = self.client.get("/app")
        self.assertEqual(app_html.status_code, 200)
        self.assertIn("Входящая почта", app_html.text)

        accounts = self.client.get("/api/email/accounts")
        self.assertEqual(accounts.status_code, 200)
        self.assertTrue(any(item["id"] == account_id for item in accounts.json()))

        emails = self.client.get(f"/api/emails?account_id={account_id}&filter_name=all")
        self.assertEqual(emails.status_code, 200)
        self.assertTrue(any(item["subject"] == "Smoke email" for item in emails.json()))

        filtered = self.client.get(f"/api/emails?account_id={account_id}&filter_name=new&query=Smoke")
        self.assertEqual(filtered.status_code, 200)
        self.assertTrue(any(item["subject"] == "Smoke email" for item in filtered.json()))

    def test_mailbox_test_endpoint_and_failed_retry_flow(self):
        account_res = self.client.post(
            "/api/email/accounts",
            json={
                "label": "QA Broken Mailbox",
                "address": "qa-mailbox-broken@example.com",
                "login": "qa-mailbox-broken@example.com",
                "password": "mail-pass-1",
                "imap_host": "imap.invalid",
                "imap_port": 993,
                "smtp_host": "smtp.invalid",
                "smtp_port": 465,
                "smtp_login": "qa-mailbox-broken@example.com",
                "smtp_password": "mail-pass-1",
                "inbox_folder": "INBOX",
                "archive_folder": "Archive",
                "is_default": 0,
                "is_active": 1,
            },
        )
        self.assertEqual(account_res.status_code, 200)
        account_id = account_res.json()["id"]

        tested = self.client.post(f"/api/email/accounts/{account_id}/test")
        self.assertEqual(tested.status_code, 200)
        payload = tested.json()
        self.assertEqual(payload["status"], "error")
        self.assertIn("imap", payload)
        self.assertIn("smtp", payload)
        self.assertFalse(payload["imap"]["ok"])

        retried = self.client.post(f"/api/email/retry_failed?account_id={account_id}")
        self.assertEqual(retried.status_code, 200)
        retried_payload = retried.json()
        self.assertEqual(retried_payload["status"], "success")
        self.assertTrue(any(item["account_id"] == account_id for item in retried_payload["failed_accounts"]))

    def test_quick_setup_autofills_mail_settings(self):
        account_res = self.client.post(
            "/api/email/accounts",
            json={
                "label": "",
                "address": "qa-mailbox-quick@example.com",
                "login": "",
                "password": "mail-pass-1",
                "imap_host": "",
                "imap_port": 0,
                "smtp_host": "",
                "smtp_port": 0,
                "smtp_login": "",
                "smtp_password": "",
                "inbox_folder": "",
                "archive_folder": "",
                "is_default": 0,
                "is_active": 0,
            },
        )
        self.assertEqual(account_res.status_code, 200)
        account_id = account_res.json()["id"]

        conn = get_connection()
        c = conn.cursor()
        c.execute(
            """
            SELECT label, address, login, imap_host, imap_port, smtp_host, smtp_port, smtp_login,
                   inbox_folder, archive_folder
            FROM email_accounts
            WHERE id=?
            """,
            (account_id,),
        )
        row = c.fetchone()
        conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], "qa-mailbox-quick")
        self.assertEqual(row[1], "qa-mailbox-quick@example.com")
        self.assertEqual(row[2], "qa-mailbox-quick@example.com")
        self.assertEqual(row[3], "imap.yandex.ru")
        self.assertEqual(row[4], 993)
        self.assertEqual(row[5], "smtp.yandex.ru")
        self.assertEqual(row[6], 465)
        self.assertEqual(row[7], "qa-mailbox-quick@example.com")
        self.assertEqual(row[8], "INBOX")
        self.assertEqual(row[9], "Archive")

        duplicate_res = self.client.post(
            "/api/email/accounts",
            json={
                "label": "Updated mailbox",
                "address": "qa-mailbox-quick@example.com",
                "login": "qa-mailbox-quick@example.com",
                "password": "mail-pass-2",
                "imap_host": "imap.invalid",
                "imap_port": 993,
                "smtp_host": "smtp.invalid",
                "smtp_port": 465,
                "smtp_login": "qa-mailbox-quick@example.com",
                "smtp_password": "mail-pass-2",
                "inbox_folder": "INBOX",
                "archive_folder": "Archive",
                "is_default": 0,
                "is_active": 0,
            },
        )
        self.assertEqual(duplicate_res.status_code, 200)
        self.assertEqual(duplicate_res.json()["id"], account_id)
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM email_accounts WHERE address=?", ("qa-mailbox-quick@example.com",))
        self.assertEqual(c.fetchone()[0], 1)
        conn.close()

        update_res = self.client.put(
            f"/api/email/accounts/{account_id}",
            json={
                "label": "",
                "address": "qa-mailbox-quick@example.com",
                "login": "",
                "password": "",
                "imap_host": "",
                "imap_port": 0,
                "smtp_host": "",
                "smtp_port": 0,
                "smtp_login": "",
                "smtp_password": "",
                "inbox_folder": "",
                "archive_folder": "",
                "is_default": 0,
                "is_active": 0,
            },
        )
        self.assertEqual(update_res.status_code, 200)
        self.assertEqual(update_res.json()["status"], "success")

        conn = get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM email_accounts WHERE id=?", (account_id,))
        conn.commit()
        conn.close()

    def test_exchange_message_parser(self):
        root = ET.fromstring('''
        <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"
                    xmlns:m="http://schemas.microsoft.com/exchange/services/2006/messages"
                    xmlns:t="http://schemas.microsoft.com/exchange/services/2006/types">
          <s:Body><m:GetItemResponse><m:ResponseMessages><m:GetItemResponseMessage ResponseClass="Success">
            <m:ResponseCode>NoError</m:ResponseCode><m:Items><t:Message>
              <t:ItemId Id="ews-1" ChangeKey="v1"/><t:Subject>Тест EWS</t:Subject>
              <t:Body BodyType="Text">Текст письма</t:Body><t:DateTimeReceived>2026-11-25T12:30:00Z</t:DateTimeReceived>
              <t:IsRead>true</t:IsRead><t:InternetMessageId>&lt;message@example.com&gt;</t:InternetMessageId>
              <t:From><t:Mailbox><t:Name>Отправитель</t:Name><t:EmailAddress>sender@example.com</t:EmailAddress></t:Mailbox></t:From>
            </t:Message></m:Items>
          </m:GetItemResponseMessage></m:ResponseMessages></m:GetItemResponse></s:Body>
        </s:Envelope>''')
        rows = _parse_exchange_ews_messages(root, 42)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["account_id"], 42)
        self.assertEqual(rows[0]["uid"], "ews-1")
        self.assertEqual(rows[0]["sender_email"], "sender@example.com")
        self.assertEqual(rows[0]["body_text"], "Текст письма")
        self.assertEqual(rows[0]["is_read"], 1)


if __name__ == "__main__":
    unittest.main()
