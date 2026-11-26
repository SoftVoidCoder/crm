import datetime
import unittest

from routers.contract_registry import _clean_data, _vat, access_level, contract_email_html, contract_flags, contract_reminders, format_contract_number


class ContractNumberTests(unittest.TestCase):
    def test_full_template_matches_registry_example(self):
        doc_type = {"prefix": "КР-", "digits": 5, "postfix": "/П-", "add_year": 1}
        self.assertEqual(format_contract_number(doc_type, 17, year=2022), "КР-00017/П-2022")

    def test_plain_prefix_without_padding(self):
        self.assertEqual(format_contract_number({"prefix": "ДПТ-", "digits": 0}, 1269), "ДПТ-1269")


class ContractFlagsTests(unittest.TestCase):
    today = datetime.date(2026, 11, 26)

    def test_overdue_and_expiring(self):
        self.assertTrue(contract_flags({"end_date": "2026-11-01"}, [], self.today)["overdue"])
        self.assertTrue(contract_flags({"end_date": "2026-12-10"}, [], self.today)["expiring"])
        self.assertFalse(contract_flags({"end_date": "2026-11-01", "indefinite": 1}, [], self.today)["overdue"])

    def test_approval_flags(self):
        flags = contract_flags({}, [{"status": "pending", "due_date": "2026-11-20"}, {"status": "approved", "due_date": "2026-01-01"}], self.today)
        self.assertTrue(flags["approvals_open"])
        self.assertTrue(flags["approvals_overdue"])


class VatTests(unittest.TestCase):
    def test_vat_is_extracted_from_inclusive_amount(self):
        self.assertEqual(_vat(120000, 20), 20000.0)
        self.assertEqual(_vat(1000, 0), 0.0)


class AccessLevelTests(unittest.TestCase):
    employee = {"role": "Сотрудник", "email": "ivan@korda.ru"}

    def test_open_contract_without_access_list(self):
        self.assertEqual(access_level(self.employee, {"created_by": "x@korda.ru"}, []), "edit")

    def test_access_list_restricts_others(self):
        rows = [{"user": "olga@korda.ru", "level": "edit"}]
        self.assertEqual(access_level(self.employee, {"created_by": "x@korda.ru"}, rows), "")
        self.assertEqual(access_level({"role": "Директор", "email": "d@korda.ru"}, {}, rows), "edit")
        self.assertEqual(access_level(self.employee, {"created_by": "IVAN@korda.ru"}, rows), "edit")
        self.assertEqual(access_level(self.employee, {}, [{"user": "ivan@korda.ru", "level": "read"}]), "read")

    def test_approver_reads_and_responsible_edits_restricted_contract(self):
        rows = [{"user": "olga@korda.ru", "level": "edit"}]
        self.assertEqual(access_level(self.employee, {}, rows, {"ivan@korda.ru"}), "read")
        self.assertEqual(access_level(self.employee, {"responsible_email": "ivan@korda.ru"}, rows), "edit")
        self.assertEqual(access_level(self.employee, {"initiator_email": "IVAN@korda.ru"}, rows), "edit")

    def test_full_name_requires_surname(self):
        from routers.users import full_name_error
        self.assertTrue(full_name_error("Иван"))
        self.assertTrue(full_name_error("  "))
        self.assertEqual(full_name_error("Иванов Иван"), "")
        self.assertEqual(full_name_error("Иванов Иван Иванович"), "")

    def test_section_data_is_flattened_and_bounded(self):
        data = _clean_data({"amount": 10.5, "note": {"nested": 1}, "": "x", "flag": True})
        self.assertEqual(data["amount"], 10.5)
        self.assertEqual(data["note"], "{'nested': 1}")
        self.assertEqual(data["flag"], "True")
        self.assertNotIn("", data)


class ContractEmailTests(unittest.TestCase):
    def test_email_shows_contract_sheet_and_escapes_input(self):
        page = contract_email_html(
            {"number": "ДПТ-0001/2026", "amount": 1200000, "vat_enabled": 1, "vat_amount": 200000, "subject": "<script>x</script>", "end_date": "2026-12-31"},
            [{"name": "ПАО СБЕРБАНК", "role": "Покупатель"}],
            [{"approver": "Пузанова Ольга", "position": "Юрист", "status": "approved"}, {"approver": "Колемасова Елена", "status": "pending", "due_date": "2026-12-01"}],
            "Требуется ваше согласование", "Вас добавили согласующим.", tone="action", link="https://crm/app#cr=1",
        )
        for text in ["ДПТ-0001/2026", "1 200 000,00 ₽", "ПАО СБЕРБАНК (Покупатель)", "Лист согласования · 1 из 2", "согласовано", "ждёт решения", "01.12.2026", "https://crm/app#cr=1"]:
            self.assertIn(text, page)
        self.assertNotIn("<script>", page)


class ReminderTests(unittest.TestCase):
    today = datetime.date(2026, 12, 10)
    contract = {"id": 1, "number": "Д-1", "status": "active", "is_deleted": 0, "created_by": "a@k.ru", "responsible_email": "r@k.ru",
                "end_date": "2026-12-20", "notify_enabled": 1, "notify_days": 10}

    def kinds(self, contracts=None, approvals=(), payments=()):
        return sorted(r["kind"] for r in contract_reminders(contracts or [self.contract], list(approvals), list(payments), self.today))

    def test_contract_ending_on_notify_day_and_expired(self):
        self.assertEqual(self.kinds(), ["contract_ending"])
        expired = {**self.contract, "end_date": "2026-12-01", "notify_enabled": 0}
        self.assertEqual(self.kinds([expired]), ["contract_expired"])
        self.assertEqual(self.kinds([{**expired, "status": "executed"}]), [])

    def test_approval_due_today_and_overdue(self):
        a = {"id": 5, "contract_id": 1, "approver": "Юрист", "approver_email": "j@k.ru", "status": "pending"}
        self.assertIn("appr_due_today", self.kinds(approvals=[{**a, "due_date": "2026-12-10"}]))
        self.assertTrue({"appr_overdue", "appr_overdue_owner"} <= set(self.kinds(approvals=[{**a, "due_date": "2026-12-05"}])))
        self.assertNotIn("appr_overdue", self.kinds(approvals=[{**a, "due_date": "2026-12-05", "status": "approved"}]))

    def test_payment_overdue_only_without_fact(self):
        p = {"id": 9, "contract_id": 1, "plan_date": "2026-12-01", "plan_amount": 500}
        self.assertIn("payment_overdue", self.kinds(payments=[p]))
        self.assertNotIn("payment_overdue", self.kinds(payments=[{**p, "fact_amount": 500}]))


if __name__ == "__main__":
    unittest.main()
