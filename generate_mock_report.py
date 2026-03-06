#!/usr/bin/env python3
"""Generate mock affiliate audit outputs without live crawling.

Useful for demos and stakeholder previews.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, List

from scanner import SiteAudit, write_dashboard, write_report


def read_rows(path: str) -> List[Dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def mock_row(row: Dict[str, str], idx: int) -> SiteAudit:
    rank = row.get("Overall Rank", "")
    url = row.get("Company URL", "")
    category_cycle = ["directory/ranking", "blog", "coupon", "hybrid", "youtube/social media", "course"]
    category = category_cycle[idx % len(category_cycle)]

    disclosure_found = idx % 4 != 3
    clear = "Yes" if disclosure_found and idx % 3 != 1 else "No"
    sufficient = "Yes" if disclosure_found and idx % 5 != 2 else "No"
    no_action = "Yes" if disclosure_found and idx % 2 == 0 else "No"
    frequent = "Yes" if disclosure_found and idx % 3 == 0 else "No"
    explicit = "Yes" if disclosure_found and idx % 2 == 0 else "No"
    passive = "Yes" if disclosure_found and idx % 6 == 0 else "No"
    brand_named = "Yes" if disclosure_found and idx % 2 == 0 else "No"
    ranking_influence = "Yes" if category == "directory/ranking" and disclosure_found else "No"
    sponsored = "Yes" if category == "directory/ranking" and idx % 7 == 0 else "No"
    bizop = "Yes" if category == "business opportunity" else "No"

    sample = (
        "We earn a commission if you make a purchase of Bluehost products through referral links. "
        "This compensation affects placement and ratings."
        if disclosure_found
        else ""
    )

    notes = "Mock data for dashboard/CSV preview"
    if not disclosure_found:
        notes = "No disclosure language detected (mock scenario)"
    elif clear == "No":
        notes = "Disclosure found but may not be clear/conspicuous (mock scenario)"

    return SiteAudit(
        rank=rank,
        partner_id=row.get("Partner Id", ""),
        partner=row.get("Partner", ""),
        company_url=url,
        ftc_risk_tier=row.get("FTC Risk Tier", ""),
        tier_rank=row.get("Tier Rank", ""),
        category=category,
        pages_scanned=(idx % 4) + 1,
        disclosure_found=disclosure_found,
        disclosure_urls=f"{url.rstrip('/')}/disclosure" if disclosure_found and url else "",
        sample_disclosure_text=sample,
        clear_and_conspicuous=clear,
        sufficient_language=sufficient,
        no_action_to_view=no_action,
        frequent_disclosure=frequent,
        explicit_commission_language=explicit,
        passive_language_detected=passive,
        brand_identification_disclosed=brand_named,
        ranking_influence_disclosed=ranking_influence,
        sponsored_content_disclosed=sponsored,
        biz_op_policy_risk=bizop,
        notes=notes,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate mock audit outputs (CSV + HTML dashboard)")
    parser.add_argument("--input", default="affiliates_sample.csv")
    parser.add_argument("--output", default="mock_audit_report.csv")
    parser.add_argument("--html-output", default="mock_audit_dashboard.html")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    rows = read_rows(args.input)[: args.limit]
    audits = [mock_row(r, i) for i, r in enumerate(rows)]

    write_report(args.output, audits)
    write_dashboard(args.html_output, audits)

    print(f"Mock CSV written to {Path(args.output).resolve()}")
    print(f"Mock HTML dashboard written to {Path(args.html_output).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
