import tempfile
import unittest
from pathlib import Path

from scanner import (
    PageScan,
    SiteAudit,
    classify_site,
    evaluate_disclosure_quality,
    evaluate_program_requirements,
    find_disclosure_hits,
    write_dashboard,
)


class ScannerRulesTests(unittest.TestCase):
    def test_find_disclosure_hits(self):
        text = "We earn a commission through affiliate links at no additional cost to you."
        hits = find_disclosure_hits(text)
        self.assertTrue(any("commission" in h.lower() for h in hits))
        self.assertTrue(any("affiliate links" in h.lower() for h in hits))

    def test_classify_coupon(self):
        category = classify_site("https://examplecoupon.com", "best coupon deals and voucher codes")
        self.assertEqual(category, "coupon")

    def test_quality_on_homepage(self):
        pages = [
            PageScan(
                url="https://example.com",
                has_disclosure=True,
                disclosure_hits=["affiliate links", "commission"],
                text_excerpt="We earn a commission from affiliate links and this compensation may affect rankings.",
                full_text="We earn a commission from affiliate links and this compensation may affect rankings.",
            )
        ]
        found, clear, sufficient, no_action, _ = evaluate_disclosure_quality(pages, pages[0].text_excerpt)
        self.assertEqual((found, clear, sufficient, no_action), ("Yes", "Yes", "Yes", "Yes"))

    def test_program_requirements(self):
        pages = [
            PageScan(
                url="https://example.com",
                has_disclosure=True,
                disclosure_hits=["commission"],
                text_excerpt="",
                full_text=(
                    "We earn a commission if you purchase Bluehost through our referral links. "
                    "This compensation affects ranking placement and ratings."
                ),
            )
        ]
        reqs = evaluate_program_requirements(pages, "directory/ranking")
        self.assertEqual(reqs["explicit_commission_language"], "Yes")
        self.assertEqual(reqs["brand_identification_disclosed"], "Yes")
        self.assertEqual(reqs["ranking_influence_disclosed"], "Yes")
        self.assertEqual(reqs["biz_op_policy_risk"], "No")

    def test_write_dashboard(self):
        rows = [
            SiteAudit(
                rank="1",
                partner_id="123",
                partner="Partner A",
                company_url="https://example.com",
                ftc_risk_tier="High",
                tier_rank="1",
                category="blog",
                pages_scanned=2,
                disclosure_found=True,
                disclosure_urls="https://example.com/disclosure",
                sample_disclosure_text="We earn a commission.",
                clear_and_conspicuous="Yes",
                sufficient_language="Yes",
                no_action_to_view="Yes",
                frequent_disclosure="Yes",
                explicit_commission_language="Yes",
                passive_language_detected="No",
                brand_identification_disclosed="Yes",
                ranking_influence_disclosed="No",
                sponsored_content_disclosed="No",
                biz_op_policy_risk="No",
                notes="ok",
            )
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "dashboard.html"
            write_dashboard(str(out), rows)
            content = out.read_text(encoding="utf-8")
            self.assertIn("Affiliate FTC Audit Dashboard", content)
            self.assertIn("Partner A", content)
            self.assertIn("Explicit Commission", content)


if __name__ == "__main__":
    unittest.main()
