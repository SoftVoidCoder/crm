import unittest

from utils import decrypt_secret, encrypt_secret, normalize_email, validate_password_strength


class UtilsUnitTests(unittest.TestCase):
    def test_secret_roundtrip(self):
        secret = "smtp-pass-42"
        encrypted = encrypt_secret(secret)
        self.assertNotEqual(secret, encrypted)
        self.assertEqual(decrypt_secret(encrypted), secret)

    def test_normalize_email(self):
        self.assertEqual(normalize_email("  USER@Example.COM "), "user@example.com")

    def test_password_strength(self):
        self.assertTrue(validate_password_strength("short"))
        self.assertEqual(validate_password_strength("Strongpass1"), "")


if __name__ == "__main__":
    unittest.main()
