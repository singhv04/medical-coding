# WHO ICD-10 (2019) knowledge base

The code set for the Indian discharge-summary coder. One script downloads the official WHO
release, parses it, validates it and builds the files the L1/L2/L3 coding agents query.

```bash
python3 prepare_who_icd10.py          # full run, stdlib only, ~10 s
python3 prepare_who_icd10.py --force  # also re-download the WHO zips
```

| Step | What happens |
|---|---|
| 1. download | Fetches 2 zips from WHO's public download page <https://icdcdn.who.int/icd10/index.html> (no login) into `raw/`, and records the SHA-256 of each |
| 2. extract | `claml/icd102019en.xml` (9.6 MB ClaML XML) and `meta/*.txt` (flat code tables) |
| 3. parse | Reads the ClaML tree and every rubric, and expands modifier-derived codes (see below) |
| 4. validate | 9 hard checks: 22 chapters, all 10,636 billable codes present, parents exist, billable = leaf, **every piece of ClaML text present in the output**, optional subdivisions attached. Stops if any check fails |
| 5. build | `out/` → JSONL nodes, JSONL subdivision tables, CSV edges, SQLite with full-text search, `manifest.json` |

Full field-by-field reference: [`docs/WHO_ICD10_Data_Structure.md`](../../docs/WHO_ICD10_Data_Structure.md).

`raw/`, `claml/`, `meta/` and `out/` are generated and git-ignored. Rerun the script to rebuild them.

**Release:** ICD-10 2019 version incl. COVID-19 updates (`version="2019-covid-expanded"`, dated
2020-03-22). This is the last WHO ICD-10 release; WHO's newer work goes into ICD-11.

---

## How the WHO XML (ClaML) is organised

ClaML (Classification Markup Language, ISO 13120:2013) is WHO's XML format for classifications.
The file has a small header and three kinds of element:

```xml
<ClaML version="2.0.0">
  <Title version="2019-covid-expanded" date="2020-03-22">International Statistical Classification ...</Title>
  <ClassKinds> chapter | block | category </ClassKinds>
  <UsageKinds> dagger (+) | aster (*) </UsageKinds>
  <RubricKinds> preferred, preferredLong, inclusion, exclusion, note, coding-hint, definition, text, ... </RubricKinds>

  <Modifier .../>        46 shared subdivision tables, e.g. "4th characters for E10-E14"
  <ModifierClass .../>   243 entries in those tables, e.g. ".5 With peripheral circulatory complications"
  <Class .../>           22 chapters, 274 blocks, 11,243 categories/subcategories
</ClaML>
```

### 1. `Class`: the tree (your L1 → L2 → L3)

```xml
<Class code="IV" kind="chapter">                 <!-- L1: chapter (Roman numeral) -->
  <SubClass code="E10-E14"/> ...
  <Rubric kind="preferred"><Label>Endocrine, nutritional and metabolic diseases</Label></Rubric>
  <Rubric kind="note">All neoplasms ... are classified in Chapter II ...</Rubric>
  <Rubric kind="exclusion"><Label>complications of pregnancy ...<Reference code="O00">O00-O99</Reference></Label></Rubric>
</Class>

<Class code="E10-E14" kind="block">              <!-- L2a: block -->
  <SuperClass code="IV"/>
  <Rubric kind="coding-hint">Use additional external cause code (Chapter XX), if desired, to identify drug ...</Rubric>
</Class>

<Class code="E11" kind="category">               <!-- L2b: 3-character category -->
  <SuperClass code="E10-E14"/>
  <ModifiedBy code="S04E10_4"/>                   <!-- its 4th characters come from a shared table -->
  <Rubric kind="preferred">Type 2 diabetes mellitus</Rubric>
  <Rubric kind="inclusion"><Fragment type="list">diabetes (mellitus)(nonobese)(obese):</Fragment>
                           <Fragment type="list">maturity-onset</Fragment></Rubric>
  <Rubric kind="exclusion">... malnutrition-related <Reference>E12.-</Reference></Rubric>
  <Meta name="MortL1Code" value="1-052"/>         <!-- WHO mortality tabulation lists -->
</Class>
```

* `SuperClass` / `SubClass` give the parent/child links. Walking down them is exactly the L1 → L2 → L3 route.
* Each `Rubric` is one piece of the class. `kind` says which:

| Rubric kind | Count | What it means for the coding agent |
|---|---|---|
| `preferred` | 11,782 | Official title |
| `preferredLong` | 797 | Longer title, where the short one is abbreviated |
| `inclusion` | 9,724 | **Other wording that belongs here.** Bridges to doctor language (e.g. "Diabetic: ulcer" under E1x.5) |
| `exclusion` | 4,813 | **Not here: go to the referenced code.** Becomes routing and pruning edges |
| `coding-hint` | 232 | "Use additional code ..." style instructions |
| `note` / `text` / `introduction` | 280 | Chapter and block rules, e.g. the neoplasm note in Chapter IV |
| `definition` | 276 | Definitions, mostly in Chapter V (mental disorders) |
| `modifierlink` | 182 | Pointer to the shared 4th/5th-character table |

* A `Label` is mixed content. `Fragment type="list"` items form a two-part phrase
  ("Diabetic:" + "ulcer" → "Diabetic: ulcer"), and `Reference` marks a cross-reference to another code.

### 2. `Modifier` / `ModifierClass`: codes that are not written out

In WHO ICD-10, many 4th and 5th characters are defined once and shared, so **E11.5 never appears as
a `<Class>`**. It is E11 + the `.5` entry of modifier `S04E10_4`:

