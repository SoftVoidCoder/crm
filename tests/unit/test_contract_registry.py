import datetime
import unittest

from routers.contract_registry import _vat, contract_flags, format_contract_number


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


if __name__ == "__main__":
    unittest.main()
