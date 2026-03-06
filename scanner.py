#!/usr/bin/env python3
"""Affiliate FTC disclosure scanner.

Reads an affiliate list CSV and audits each site for:
- presence of affiliate disclosure language
- heuristic clarity/conspicuousness
- heuristic sufficiency against FTC-style expectations
- whether disclosure appears without extra action (on landing page)
- site type classification

Output: CSV report with per-site findings.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

USER_AGENT = "Mozilla/5.0 (compatible; BH-Affiliate-Audit/1.0; +https://example.com)"

DISCLOSURE_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\baffiliate\s+links?\b",
        r"\baffiliate\s+disclosure\b",
        r"\bwe\s+earn\s+(a\s+)?commission\b",
        r"\bwe\s+may\s+earn\s+(a\s+)?commission\b",
        r"\bwe\s+receive\s+commissions?\b",
        r"\bcompensation\s+affects\b",
        r"\bpaid\s+partnership\b",
        r"\bsponsored\b",
        r"\breferral\s+links?\b",
        r"\bat\s+no\s+additional\s+cost\s+to\s+you\b",
    ]
]

DISCLOSURE_LINK_HINT = re.compile(
    r"(affiliate|disclosure|how\s+we\s+make\s+money|editorial\s+policy|about|terms|privacy)",
    re.IGNORECASE,
)

CATEGORY_RULES = {
    "coupon": ["coupon", "vouchercode", "deals", "retailmenot", "honey"],
    "directory/ranking": ["top10", "best", "compare", "comparison", "directory", "ratings"],
    "domain registry": ["domain registry", "whois", "registrar", "registry"],
    "business opportunity": ["business opportunity", "make money", "income report", "side hustle"],
    "blog": ["blog", "wordpress", "wp", "personal finance", "how to", "guide"],
    "course": ["course", "academy", "training", "coaching", "masterclass"],
    "youtube/social media": ["youtube.com", "instagram.com", "tiktok.com", "facebook.com", "x.com", "twitter.com"],
}

BRAND_HINTS = ["bluehost", "hostgator", "domain.com", "web.com", "network solutions", "newfold"]


class LinkAndTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: List[str] = []
        self.links: List[Tuple[str, str]] = []
        self._current_href: Optional[str] = None
        self._capture_link_text = False
        self._link_text_parts: List[str] = []
        self._suppress_depth = 0

    def handle_starttag(self, tag: str, attrs: Sequence[Tuple[str, Optional[str]]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._suppress_depth += 1
            return
        if tag == "a":
            href = dict(attrs).get("href")
            self._current_href = href
            self._capture_link_text = True
            self._link_text_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._suppress_depth:
            self._suppress_depth -= 1
            return
        if tag == "a" and self._capture_link_text:
            text = " ".join(self._link_text_parts).strip()
            if self._current_href:
                self.links.append((self._current_href, text))
            self._current_href = None
            self._capture_link_text = False
            self._link_text_parts = []

    def handle_data(self, data: str) -> None:
        if self._suppress_depth:
            return
        cleaned = " ".join(data.split())
        if cleaned:
            self.text_parts.append(cleaned)
            if self._capture_link_text:
                self._link_text_parts.append(cleaned)


@dataclass
class PageScan:
    url: str
    disclosure_hits: List[str] = field(default_factory=list)
    has_disclosure: bool = False
    text_excerpt: str = ""
    full_text: str = ""


@dataclass
class SiteAudit:
    rank: str
    partner_id: str
    partner: str
    company_url: str
    ftc_risk_tier: str
    tier_rank: str
    category: str
    pages_scanned: int
    disclosure_found: bool
    disclosure_urls: str
    sample_disclosure_text: str
    clear_and_conspicuous: str
    sufficient_language: str
    no_action_to_view: str
    frequent_disclosure: str
    explicit_commission_language: str
    passive_language_detected: str
    brand_identification_disclosed: str
    ranking_influence_disclosed: str
    sponsored_content_disclosed: str
    biz_op_policy_risk: str
    notes: str


def normalize_url(url: str) -> str:
    candidate = (url or "").strip()
    if not candidate:
        return ""
    if not candidate.startswith(("http://", "https://")):
        candidate = "https://" + candidate
    return candidate


def fetch_html(url: str, timeout: int = 12) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as resp:
        content_type = resp.headers.get("Content-Type", "")
        if "text/html" not in content_type:
            return ""
        charset = resp.headers.get_content_charset() or "utf-8"
        raw = resp.read()
        return raw.decode(charset, errors="replace")


def extract_text_and_links(html_content: str) -> Tuple[str, List[Tuple[str, str]]]:
    parser = LinkAndTextParser()
    parser.feed(html_content)
    parser.close()
    text = html.unescape(" ".join(parser.text_parts))
    text = re.sub(r"\s+", " ", text).strip()
    return text, parser.links


def find_disclosure_hits(text: str) -> List[str]:
    hits: List[str] = []
    for pat in DISCLOSURE_PATTERNS:
        m = pat.search(text)
        if m:
            hits.append(m.group(0))
    return sorted(set(hits))


def select_followup_links(base_url: str, links: Iterable[Tuple[str, str]], max_links: int) -> List[str]:
    parsed_base = urlparse(base_url)
    same_host = parsed_base.netloc.lower()
    candidates: List[str] = []
    seen: Set[str] = set()

    for href, anchor_text in links:
        if not href:
            continue
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue
        if parsed.netloc.lower() != same_host:
            continue
        normalized = parsed._replace(fragment="").geturl()
        haystack = f"{anchor_text} {parsed.path}".lower()
        if DISCLOSURE_LINK_HINT.search(haystack) and normalized not in seen:
            seen.add(normalized)
            candidates.append(normalized)
            if len(candidates) >= max_links:
                break
    return candidates


def classify_site(url: str, aggregate_text: str) -> str:
    hay = f"{url} {aggregate_text[:8000]}".lower()
    matched: List[str] = []
    for category, keywords in CATEGORY_RULES.items():
        if any(k in hay for k in keywords):
            matched.append(category)

    if not matched:
        return "hybrid"
    if len(matched) == 1:
        return matched[0]
    if "youtube/social media" in matched:
        return "youtube/social media"
    if "course" in matched:
        return "course"
    if "coupon" in matched:
        return "coupon"
    if "domain registry" in matched:
        return "domain registry"
    if "directory/ranking" in matched:
        return "directory/ranking"
    if "business opportunity" in matched:
        return "business opportunity"
    if "blog" in matched and len(matched) == 2 and "business opportunity" not in matched:
        return "blog"
    return "hybrid"


def evaluate_disclosure_quality(page_results: List[PageScan], homepage_text: str) -> Tuple[str, str, str, str, str]:
    disclosure_pages = [p for p in page_results if p.has_disclosure]
    disclosure_found = bool(disclosure_pages)
    urls = "; ".join(p.url for p in disclosure_pages)
    sample_text = disclosure_pages[0].text_excerpt if disclosure_pages else ""

    if not disclosure_found:
        return "No", "No", "No", "No", "No disclosure language detected with current patterns"

    lower_home = homepage_text.lower()
    top_slice = lower_home[: max(5000, len(lower_home) // 3)]
    on_homepage = bool(find_disclosure_hits(top_slice))

    sufficiency_signals = [
        bool(re.search(r"\bcommission\b", sample_text, re.IGNORECASE)),
        bool(re.search(r"\baffiliate\b", sample_text, re.IGNORECASE)),
        bool(re.search(r"\bcompensation\b|\bpaid\b|\bsponsored\b", sample_text, re.IGNORECASE)),
    ]
    sufficient = sum(sufficiency_signals) >= 2

    clear = on_homepage and sufficient
    no_action = on_homepage

    notes = []
    if not on_homepage:
        notes.append("Disclosure found off landing page; may require user action")
    if not sufficient:
        notes.append("Language may be generic; consider explicit commission/placement impact wording")

    return (
        "Yes",
        "Yes" if clear else "No",
        "Yes" if sufficient else "No",
        "Yes" if no_action else "No",
        "; ".join(notes) if notes else "Disclosure language appears explicit in scanned content",
    )


def evaluate_program_requirements(page_results: List[PageScan], category: str) -> Dict[str, str]:
    if not page_results:
        return {
            "frequent_disclosure": "No",
            "explicit_commission_language": "No",
            "passive_language_detected": "Unknown",
            "brand_identification_disclosed": "No",
            "ranking_influence_disclosed": "No",
            "sponsored_content_disclosed": "No",
            "biz_op_policy_risk": "Unknown",
        }

    texts = [p.full_text or p.text_excerpt for p in page_results]
    aggregate = " ".join(texts)
    aggregate_lower = aggregate.lower()
    disclosure_pages = [p for p in page_results if p.has_disclosure]

    explicit_commission = bool(re.search(r"\b(i|we)\s+(earn|receive)\s+(a\s+)?commission", aggregate, re.IGNORECASE))
    passive_detected = bool(re.search(r"\b(may|sometimes|can)\s+earn\s+(a\s+)?commission", aggregate, re.IGNORECASE))
    brand_identified = any(brand in aggregate_lower for brand in BRAND_HINTS)
    ranking_influence = bool(
        re.search(
            r"(compensation|commission).{0,50}(affect|influence).{0,50}(ranking|placement|rating)",
            aggregate,
            re.IGNORECASE,
        )
    )
    sponsored_content = bool(re.search(r"\bsponsored\s+content\b", aggregate, re.IGNORECASE))
    disclosure_ratio = len(disclosure_pages) / max(len(page_results), 1)

    return {
        "frequent_disclosure": "Yes" if disclosure_ratio >= 0.5 else "No",
        "explicit_commission_language": "Yes" if explicit_commission else "No",
        "passive_language_detected": "Yes" if passive_detected else "No",
        "brand_identification_disclosed": "Yes" if brand_identified else "No",
        "ranking_influence_disclosed": "Yes" if ranking_influence else "No",
        "sponsored_content_disclosed": "Yes" if sponsored_content else "No",
        "biz_op_policy_risk": "Yes" if category == "business opportunity" else "No",
    }


def scan_site(url: str, timeout: int, max_pages: int) -> Tuple[List[PageScan], str, str]:
    homepage_html = fetch_html(url, timeout=timeout)
    if not homepage_html:
        return [], "", "Could not fetch HTML content"

    homepage_text, links = extract_text_and_links(homepage_html)
    pages: List[PageScan] = []

    home_hits = find_disclosure_hits(homepage_text)
    excerpt = homepage_text[:300]
    pages.append(PageScan(url=url, disclosure_hits=home_hits, has_disclosure=bool(home_hits), text_excerpt=excerpt, full_text=homepage_text[:20000]))

    for follow_url in select_followup_links(url, links, max_links=max_pages - 1):
        try:
            child_html = fetch_html(follow_url, timeout=timeout)
            if not child_html:
                continue
            text, _ = extract_text_and_links(child_html)
            hits = find_disclosure_hits(text)
            pages.append(PageScan(url=follow_url, disclosure_hits=hits, has_disclosure=bool(hits), text_excerpt=text[:300], full_text=text[:20000]))
        except Exception:
            continue

    aggregate = " ".join(p.text_excerpt for p in pages)
    return pages, homepage_text, aggregate


def read_affiliates(path: str) -> List[Dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_report(path: str, rows: List[SiteAudit]) -> None:
    fields = [
        "Overall Rank",
        "Partner Id",
        "Partner",
        "Company URL",
        "FTC Risk Tier",
        "Tier Rank",
        "Site Category",
        "Pages Scanned",
        "Disclosure Found",
        "Disclosure URLs",
        "Sample Disclosure Text",
        "Clear and Conspicuous",
        "Sufficient Language",
        "No Action to View",
        "Frequent Disclosure",
        "Explicit Commission Language",
        "Passive Language Detected",
        "Brand Identification Disclosed",
        "Ranking Influence Disclosed",
        "Sponsored Content Disclosed",
        "Biz Op Policy Risk",
        "Notes",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            writer.writerow(
                {
                    "Overall Rank": r.rank,
                    "Partner Id": r.partner_id,
                    "Partner": r.partner,
                    "Company URL": r.company_url,
                    "FTC Risk Tier": r.ftc_risk_tier,
                    "Tier Rank": r.tier_rank,
                    "Site Category": r.category,
                    "Pages Scanned": r.pages_scanned,
                    "Disclosure Found": r.disclosure_found,
                    "Disclosure URLs": r.disclosure_urls,
                    "Sample Disclosure Text": r.sample_disclosure_text,
                    "Clear and Conspicuous": r.clear_and_conspicuous,
                    "Sufficient Language": r.sufficient_language,
                    "No Action to View": r.no_action_to_view,
                    "Frequent Disclosure": r.frequent_disclosure,
                    "Explicit Commission Language": r.explicit_commission_language,
                    "Passive Language Detected": r.passive_language_detected,
                    "Brand Identification Disclosed": r.brand_identification_disclosed,
                    "Ranking Influence Disclosed": r.ranking_influence_disclosed,
                    "Sponsored Content Disclosed": r.sponsored_content_disclosed,
                    "Biz Op Policy Risk": r.biz_op_policy_risk,
                    "Notes": r.notes,
                }
            )


def write_dashboard(path: str, rows: List[SiteAudit]) -> None:
    rows_payload = [
        {
            "overall_rank": r.rank,
            "partner_id": r.partner_id,
            "partner": r.partner,
            "company_url": r.company_url,
            "ftc_risk_tier": r.ftc_risk_tier,
            "tier_rank": r.tier_rank,
            "site_category": r.category,
            "pages_scanned": r.pages_scanned,
            "disclosure_found": "Yes" if r.disclosure_found else "No",
            "clear_and_conspicuous": r.clear_and_conspicuous,
            "sufficient_language": r.sufficient_language,
            "no_action_to_view": r.no_action_to_view,
            "disclosure_urls": r.disclosure_urls,
            "sample_disclosure_text": r.sample_disclosure_text,
            "frequent_disclosure": r.frequent_disclosure,
            "explicit_commission_language": r.explicit_commission_language,
            "passive_language_detected": r.passive_language_detected,
            "brand_identification_disclosed": r.brand_identification_disclosed,
            "ranking_influence_disclosed": r.ranking_influence_disclosed,
            "sponsored_content_disclosed": r.sponsored_content_disclosed,
            "biz_op_policy_risk": r.biz_op_policy_risk,
            "notes": r.notes,
        }
        for r in rows
    ]

    html_doc = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Affiliate FTC Audit Dashboard</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 20px; color: #1a1a1a; }}
    h1 {{ margin-bottom: 6px; }}
    .muted {{ color: #666; margin-top: 0; }}
    .controls {{ display: flex; gap: 12px; flex-wrap: wrap; margin: 14px 0; }}
    label {{ font-size: 14px; display: flex; flex-direction: column; gap: 4px; }}
    input, select {{ padding: 6px 8px; min-width: 180px; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; margin-bottom: 14px; }}
    .card {{ border: 1px solid #ddd; border-radius: 8px; padding: 10px; background: #fafafa; }}
    .card .label {{ font-size: 12px; color: #666; }}
    .card .value {{ font-size: 22px; font-weight: 700; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; vertical-align: top; }}
    th {{ background: #f0f3f8; position: sticky; top: 0; }}
    tr:nth-child(even) {{ background: #fcfcfc; }}
    .yes {{ color: #0b7a34; font-weight: 700; }}
    .no {{ color: #9a2020; font-weight: 700; }}
    .truncate {{ max-width: 350px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  </style>
</head>
<body>
  <h1>Affiliate FTC Audit Dashboard</h1>
  <p class=\"muted\">Heuristic pre-audit view of disclosure and categorization results.</p>
  <div class=\"cards\">
    <div class=\"card\"><div class=\"label\">Affiliates</div><div class=\"value\" id=\"kpiTotal\">0</div></div>
    <div class=\"card\"><div class=\"label\">Disclosure Found</div><div class=\"value\" id=\"kpiFound\">0</div></div>
    <div class=\"card\"><div class=\"label\">No Disclosure</div><div class=\"value\" id=\"kpiMissing\">0</div></div>
    <div class=\"card\"><div class=\"label\">Clear & Conspicuous = No</div><div class=\"value\" id=\"kpiClearNo\">0</div></div>
    <div class=\"card\"><div class=\"label\">Biz Op Policy Risk</div><div class=\"value\" id=\"kpiBizOp\">0</div></div>
  </div>
  <div class=\"controls\">
    <label>Search partner / URL
      <input id=\"search\" placeholder=\"type to filter\" />
    </label>
    <label>FTC Risk Tier
      <select id=\"tier\"><option value=\"\">All</option><option>High</option><option>Medium</option><option>Low</option></select>
    </label>
    <label>Disclosure Found
      <select id=\"found\"><option value=\"\">All</option><option>Yes</option><option>No</option></select>
    </label>
    <label>Site Category
      <select id=\"category\"><option value=\"\">All</option></select>
    </label>
  </div>
  <table>
    <thead>
      <tr>
        <th>Rank</th><th>Partner</th><th>URL</th><th>Risk</th><th>Category</th><th>Disclosure</th><th>Clear?</th><th>Sufficient?</th><th>No Action?</th><th>Frequent?</th><th>Explicit Commission?</th><th>Brand Named?</th><th>Ranking Influence?</th><th>Passive Language?</th><th>Biz Op Risk?</th><th>Notes</th>
      </tr>
    </thead>
    <tbody id=\"rows\"></tbody>
  </table>
  <script>
    const DATA = {json.dumps(rows_payload)};
    const rowsEl = document.getElementById('rows');
    const searchEl = document.getElementById('search');
    const tierEl = document.getElementById('tier');
    const foundEl = document.getElementById('found');
    const categoryEl = document.getElementById('category');

    const categories = [...new Set(DATA.map(r => r.site_category).filter(Boolean))].sort();
    for (const c of categories) {{
      const option = document.createElement('option');
      option.textContent = c;
      categoryEl.appendChild(option);
    }}

    function badgeClass(v) {{
      return String(v).toLowerCase() === 'yes' ? 'yes' : 'no';
    }}

    function rowHtml(r) {{
      return `<tr>
        <td>${{r.overall_rank}}</td>
        <td>${{r.partner}}</td>
        <td class=\"truncate\" title=\"${{r.company_url}}\"><a href=\"${{r.company_url}}\" target=\"_blank\" rel=\"noopener noreferrer\">${{r.company_url}}</a></td>
        <td>${{r.ftc_risk_tier}} #${{r.tier_rank}}</td>
        <td>${{r.site_category}}</td>
        <td class=\"${{badgeClass(r.disclosure_found)}}\">${{r.disclosure_found}}</td>
        <td class=\"${{badgeClass(r.clear_and_conspicuous)}}\">${{r.clear_and_conspicuous}}</td>
        <td class=\"${{badgeClass(r.sufficient_language)}}\">${{r.sufficient_language}}</td>
        <td class=\"${{badgeClass(r.no_action_to_view)}}\">${{r.no_action_to_view}}</td>
        <td class=\"${{badgeClass(r.frequent_disclosure)}}\">${{r.frequent_disclosure}}</td>
        <td class=\"${{badgeClass(r.explicit_commission_language)}}\">${{r.explicit_commission_language}}</td>
        <td class=\"${{badgeClass(r.brand_identification_disclosed)}}\">${{r.brand_identification_disclosed}}</td>
        <td class=\"${{badgeClass(r.ranking_influence_disclosed)}}\">${{r.ranking_influence_disclosed}}</td>
        <td class=\"${{badgeClass(r.passive_language_detected === 'Yes' ? 'No' : 'Yes')}}\">${{r.passive_language_detected}}</td>
        <td class=\"${{badgeClass(r.biz_op_policy_risk === 'Yes' ? 'No' : 'Yes')}}\">${{r.biz_op_policy_risk}}</td>
        <td class=\"truncate\" title=\"${{r.notes || ''}}\">${{r.notes || ''}}</td>
      </tr>`;
    }}

    function render() {{
      const q = searchEl.value.trim().toLowerCase();
      const tier = tierEl.value;
      const found = foundEl.value;
      const category = categoryEl.value;
      const filtered = DATA.filter(r => {{
        const matchesSearch = !q || `${{r.partner}} ${{r.company_url}}`.toLowerCase().includes(q);
        const matchesTier = !tier || r.ftc_risk_tier === tier;
        const matchesFound = !found || r.disclosure_found === found;
        const matchesCategory = !category || r.site_category === category;
        return matchesSearch && matchesTier && matchesFound && matchesCategory;
      }});

      rowsEl.innerHTML = filtered.map(rowHtml).join('');

      document.getElementById('kpiTotal').textContent = filtered.length;
      const foundCount = filtered.filter(r => r.disclosure_found === 'Yes').length;
      document.getElementById('kpiFound').textContent = foundCount;
      document.getElementById('kpiMissing').textContent = filtered.length - foundCount;
      document.getElementById('kpiClearNo').textContent = filtered.filter(r => r.clear_and_conspicuous === 'No').length;
      document.getElementById('kpiBizOp').textContent = filtered.filter(r => r.biz_op_policy_risk === 'Yes').length;
    }}

    [searchEl, tierEl, foundEl, categoryEl].forEach(el => el.addEventListener('input', render));
    render();
  </script>
</body>
</html>
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html_doc)


def audit_affiliates(
    input_csv: str,
    output_csv: str,
    timeout: int,
    max_pages: int,
    limit: Optional[int],
    html_output: Optional[str],
) -> None:
    affiliates = read_affiliates(input_csv)
    if limit:
        affiliates = affiliates[:limit]

    output: List[SiteAudit] = []
    for row in affiliates:
        rank = row.get("Overall Rank", "")
        partner_id = row.get("Partner Id", "")
        partner = row.get("Partner", "")
        raw_url = row.get("Company URL", "")
        ftc_risk = row.get("FTC Risk Tier", "")
        tier_rank = row.get("Tier Rank", "")

        url = normalize_url(raw_url)
        if not url:
            output.append(
                SiteAudit(
                    rank=rank,
                    partner_id=partner_id,
                    partner=partner,
                    company_url=raw_url,
                    ftc_risk_tier=ftc_risk,
                    tier_rank=tier_rank,
                    category="unknown",
                    pages_scanned=0,
                    disclosure_found=False,
                    disclosure_urls="",
                    sample_disclosure_text="",
                    clear_and_conspicuous="No",
                    sufficient_language="No",
                    no_action_to_view="No",
                    frequent_disclosure="No",
                    explicit_commission_language="No",
                    passive_language_detected="Unknown",
                    brand_identification_disclosed="No",
                    ranking_influence_disclosed="No",
                    sponsored_content_disclosed="No",
                    biz_op_policy_risk="Unknown",
                    notes="Missing company URL",
                )
            )
            continue

        try:
            pages, homepage_text, aggregate = scan_site(url, timeout=timeout, max_pages=max_pages)
            if not pages:
                output.append(
                    SiteAudit(
                        rank=rank,
                        partner_id=partner_id,
                        partner=partner,
                        company_url=url,
                        ftc_risk_tier=ftc_risk,
                        tier_rank=tier_rank,
                        category="unknown",
                        pages_scanned=0,
                        disclosure_found=False,
                        disclosure_urls="",
                        sample_disclosure_text="",
                        clear_and_conspicuous="No",
                        sufficient_language="No",
                        no_action_to_view="No",
                        frequent_disclosure="No",
                        explicit_commission_language="No",
                        passive_language_detected="Unknown",
                        brand_identification_disclosed="No",
                        ranking_influence_disclosed="No",
                        sponsored_content_disclosed="No",
                        biz_op_policy_risk="Unknown",
                        notes="Unable to crawl site HTML",
                    )
                )
                continue

            found, clear, sufficient, no_action, notes = evaluate_disclosure_quality(pages, homepage_text)
            disclosure_pages = [p.url for p in pages if p.has_disclosure]
            sample = next((p.text_excerpt for p in pages if p.has_disclosure), "")
            category = classify_site(url, aggregate)
            reqs = evaluate_program_requirements(pages, category)

            output.append(
                SiteAudit(
                    rank=rank,
                    partner_id=partner_id,
                    partner=partner,
                    company_url=url,
                    ftc_risk_tier=ftc_risk,
                    tier_rank=tier_rank,
                    category=category,
                    pages_scanned=len(pages),
                    disclosure_found=(found == "Yes"),
                    disclosure_urls="; ".join(disclosure_pages),
                    sample_disclosure_text=sample,
                    clear_and_conspicuous=clear,
                    sufficient_language=sufficient,
                    no_action_to_view=no_action,
                    frequent_disclosure=reqs["frequent_disclosure"],
                    explicit_commission_language=reqs["explicit_commission_language"],
                    passive_language_detected=reqs["passive_language_detected"],
                    brand_identification_disclosed=reqs["brand_identification_disclosed"],
                    ranking_influence_disclosed=reqs["ranking_influence_disclosed"],
                    sponsored_content_disclosed=reqs["sponsored_content_disclosed"],
                    biz_op_policy_risk=reqs["biz_op_policy_risk"],
                    notes=notes,
                )
            )
        except (HTTPError, URLError, TimeoutError) as exc:
            output.append(
                SiteAudit(
                    rank=rank,
                    partner_id=partner_id,
                    partner=partner,
                    company_url=url,
                    ftc_risk_tier=ftc_risk,
                    tier_rank=tier_rank,
                    category="unknown",
                    pages_scanned=0,
                    disclosure_found=False,
                    disclosure_urls="",
                    sample_disclosure_text="",
                    clear_and_conspicuous="No",
                    sufficient_language="No",
                    no_action_to_view="No",
                    frequent_disclosure="No",
                    explicit_commission_language="No",
                    passive_language_detected="Unknown",
                    brand_identification_disclosed="No",
                    ranking_influence_disclosed="No",
                    sponsored_content_disclosed="No",
                    biz_op_policy_risk="Unknown",
                    notes=f"Network error: {exc}",
                )
            )
        except Exception as exc:
            output.append(
                SiteAudit(
                    rank=rank,
                    partner_id=partner_id,
                    partner=partner,
                    company_url=url,
                    ftc_risk_tier=ftc_risk,
                    tier_rank=tier_rank,
                    category="unknown",
                    pages_scanned=0,
                    disclosure_found=False,
                    disclosure_urls="",
                    sample_disclosure_text="",
                    clear_and_conspicuous="No",
                    sufficient_language="No",
                    no_action_to_view="No",
                    frequent_disclosure="No",
                    explicit_commission_language="No",
                    passive_language_detected="Unknown",
                    brand_identification_disclosed="No",
                    ranking_influence_disclosed="No",
                    sponsored_content_disclosed="No",
                    biz_op_policy_risk="Unknown",
                    notes=f"Unhandled error: {exc}",
                )
            )

    write_report(output_csv, output)
    if html_output:
        write_dashboard(html_output, output)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Scan affiliate websites for FTC disclosure signals")
    p.add_argument("--input", required=True, help="Input CSV with affiliate rows")
    p.add_argument("--output", required=True, help="Output CSV report path")
    p.add_argument("--timeout", type=int, default=12, help="HTTP timeout seconds per request")
    p.add_argument("--max-pages", type=int, default=4, help="Max pages scanned per site")
    p.add_argument("--limit", type=int, default=None, help="Optional row limit for test runs")
    p.add_argument("--html-output", default=None, help="Optional path for HTML dashboard output")
    return p.parse_args(argv)


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    audit_affiliates(
        input_csv=args.input,
        output_csv=args.output,
        timeout=args.timeout,
        max_pages=args.max_pages,
        limit=args.limit,
        html_output=args.html_output,
    )
    print(f"Audit complete. Report written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
