# Medical coding: WHO ICD-10 auto-coding for Indian discharge summaries

| Path | What |
|---|---|
| `docs/ICD10_Coding_Approach.pdf` | 2-page approach: multi-agent L1/L2/L3 coding with beam routing |
| `docs/make_approach_pdf.py` | Regenerates the PDF (`pip install reportlab`, then `python3 docs/make_approach_pdf.py docs/ICD10_Coding_Approach.pdf`) |
| `docs/WHO_ICD10_Data_Structure.md` | How the WHO data is parsed and structured, every output field, and the commands to rebuild and verify it |
| `data/who-icd10/` | WHO ICD-10 2019 knowledge base, plus the script that downloads and builds it. See its README |

Rebuild the knowledge base from scratch (standard-library Python, about 10 s):

```bash
python3 data/who-icd10/prepare_who_icd10.py --force
```
