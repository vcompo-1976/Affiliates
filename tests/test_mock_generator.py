import unittest

from generate_mock_report import mock_row


class MockGeneratorTests(unittest.TestCase):
    def test_mock_row_has_required_fields(self):
        src = {
            "Overall Rank": "1",
            "Partner Id": "123",
            "Partner": "Demo Partner",
            "Company URL": "https://example.com",
            "FTC Risk Tier": "High",
            "Tier Rank": "1",
        }
        out = mock_row(src, 0)
        self.assertEqual(out.rank, "1")
        self.assertEqual(out.partner, "Demo Partner")
        self.assertIn(out.clear_and_conspicuous, {"Yes", "No"})
        self.assertIn(out.explicit_commission_language, {"Yes", "No"})


if __name__ == "__main__":
    unittest.main()
