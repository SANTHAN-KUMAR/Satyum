# Satyum Discrimination Report

Generated: 2026-06-30T11:17:02.466943

| # | File | Category | Verdict | Score | Key Signal | Description |
|---|------|----------|---------|-------|------------|-------------|
| 1 | `canara_direct/genuine.pdf` | genuine | REVIEW | 80.0 | `font_layout(1.00)` | Genuine Canara statement (pdf) |
| 2 | `canara_direct/genuine.png` | genuine | REVIEW | 71.4 | `font_layout(1.00)` | Genuine Canara statement (png) |
| 3 | `canara_direct/tamper_salary_inflate.pdf` | tampered | REVIEW | 80.0 | `font_layout(1.00)` | Tampered: RTGS credit inflated 5.8L→8.8L (pdf) |
| 4 | `canara_direct/tamper_salary_inflate.png` | tampered | REVIEW | 71.4 | `font_layout(1.00)` | Tampered: RTGS credit inflated 5.8L→8.8L (png) |
| 5 | `canara_direct/tamper_closing_balance.pdf` | tampered | REVIEW | 80.0 | `font_layout(1.00)` | Tampered: Closing balance edited 22K→52K (pdf) |
| 6 | `canara_direct/tamper_closing_balance.png` | tampered | REVIEW | 71.4 | `font_layout(1.00)` | Tampered: Closing balance edited 22K→52K (png) |
| 7 | `canara_direct/tamper_debit_remove.pdf` | tampered | REVIEW | 80.0 | `font_layout(1.00)` | Tampered: Debit zeroed out (pdf) |
| 8 | `canara_direct/tamper_debit_remove.png` | tampered | REVIEW | 71.4 | `font_layout(1.00)` | Tampered: Debit zeroed out (png) |
| 9 | `canara_direct/tamper_partial_recompute.pdf` | tampered | REVIEW | 80.0 | `font_layout(1.00)` | Tampered: Credit+balance edited, next row breaks (pdf) |
| 10 | `canara_direct/tamper_partial_recompute.png` | tampered | REVIEW | 71.4 | `font_layout(1.00)` | Tampered: Credit+balance edited, next row breaks (png) |
| 11 | `canara_direct/tamper_opening_balance.pdf` | tampered | REVIEW | 80.0 | `font_layout(1.00)` | Tampered: Opening balance fabricated 0→50K (pdf) |
| 12 | `canara_direct/tamper_opening_balance.png` | tampered | REVIEW | 71.4 | `font_layout(1.00)` | Tampered: Opening balance fabricated 0→50K (png) |
| 13 | `canara_cams/genuine.pdf` | cams_layout | REVIEW | 71.9 | `pdf_only_red_flag(0.55)` | CAMSfinserv genuine (pdf) |
| 14 | `canara_cams/genuine.png` | cams_layout | REVIEW | 65.7 | `font_layout(1.00)` | CAMSfinserv genuine (png) |
| 15 | `canara_cams/tamper_amount_inflate.pdf` | cams_layout | REVIEW | 69.0 | `pdf_only_red_flag(0.55)` | CAMSfinserv tamper_amount_inflate (pdf) |
| 16 | `canara_cams/tamper_amount_inflate.png` | cams_layout | REVIEW | 65.7 | `font_layout(1.00)` | CAMSfinserv tamper_amount_inflate (png) |
| 17 | `identity/aadhaar_genuine.pdf` | identity | REVIEW | 60.0 | `` | Identity: aadhaar_genuine (pdf) |
| 18 | `identity/aadhaar_genuine.png` | identity | REJECTED | 46.5 | `font_layout(1.00)` | Identity: aadhaar_genuine (png) |
| 19 | `identity/aadhaar_name_mismatch.pdf` | identity | REVIEW | 60.0 | `` | Identity: aadhaar_name_mismatch (pdf) |
| 20 | `identity/aadhaar_name_mismatch.png` | identity | REJECTED | 46.4 | `font_layout(1.00)` | Identity: aadhaar_name_mismatch (png) |
| 21 | `identity/aadhaar_number_typo.pdf` | identity | REVIEW | 60.0 | `` | Identity: aadhaar_number_typo (pdf) |
| 22 | `identity/aadhaar_number_typo.png` | identity | REJECTED | 52.9 | `font_layout(1.00)` | Identity: aadhaar_number_typo (png) |
| 23 | `identity/aadhaar_locked.pdf` | edge | REVIEW | 60.0 | `pades_signature[ERR]` | Locked/encrypted Aadhaar |
| 24 | `edge/corrupt.pdf` | edge | REVIEW | 60.0 | `pades_signature[ERR]` | Edge: Corrupt PDF body |
| 25 | `edge/empty.pdf` | edge | ERROR | N/A | `` | Edge: Empty file |
| 26 | `edge/wrong_extension.pdf` | edge | REVIEW | 60.0 | `` | Edge: PNG as PDF |
| 27 | `edge/truncated.pdf` | edge | REVIEW | 60.0 | `pades_signature[ERR]` | Edge: Truncated PDF |