```xml
<ModifierClass code=".5" modifier="S04E10_4">
  <Rubric kind="preferred">With peripheral circulatory complications</Rubric>
  <Rubric kind="inclusion">Diabetic: gangrene</Rubric>
  <Rubric kind="inclusion">Diabetic: peripheral angiopathy <Reference usage="aster">I79.2</Reference></Rubric>
  <Rubric kind="inclusion">Diabetic: ulcer</Rubric>
</ModifierClass>
```

`ModifiedBy all="true"` means the table also applies to all descendants, and `ExcludeModifier` turns
it off for a subtree. 1,058 of the 10,636 billable codes are produced this way. The script expands
only the combinations that WHO's own `meta/…codes.txt` lists as valid, and validation confirms
every one of them was matched.

28 of the 46 tables are WHO's *optional supplementary* characters (J96 Type I/II respiratory failure,
fracture closed/open, musculoskeletal site, place of occurrence). WHO lists none of them as valid
codes, so they are not expanded. They are kept whole in `out/icd10_who_2019_modifiers.jsonl` and
referenced from each billable code they qualify (`optional_subdivisions`, e.g. J96.1 → `J96_5`).
Table heading text, which sometimes carries rules such as "a fracture not indicated as closed or
open should be classified as closed", goes into `subdivision_notes` on the declaring class.

U10.9, U11.9 and U12.9 (COVID-19 MIS-C, vaccination, vaccine adverse effects) are in the XML but not
in the older meta table; the script marks them billable. The `Uxx` "Emergency use" placeholders stay
non-billable.

### 3. Dagger (†) and asterisk (*): WHO's paired codes

WHO ICD-10 uses two codes for "disease X causing manifestation Y":

```xml
<Class code="G63.2" kind="category" usage="aster">          <!-- * manifestation, never coded alone -->
  <Rubric kind="preferred">Diabetic polyneuropathy
     <Reference usage="dagger">E10-E14 with common fourth character .4</Reference></Rubric>
</Class>
```

This is the WHO equivalent of ICD-10-CM's *Code First / Use Additional*. The rule for the
validator is: an asterisk code (373 of them) is never the principal diagnosis, and it must be paired
with its dagger code (here E11.4 + G63.2).

### 4. The `meta/` text files

These are flat tables (`;`-separated, Latin-1). `icd102019syst_codes.txt` has one row per code:
level (3/4/5), **T = terminal (billable) / N = not billable**, X = written out vs S = derived from a
modifier, chapter, block, code, title and mortality lists. WHO notes these files *are not enough for
coding on their own* because they leave out inclusions and exclusions. The script uses them only as
the authoritative list of valid codes.

---

## Output files (`out/`)

**`icd10_who_2019_nodes.jsonl`** has one record per chapter, block or code (12,597 in total):

```json
{"code": "E11.5", "kind": "category", "level": 4,
 "title": "Type 2 diabetes mellitus: With peripheral circulatory complications",
 "parent": "E11", "path": ["IV", "E10-E14", "E11"], "chapter": "IV", "children": [],
 "billable": true, "dagger_asterisk": null,
 "inclusions": ["Diabetic: gangrene", "Diabetic: peripheral angiopathy (I79.2)", "Diabetic: ulcer"],
 "exclusions": [], "notes": [], "coding_hints": [], "pairs_with": ["I79.2"],
 "subdivision_notes": [], "optional_subdivisions": [],
 "modifier_source": "S04E10_4", "mortality_lists": {"MortL1Code": "1-052", "...": "..."}}
```

**`icd10_who_2019_modifiers.jsonl`** has one record per shared subdivision table (46), with its
heading text, where it is declared or excluded, and every entry (title, inclusions, exclusions).

**`icd10_who_2019_edges.csv`** holds the graph the agents walk and the validator enforces:

| type | count | use |
|---|---|---|
| `child_of` | 12,575 | L1 → L2 → L3 tree walk |
| `excludes` | 4,980 | Re-route ("not here, try X") and prune conflicting beams |
| `dagger_pairs_with_asterisk` | 304 | Add the companion * code |
| `asterisk_needs_dagger` | 114 | Never code this * alone |

**`icd10_who_2019.sqlite`** has the same data (tables `nodes`, `edges`, `modifiers`), plus an FTS5
`search` table over titles, inclusion terms, parent titles and optional subdivision terms. This is
the retrieval tool the agents call:

```sql
-- "non-healing ulcer, k/c/o DM2" → candidate leaves (the hit comes from the inclusion term, not the title)
SELECT n.code, n.title FROM search s JOIN nodes n USING(code)
WHERE search MATCH 'diabetic AND ulcer' AND n.billable = 1;      -- E10.5 ... E14.5

-- children of a node chosen at the previous level
SELECT code, title, billable FROM nodes WHERE parent = 'E11';
```

**`manifest.json`** records the source URLs, SHA-256 of every input and output, counts and
validation results. Use it for audits and to detect changes between releases.

## Limits to know

* **There is no Alphabetic Index (Volume 3) in this release.** The doctor-language bridge here is the
  inclusion terms only. The extractor/normaliser agents still need an Indian abbreviation and brand-drug
  lexicon, plus a synonym layer. The ICD-11 Coding Tool/API (free registration) has a large index with
  ICD-11 → ICD-10 mappings that could feed that layer.
* **WHO ICD-10 is coarser than ICD-10-CM.** It has 10.6k billable codes (vs ~74k) and no laterality or 7th
  character. For example, a diabetic foot ulcer is simply **E11.5** (CM: E11.621 + L97.4xx).
* **Licence:** the files are © WHO. Before commercial use, check WHO's ICD licensing terms
  (<https://www.who.int/about/policies/publishing/copyright>) and payer requirements (NHA/PM-JAY, IRDAI).
