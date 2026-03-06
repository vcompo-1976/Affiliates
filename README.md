# BH-Affiliate-Audit

CLI scanner to audit affiliate websites for FTC disclosure signals.

## What it checks

For each affiliate URL, the scanner crawls the homepage plus a small set of likely policy/disclosure pages and reports:

- Disclosure language found (`commission`, `affiliate links`, `compensation`, etc.)
- `Clear and Conspicuous` (heuristic)
- `Sufficient Language` (heuristic)
- `No Action to View` (heuristic: appears on landing page text)
- `Frequent Disclosure` (heuristic based on disclosure coverage across scanned pages)
- `Explicit Commission Language` + passive language detection (`may/sometimes/can`)
- `Brand Identification Disclosed` (brand references in disclosure context)
- `Ranking Influence Disclosed` (if compensation affects rankings/placement/ratings)
- `Sponsored Content Disclosed`
- `Biz Op Policy Risk` (flags business opportunity category)
- Site category (`business opportunity`, `blog`, `directory/ranking`, `coupon`, `hybrid`, `domain registry`, `course`, `youtube/social media`)

## Files

- `scanner.py`: scanner CLI
- `affiliates_sample.csv`: sample input populated with your affiliate list

## Usage

```bash
python3 scanner.py --input affiliates_sample.csv --output audit_report.csv
```

Generate CSV + HTML dashboard together:

```bash
python3 scanner.py --input affiliates_sample.csv --output audit_report.csv --html-output audit_dashboard.html
```

Helpful options:

```bash
python3 scanner.py --input affiliates_sample.csv --output audit_report.csv --limit 10 --max-pages 5 --timeout 15
```

## Output columns

- `Disclosure Found`
- `Disclosure URLs`
- `Sample Disclosure Text`
- `Clear and Conspicuous`
- `Sufficient Language`
- `No Action to View`
- `Frequent Disclosure`
- `Explicit Commission Language`
- `Passive Language Detected`
- `Brand Identification Disclosed`
- `Ranking Influence Disclosed`
- `Sponsored Content Disclosed`
- `Biz Op Policy Risk`
- `Site Category`
- `Notes`

The optional HTML dashboard includes:

- KPI cards (total affiliates, disclosure found/missing, clear+conspicuous gaps, biz-op risk)
- Search and filters (risk tier, disclosure found, site category)
- Clickable partner URLs and condensed notes
- Added compliance columns mapped to your SharePoint framework

## Demo / Mock Preview (no crawling)

If you just want to see how the outputs look without hitting live affiliate sites, generate mock files:

```bash
python3 generate_mock_report.py --input affiliates_sample.csv --limit 10 --output mock_audit_report.csv --html-output mock_audit_dashboard.html
```

This creates:

- `mock_audit_report.csv` (sample report data)
- `mock_audit_dashboard.html` (interactive dashboard preview)

## Notes

- This is a rules-based pre-audit, not legal advice.
- Final FTC compliance determinations should be validated by legal/compliance reviewers.# Affiliates
