# WHO ICD-10 (2019) knowledge base: data structure and approach

How the WHO ICD-10 release is downloaded, parsed and turned into the files the coding agents query,
what every output field means, and the commands to rebuild and verify it from scratch.

| | |
|---|---|
| **Source** | WHO public download page, <https://icdcdn.who.int/icd10/index.html> (no login) |
| **Release** | "ICD-10 2019 version (including COVID-19 updates)", ClaML `version="2019-covid-expanded"`, dated 2020-03-22 |
| **Builder** | [`data/who-icd10/prepare_who_icd10.py`](../data/who-icd10/prepare_who_icd10.py), Python standard library only, about 10 s |
| **Outputs** | `data/who-icd10/out/`: nodes JSONL, modifiers JSONL, edges CSV, SQLite with FTS5 search, `manifest.json` |
| **Size** | 12,597 nodes (22 chapters, 274 blocks, 12,301 categories), of which **10,636 are billable**; 46 subdivision tables |
| **Completeness** | Every piece of text in the WHO XML is checked to be present in the output on every build (section 10) |

---

## Contents

1. [Approach in one page](#1-approach-in-one-page)
2. [Recreate the data from scratch](#2-recreate-the-data-from-scratch)
3. [Source files and what they contain](#3-source-files-and-what-they-contain)
4. [Parsing rules (ClaML to nodes)](#4-parsing-rules-claml-to-nodes)
5. [Output: `icd10_who_2019_nodes.jsonl`](#5-output-icd10_who_2019_nodesjsonl)
6. [Output: `icd10_who_2019_modifiers.jsonl`](#6-output-icd10_who_2019_modifiersjsonl)
7. [Output: `icd10_who_2019_edges.csv`](#7-output-icd10_who_2019_edgescsv)
8. [Output: `icd10_who_2019.sqlite`](#8-output-icd10_who_2019sqlite)
9. [Output: `manifest.json`](#9-output-manifestjson)
10. [Validation checks](#10-validation-checks)
11. [How the agents use the data](#11-how-the-agents-use-the-data)
12. [Known quirks and limits](#12-known-quirks-and-limits)

---

## 1. Approach in one page

**Why WHO ICD-10 and not ICD-10-CM.** Indian payers (NHA/PM-JAY, IRDAI) use WHO ICD-10. It is
coarser than ICD-10-CM: codes have at most 4 or 5 characters, there is no laterality and no 7th
character, and "Code First / Use Additional" is written as dagger (†) / asterisk (*) pairs.

**Why the official files and not scraping the website.** WHO publishes the full classification as a
downloadable ClaML XML file, which is the machine-readable form of the content shown in the online
browser. The XML labels every piece of text by its role (`kind="exclusion"`, `usage="dagger"`) and
links shared subdivision tables to the codes they apply to. A scraper would have to infer the same
structure from page layout, needs a headless browser for thousands of pages, breaks when the site
changes, and still ends in a parser. So the "scrape" is a download of two official zips, followed by
a structured parse whose completeness is checked against the source on every build.

**Coding is a walk down a graph.** The output is built for a hierarchical, multi-agent coder:

| Level | Node kind | Example | Agent |
|---|---|---|---|
| L1 | `chapter` (Roman numeral) | `IV` Endocrine, nutritional and metabolic diseases | Chapter router |
| L2a | `block` (code range) | `E10-E14` Diabetes mellitus | Category agent |
| L2b | 3-character `category` | `E11` Type 2 diabetes mellitus | Category agent |
| L3 | 4- or 5-character `category` (billable leaf) | `E11.5` ... With peripheral circulatory complications | 4th-character agent |

Besides the tree, the rules in the XML are turned into edges the agents and the validator follow:
exclusions ("not here, go to X") and dagger/asterisk pairings. WHO's optional supplementary
characters (J96 Type I/II, fracture open/closed, musculoskeletal site) are attached to the codes they
qualify, without turning them into codes WHO does not list as valid.

**Pipeline (one script, five steps):**

| Step | Input | Output | Notes |
|---|---|---|---|
| 1. download | WHO URLs | `raw/*.zip` | Skipped if the zips already exist, unless `--force`. SHA-256 recorded |
| 2. extract | `raw/*.zip` | `claml/icd102019en.xml`, `meta/*.txt` | Rejects zip entries that would escape the target folder |
| 3. parse | ClaML XML + `meta/…codes.txt` | In-memory nodes and subdivision tables | Flattens rubrics, expands modifier-derived codes, attaches optional subdivisions |
| 4. validate | Nodes + tables + the XML again | Pass/fail report | Any hard-check failure stops the run before writing outputs |
| 5. build | Nodes + tables + report | `out/` files | JSONL, CSV, SQLite (with FTS5), manifest |

---

## 2. Recreate the data from scratch

### 2.1 Prerequisites

| Requirement | Check | Notes |
|---|---|---|
| Python 3.9+ | `python3 --version` | Tested with 3.13. Standard library only, no `pip install` |
| SQLite with FTS5 | `python3 -c "import sqlite3; sqlite3.connect(':memory:').execute('create virtual table t using fts5(x)'); print('fts5 ok')"` | Bundled with python.org and Homebrew builds |
| Internet access to `icdcdn.who.int` | `curl -sI https://icdcdn.who.int/icd10/claml/icd102019en.xml.zip \| head -1` | Only needed for step 1 |
| Optional: `sqlite3` CLI, `jq` | `sqlite3 --version`, `jq --version` | Only for the inspection commands below |

### 2.2 Full rebuild (recommended)

Run from the repository root:

```bash
# Wipe every generated folder so nothing stale survives
rm -rf data/who-icd10/raw data/who-icd10/claml data/who-icd10/meta data/who-icd10/out

# Download, extract, parse, validate and build (about 10 s)
python3 data/who-icd10/prepare_who_icd10.py --force
```

Use `--force` to re-download the zips even if `raw/` already holds them. Without it, the script
reuses the existing zips and only rebuilds the rest:

```bash
python3 data/who-icd10/prepare_who_icd10.py
```

A successful run prints nine `PASS` lines and ends like this:

```text
[validate] PASS  22 chapters
[validate] PASS  blocks present
[validate] PASS  billable codes present
[validate] PASS  every meta billable code parsed
[validate] PASS  every derived code matched a modifier
[validate] PASS  every parent exists
[validate] PASS  billable codes are leaves
[validate] PASS  every ClaML text present in output
[validate] PASS  every optional table attached to a billable code
[validate] info  optional tables not attached to codes (WHO ExcludeModifier): ['S20W00_4', 'S20V01T_5']
[validate] info  billable but not in meta table: ['U10.9', 'U11.9', 'U12.9']
...
[done] 10636 billable WHO ICD-10 codes ready in out/
```

If any check prints `FAIL`, the script exits with a non-zero status and writes nothing to `out/`.

### 2.3 Manual download (if you only want the raw WHO files)

These are the exact steps 1 and 2 of the script, done by hand. On the WHO page they are the
**ClaML** and **Meta** downloads under "ICD-10 2019 version (including COVID-19 updates)".

```bash
cd data/who-icd10
mkdir -p raw claml meta

curl -fL -o raw/icd102019en.xml.zip     https://icdcdn.who.int/icd10/claml/icd102019en.xml.zip
curl -fL -o raw/icd102019enMeta.zip     https://icdcdn.who.int/icd10/meta/icd102019enMeta.zip

unzip -o raw/icd102019en.xml.zip  -d claml/
unzip -o raw/icd102019enMeta.zip  -d meta/
```

Check that the downloads match the ones this knowledge base was built from:

```bash
shasum -a 256 raw/*.zip
# 344c571aa9aed3b9ad1c80261b7828c45cfb5fc0b1a5da64aecef354dff5b3d9  raw/icd102019en.xml.zip
# a9fa787fa79076e199e46ca645bbc076449853e93e62cd3b2050b96dc96bbc1d  raw/icd102019enMeta.zip

shasum -a 256 claml/icd102019en.xml
# 00ca1cc9daa71857258beeae2f835088a1ede0c1da250380079f859b85c689bd  claml/icd102019en.xml
```

If the hashes differ, WHO has republished the files. Rebuild, then compare the `counts` in the new
`manifest.json` against section 9 before trusting the result.

### 2.4 Verify a build

```bash
cd data/who-icd10/out

# All nine hard checks should be true
jq '.checks' manifest.json

# Headline counts: expect 22 chapters, 274 blocks, 12301 categories, 10636 billable
jq '.counts | {chapter, block, category, billable}' manifest.json

# Output files match what the manifest recorded
jq -r '.outputs | to_entries[] | "\(.value.sha256)  \(.key)"' manifest.json | shasum -a 256 -c -

# One line per node, one line per subdivision table
wc -l icd10_who_2019_nodes.jsonl icd10_who_2019_modifiers.jsonl     # 12597, 46

# Billable count straight from SQLite
sqlite3 icd10_who_2019.sqlite "SELECT COUNT(*) FROM nodes WHERE billable = 1;"   # 10636
```

The output hashes only match a build made from the same input zips. `generated_at` changes on every
run, but it lives in `manifest.json`, which is not itself hashed.

---

## 3. Source files and what they contain

On the WHO download page the release is listed as **"ICD-10 2019 version (including COVID-19
updates)"**. It offers two downloads, and the script fetches both:

| Download on the WHO page | Zip | Contents | Extracted to |
|---|---|---|---|
| ClaML (XML) | `icd102019en.xml.zip` | `icd102019en.xml` (single file) | `claml/` |
| Meta files | `icd102019enMeta.zip` | 3 `.txt` files, no folder inside the zip | `meta/` |

Unzipping `icd102019enMeta.zip` by hand (for example in Finder) creates a folder called
`icd102019enMeta/`. That is only the unzip tool naming a folder after the zip. The script puts the
same three files in `meta/`. A manual download and the script's download are byte-for-byte identical.

After extraction the folder looks like this. Everything except the script, README and `.gitignore`
is generated and git-ignored.

```text
data/who-icd10/
├── prepare_who_icd10.py          builder script
├── README.md                     short guide
├── raw/
│   ├── icd102019en.xml.zip       672 KB  ClaML zip
│   └── icd102019enMeta.zip       237 KB  flat tables zip
├── claml/
│   └── icd102019en.xml           9.6 MB  the full classification (tree + every rule)
├── meta/
│   ├── icd102019syst_chapters.txt
│   ├── icd102019syst_groups.txt
│   └── icd102019syst_codes.txt   list of valid codes
└── out/
    ├── icd10_who_2019_nodes.jsonl       8.8 MB  one record per chapter, block, code
    ├── icd10_who_2019_modifiers.jsonl   74 KB   one record per shared subdivision table
    ├── icd10_who_2019_edges.csv         0.6 MB  tree, exclusion and dagger/asterisk links
    ├── icd10_who_2019.sqlite           18.2 MB  all of the above + full-text search
    └── manifest.json                            hashes, counts, check results
```

### 3.1 The ClaML XML (`claml/icd102019en.xml`)

ClaML (Classification Markup Language, ISO 13120:2013) is WHO's XML format for classifications.
The file has a header and three kinds of element:

```xml
<ClaML version="2.0.0">
  <Title version="2019-covid-expanded" date="2020-03-22">International Statistical Classification ...</Title>
  <ClassKinds>   chapter | block | category </ClassKinds>
  <UsageKinds>   dagger | aster </UsageKinds>
  <RubricKinds>  preferred, preferredLong, inclusion, exclusion, note, coding-hint, definition, text, ... </RubricKinds>

  <Modifier .../>        46 shared subdivision tables, e.g. "4th characters for E10-E14"
  <ModifierClass .../>   243 entries in those tables, e.g. ".5 With peripheral circulatory complications"
  <Class .../>           22 chapters, 274 blocks, 11,243 written-out categories
</ClaML>
```

**`Class`** is one node in the tree:

```xml
<Class code="E11" kind="category">
  <SuperClass code="E10-E14"/>                     <!-- parent -->
  <SubClass code="E11.0"/> ...                     <!-- children (when written out) -->
  <ModifiedBy code="S04E10_4"/>                    <!-- 4th characters come from a shared table -->
  <Rubric kind="preferred"><Label>Type 2 diabetes mellitus</Label></Rubric>
  <Rubric kind="inclusion"><Label>
      <Fragment type="list">diabetes (mellitus)(nonobese)(obese):</Fragment>
      <Fragment type="list">maturity-onset</Fragment></Label></Rubric>
  <Rubric kind="exclusion"><Label>... malnutrition-related <Reference>E12.-</Reference></Label></Rubric>
  <Meta name="MortL1Code" value="1-052"/>          <!-- WHO mortality tabulation lists -->
</Class>
```

**`Rubric`** is one piece of text attached to a class, a table or a table entry. Its `kind` decides
where it goes:

| Rubric kind | Count in XML | Stored in field | Meaning for the coder |
|---|---|---|---|
| `preferred` | 11,782 | `title` | Official title |
| `preferredLong` | 797 | `title_long` | Longer title where the short one is abbreviated |
| `inclusion` | 9,724 | `inclusions` | Other wording that belongs here; the main bridge to doctor language |
| `exclusion` | 4,813 | `exclusions` | "Not here, go to the referenced code" |
| `coding-hint` | 232 | `coding_hints` | "Use additional code ..." instructions |
| `note`, `text`, `introduction`, `footnote` | 124 + 147 + 9 + 1 | `notes` | Chapter, block and table rules |
| `definition` | 276 | `definitions` | Definitions, mostly Chapter V (mental disorders) |
| `modifierlink` | 182 | not stored | Pointer such as "[See before E10 for subdivisions]"; the expansion applies the table itself |

**`Label`** is mixed content. The child elements that matter:

* `Fragment type="list"`: parts of a two-part phrase. `"Diabetic:"` + `"ulcer"` reads `"Diabetic: ulcer"`.
* `Reference`: a cross-reference to another code. It may carry `usage="dagger"` or `usage="aster"`.
* `Para`, `List`/`ListItem`, `Table`/`Row`/`Cell`: paragraphs, bullet lists and tables inside notes,
  definitions and hints (for example the visual-impairment table at H54.9).
* `Term`: styling (bold, italic, subscript as in "B<sub>12</sub>", tab spacing).

**`Modifier` / `ModifierClass`** hold the 46 shared 4th/5th-character tables. Each table has a short
heading text, and each entry has its own title, inclusions and exclusions. E11.5 is never written as a
`<Class>`. It is E11 plus entry `.5` of table `S04E10_4`:

```xml
<Modifier code="S04E10_4">
  <Rubric kind="text"><Label>The following fourth-character subdivisions are for use with categories E10-E14:</Label></Rubric>
</Modifier>
<ModifierClass code=".5" modifier="S04E10_4">
  <Rubric kind="preferred"><Label>With peripheral circulatory complications</Label></Rubric>
  <Rubric kind="inclusion"><Label>Diabetic: gangrene</Label></Rubric>
  <Rubric kind="inclusion"><Label>Diabetic: peripheral angiopathy <Reference usage="aster">I79.2</Reference></Label></Rubric>
  <Rubric kind="inclusion"><Label>Diabetic: ulcer</Label></Rubric>
</ModifierClass>
```

`ModifiedBy` on a class declares that a table applies; `all="true"` extends it to all descendants.
`ExcludeModifier` switches a table off for a subtree.

Tables fall into two groups:

| Group | Tables | Example | How the script uses them |
|---|---|---|---|
| **Expanded** | 18 | `S04E10_4` (E10-E14 complications), `S01B18_5` (hepatitis B phases) | Entries become real codes (E11.5, B18.00), because WHO lists those codes as valid |
| **Optional supplementary** | 28 | `J96_5` Type I/II respiratory failure, `S19S72_5` fracture closed/open, `S13M40_5` spinal site | WHO lists none of these as valid codes. Kept as tables and attached to the codes they qualify (section 4.4) |

**Dagger / asterisk.** `usage="aster"` on a class marks a manifestation code that is never coded
alone or as the main condition. Its title holds a `Reference usage="dagger"` to the cause:

```xml
<Class code="G63.2" kind="category" usage="aster">
  <Rubric kind="preferred"><Label>Diabetic polyneuropathy
     <Reference usage="dagger">E10-E14 with common fourth character .4</Reference></Label></Rubric>
</Class>
```

### 3.2 The meta tables (`meta/*.txt`)

Flat, `;`-separated, **Latin-1 encoded**, no header row.

**`icd102019syst_codes.txt`**: one row per code (3, 4 and 5 characters).

```text
4;T;S;04;E10;E11.5;E11.5;E115;Type 2 diabetes mellitus: With peripheral circulatory complications;Type 2 diabetes mellitus;With peripheral circulatory complications;;104;4-044;3-025;2-046;1-052
```

| Column (0-based) | Example | Meaning | Used by script |
|---|---|---|---|
| 0 | `4` | Level: 3, 4 or 5 characters | yes (`level`) |
| 1 | `T` | `T` = terminal (billable), `N` = not billable | yes (`billable`) |
| 2 | `S` | `X` = written out as a `<Class>`, `S` = derived from a modifier | yes (drives expansion) |
| 3 | `04` | Chapter number | no |
| 4 | `E10` | First code of the block | no |
| 5 | `E11.5` | Code, with `-` placeholder for 3-character codes that have children (`A00.-`) | no |
| 6 | `E11.5` | Code, plain form | yes (key) |
| 7 | `E115` | Code without the dot | no |
| 8 | ... | Full title (for 796 codes the ClaML `preferredLong`, stored as `title_long`) | no |
| 9-11 | ... | 3-, 4- and 5-character titles | no |
| 12-16 | `104;4-044;...` | Mortality and morbidity tabulation list codes | no (taken from ClaML `Meta`) |

**`icd102019syst_chapters.txt`**: `chapter_number;title` (e.g. `04;Endocrine, nutritional and metabolic diseases`).

**`icd102019syst_groups.txt`**: `first_code;last_code;chapter_number;title` (e.g. `E10;E14;04;Diabetes mellitus`).

WHO notes the meta tables are not enough for coding because they leave out inclusions and
exclusions. The script uses `syst_codes.txt` only as the list of valid and billable codes. Everything
else comes from the ClaML. The meta files were published in October 2020, before the XML was last
updated, so a few newer codes are missing from them (section 4.5).

---

## 4. Parsing rules (ClaML to nodes)

### 4.1 Label flattening

Every `Label` becomes a single string:

1. Paragraphs (`Para`), lists and tables become separate lines. A list item becomes `- item`; a table
   row becomes `cell | cell | cell`.
2. Within a line, whitespace is collapsed to single spaces. A tab `Term` becomes a space; other
   styling (bold, italic, subscript) is dropped, keeping its text (`B12`).
3. If the label has `Fragment` children, the fragments are joined with a space (`"Diabetic: ulcer"`).
4. A `Reference` is written as ` (CODE)` after the text, so `"... malnutrition-related (E12.-)"`.
   Titles are the exception: references are left out of `title`, and kept separately in `title_refs`.
5. The references in a label are also kept as structured objects: `{"text", "code", "usage"}`.
   `text` is what WHO wrote (`E12.-`, `O00-O99`), `code` is the `code` attribute if present (`O00`),
   otherwise the same as `text`.

### 4.2 Modifier expansion (derived codes)

1,058 billable codes (for example the whole E10.0 to E14.9 grid) are not `<Class>` elements. For
every row in `syst_codes.txt` marked `S` that is not already a class, the script:

1. Finds the **base class** by trimming the code until it matches an existing class
   (`E11.5` → `E11`; `B18.00` → `B18.0`).
2. Collects the **applicable modifier tables**: the base's own `ModifiedBy`, plus any ancestor
   `ModifiedBy all="true"`, minus every `ExcludeModifier` on the base or its ancestors.
3. Picks the table whose name ends in `_4` for a 4-character code (`_5` otherwise) and looks up the
   suffix (`.5`, or the last digit).
4. Creates the node:
   * `title` = base title + `": "` + modifier entry title
   * `inclusions`, `exclusions`, `notes`, `coding_hints`, `definitions` from the modifier entry
   * `mortality_lists` copied from the base
   * `modifier_source` = the table name (`S04E10_4`)
   * appended to the base's `children`

Only codes WHO lists as valid are created. A code that matches no table makes validation fail.

### 4.3 Table heading text (`subdivision_notes`)

Each table's heading text is copied onto every class that declares the table with `ModifiedBy`. This
carries rules that apply when choosing the subdivision, for example:

* O03-O06: "Incomplete abortion includes retained products of conception following abortion."
* S72 (and the other fracture categories): "a fracture not indicated as closed or open should be
  classified as closed."

217 nodes have `subdivision_notes`.

### 4.4 Optional supplementary subdivisions (`optional_subdivisions`)

A table is **optional** when none of its entries became a code in 4.2. For every billable code, the
script lists the optional tables declared on the code itself or any ancestor, minus tables switched
off by `ExcludeModifier` anywhere on that path. The `all` flag is ignored here, because WHO declares
several of these tables on a 3-character category without it while meaning them for the codes
underneath (J96 → J96.0, J96.1, J96.9).

536 billable codes get at least one optional table, for example:

| Code | `optional_subdivisions` | Meaning |
|---|---|---|
| `J96.1` Chronic respiratory failure | `["J96_5"]` | 5th character 0 Type I (hypoxic), 1 Type II (hypercapnic), 9 unspecified |
| `S72.0` Fracture of neck of femur | `["S19S72_5"]` | 0 closed, 1 open |
| `S06.0` Concussion | `["S19S06_5"]` | 0 without, 1 with open intracranial wound |
| `M54.5` Low back pain | `["S13M40_5"]` | Site in the spine |
| `I70.2` Atherosclerosis of arteries of extremities | `["I70M10_4"]` | 0 without, 1 with gangrene |

Two optional tables are attached to no code: `S20W00_4` (place of occurrence) and `S20V01T_5`
(activity). WHO switches them off with `ExcludeModifier` on every subtree where they are declared,
because they are recorded as separate variables next to an external-cause code, not as an extra
character. They are complete in the modifiers file, and their heading text is in the
`subdivision_notes` of the external-cause blocks that declare them.

The entries themselves are stored once, in the modifiers file (section 6), and nodes refer to them by
table code.

### 4.5 Billable status

| Rule | Codes |
|---|---|
| Code is in `syst_codes.txt`: billable if marked `T` | 10,633 |
| Code is not in `syst_codes.txt`, is a leaf category, and is not a placeholder: billable | 3: `U10.9` MIS-C associated with COVID-19, `U11.9` Need for immunization against COVID-19, `U12.9` COVID-19 vaccines causing adverse effects |
| Placeholders `U13`-`U49` ("Emergency use of Uxx"): not billable | — |

The second rule exists because WHO added U10-U12 to the XML after the meta files were published. The
manifest lists these codes under `counts.billable_not_in_meta`.

### 4.6 Derived fields

| Field | Rule |
|---|---|
| `level` | `0` chapter, `1` block, otherwise number of characters without the dot (3, 4 or 5) |
| `path` | Ancestors from the chapter down to the parent (the node itself is not included) |
| `chapter` | First element of `path`, or the node's own code for a chapter |
| `billable` | See 4.5 |
| `dagger_asterisk` | `"dagger"` / `"asterisk"` from the class `usage` attribute, else `null` |
| `pairs_with` | Codes referenced with `usage="aster"` inside the node's inclusions (dagger → asterisk) |
| `subdivision_notes` | See 4.3 |
| `optional_subdivisions` | See 4.4 |

---

## 5. Output: `icd10_who_2019_nodes.jsonl`

One JSON object per line, one line per chapter, block or code. 12,597 lines, UTF-8.

### 5.1 Field reference

| Field | Type | Example | Notes |
|---|---|---|---|
| `code` | string | `"E11.5"` | Chapter: Roman numeral (`"IV"`). Block: range (`"E10-E14"`). Category: code |
| `kind` | string | `"category"` | `chapter`, `block` or `category` |
| `level` | int | `4` | See 4.6 |
| `title` | string | `"Type 2 diabetes mellitus: With peripheral circulatory complications"` | |
| `title_long` | string or null | `null` | Set for 797 nodes |
| `parent` | string or null | `"E11"` | `null` only for chapters |
| `path` | string[] | `["IV", "E10-E14", "E11"]` | Ancestors, chapter first |
| `chapter` | string | `"IV"` | |
| `children` | string[] | `[]` | Empty for leaves |
| `billable` | bool | `true` | Only leaves can be billable |
| `dagger_asterisk` | string or null | `null` | `"dagger"` (81 nodes) or `"asterisk"` (373 nodes) |
| `inclusions` | string[] | `["Diabetic: gangrene", "Diabetic: ulcer", ...]` | Flattened text, references inline |
| `exclusions` | object[] | `[{"text": "...", "refs": [{"text": "E12.-", "code": "E12", "usage": null}]}]` | Structured, so the target code can be routed to |
| `notes` | string[] | | `note`, `text`, `introduction`, `footnote` rubrics. May contain line breaks |
| `coding_hints` | string[] | `["Use additional external cause code (Chapter XX) ..."]` | May contain line breaks and table rows |
| `definitions` | string[] | | 348 nodes have at least one |
| `subdivision_notes` | string[] | `["... a fracture not indicated as closed or open should be classified as closed."]` | Heading text of tables this class declares (4.3) |
| `optional_subdivisions` | string[] | `["J96_5"]` | Optional table codes for this billable code (4.4); look up in the modifiers file |
| `title_refs` | object[] | `[{"text": "E10-E14 with common fourth character .4", "code": "E10", "usage": "dagger"}]` | References removed from `title` |
| `pairs_with` | string[] | `["I79.2"]` | Asterisk codes this code pairs with |
| `modifier_source` | string or null | `"S04E10_4"` | Set only on the 1,058 derived codes |
| `mortality_lists` | object or null | `{"MortL1Code": "1-052", "MortBCode": "104", ...}` | WHO tabulation lists |

### 5.2 Distribution

| `kind` | `level` | Nodes | Billable |
|---|---|---|---|
| chapter | 0 | 22 | 0 |
| block | 1 | 274 | 0 |
| category | 3 | 2,090 | 464 (3-character codes with no subdivision, e.g. `A64`) |
| category | 4 | 10,207 | 10,168 |
| category | 5 | 4 | 4 |
| **total** | | **12,597** | **10,636** |

The 39 non-billable 4-character nodes are either parents of 5-character codes or the `Uxx.9`
"Emergency use" placeholders.

### 5.3 Examples (real records, trimmed)

A chapter:

```json
{"code": "IV", "kind": "chapter", "level": 0,
 "title": "Endocrine, nutritional and metabolic diseases",
 "parent": null, "path": [], "chapter": "IV",
 "children": ["E00-E07", "E10-E14", "E15-E16", "E20-E35", "E40-E46", "E50-E64", "E65-E68", "E70-E90"],
 "billable": false,
 "exclusions": [{"text": "complications of pregnancy, childbirth and the puerperium (O00-O99)",
                 "refs": [{"text": "O00-O99", "code": "O00", "usage": null}]}, "..."],
 "notes": ["All neoplasms, whether functionally active or not, are classified in Chapter II. ..."]}
```

A block:

```json
{"code": "E10-E14", "kind": "block", "level": 1, "title": "Diabetes mellitus",
 "parent": "IV", "path": ["IV"], "chapter": "IV",
 "children": ["E10", "E11", "E12", "E13", "E14"], "billable": false,
 "coding_hints": ["Use additional external cause code (Chapter XX), if desired, to identify drug, if drug-induced."]}
```

A 3-character category that declares a subdivision table:

```json
{"code": "E11", "kind": "category", "level": 3, "title": "Type 2 diabetes mellitus",
 "children": ["E11.0", "E11.1", "...", "E11.9"], "billable": false,
 "subdivision_notes": ["The following fourth-character subdivisions are for use with categories E10-E14:"]}
```

A derived billable leaf:

```json
{"code": "E11.5", "kind": "category", "level": 4,
 "title": "Type 2 diabetes mellitus: With peripheral circulatory complications",
 "parent": "E11", "path": ["IV", "E10-E14", "E11"], "chapter": "IV", "children": [],
 "billable": true, "dagger_asterisk": null,
 "inclusions": ["Diabetic: gangrene", "Diabetic: peripheral angiopathy (I79.2)", "Diabetic: ulcer"],
 "subdivision_notes": [], "optional_subdivisions": [],
 "pairs_with": ["I79.2"], "modifier_source": "S04E10_4",
 "mortality_lists": {"MortBCode": "104", "MortL4Code": "4-044", "MortL3Code": "3-025",
                     "MortL2Code": "2-046", "MortL1Code": "1-052"}}
```

A billable leaf with an optional subdivision:

```json
{"code": "J96.1", "kind": "category", "level": 4, "title": "Chronic respiratory failure",
 "parent": "J96", "billable": true, "optional_subdivisions": ["J96_5"]}
```

An asterisk code:

```json
{"code": "G63.2", "kind": "category", "level": 4, "title": "Diabetic polyneuropathy",
 "parent": "G63", "path": ["VI", "G60-G64", "G63"], "chapter": "VI",
 "billable": true, "dagger_asterisk": "asterisk",
 "title_refs": [{"text": "E10-E14 with common fourth character .4", "code": "E10", "usage": "dagger"}]}
```

### 5.4 Handy commands

```bash
cd data/who-icd10/out

# One record, pretty-printed
grep '"code": "E11.5"' icd10_who_2019_nodes.jsonl | jq .

# Children of a node
jq -c 'select(.code == "E11") | .children' icd10_who_2019_nodes.jsonl

# All asterisk codes
jq -r 'select(.dagger_asterisk == "asterisk") | "\(.code)\t\(.title)"' icd10_who_2019_nodes.jsonl | head

# Codes that take an optional supplementary character
jq -r 'select(.optional_subdivisions != []) | "\(.code)\t\(.optional_subdivisions | join(","))"' icd10_who_2019_nodes.jsonl | head

# Load in Python
python3 -c "import json; n=[json.loads(l) for l in open('icd10_who_2019_nodes.jsonl')]; print(len(n))"
```

---

## 6. Output: `icd10_who_2019_modifiers.jsonl`

One JSON object per shared subdivision table, 46 lines. This is the only place the 101 entries of the
28 optional tables live, and it also keeps the 18 expanded tables whole.

| Field | Type | Example | Notes |
|---|---|---|---|
| `code` | string | `"S19S72_5"` | WHO's table code |
| `character` | int or null | `5` | Character position from the table name (`_4` / `_5`) |
| `optional` | bool | `true` | `true` if no entry became a code (4.4) |
| `notes` | string[] | `["... a fracture not indicated as closed or open should be classified as closed."]` | Table heading text |
| `declared_on` | string[] | `["S72"]` | Classes with `ModifiedBy` for this table |
| `excluded_on` | string[] | `[]` | Classes with `ExcludeModifier` for this table |
| `entries` | object[] | see below | One per `ModifierClass` |

Each entry has `code` (`"0"`, `".5"`), `title`, `dagger_asterisk`, `inclusions`, `exclusions`,
`notes`, `coding_hints`, `definitions`, with the same formats as on nodes.

```json
{"code": "J96_5", "character": 5, "optional": true,
 "notes": ["The following supplementary subclassification is provided for optional use with subcategories in J96.- :"],
 "declared_on": ["J96"], "excluded_on": [],
 "entries": [{"code": "0", "title": "Type I [hypoxic]", "inclusions": [], "exclusions": [], "...": "..."},
             {"code": "1", "title": "Type II [hypercapnic]", "...": "..."},
             {"code": "9", "title": "Type unspecified", "...": "..."}]}
```

The 28 optional tables: `J96_5`, `I70M10_4`, `S13M00_5`, `S13M23_5`, `S13M40_5`, `S13M99_5`, 20
fracture/open-wound tables `S19S02_5` … `S19T142_5`, `S20W00_4`, `S20V01T_5`.

```bash
cd data/who-icd10/out
jq -c 'select(.code == "J96_5") | .entries[] | {code, title}' icd10_who_2019_modifiers.jsonl
jq -r 'select(.optional) | .code' icd10_who_2019_modifiers.jsonl
```

---

## 7. Output: `icd10_who_2019_edges.csv`

Header: `src,dst,type,note`. 17,973 rows. The same rows are in the SQLite `edges` table.

| `type` | Count | Direction | `note` | Use |
|---|---|---|---|---|
| `child_of` | 12,575 | child → parent | empty | Tree walk L1 → L2 → L3 |
| `excludes` | 4,980 | node → excluded target | full exclusion text | Re-route ("not here, try X") and prune clashing paths |
| `dagger_pairs_with_asterisk` | 304 (262 unique) | dagger code → asterisk code | empty | Add the companion * code |
| `asterisk_needs_dagger` | 114 | asterisk code → dagger target | empty | Never code this * alone or as main |

Exclusions inside optional table entries (10 in total) are kept in the modifiers file only, because
their source is a supplementary character, not a code.

Example rows:

```text
src,dst,type,note
E11.5,E11,child_of,
E11,E12.-,excludes,diabetes mellitus (in): malnutrition-related (E12.-)
A02.2,M01.3,dagger_pairs_with_asterisk,
G63.2,E10-E14 with common fourth character .4,asterisk_needs_dagger,
```

### 7.1 `dst` is WHO's raw reference text, not always a node code

`dst` keeps the reference exactly as WHO wrote it. Normalise it before looking it up in `nodes`:

| `dst` form | Example | How to resolve |
|---|---|---|
| Plain code | `E11.5`, `R81` | Direct lookup |
| Code with `.-` ("any subdivision") | `E12.-`, `O24.-` | Strip `.-`, the 3-character category |
| Block range | `O00-O99`, `C00-D48` | Matches a block code when one exists; otherwise take the first code |
| Sub-code range | `A04.0-A04.4`, `C00.0-C00.2` | Expand to the codes in that range under the same category |
| Roman numeral (`child_of` only) | `I`, `XIX` | Chapter code, direct lookup |
| Free text | `E10-E14 with common fourth character .4` | Range `E10-E14` plus fixed 4th character `.4` (E10.4 ... E14.4) |

Counts by form: plain code 13,949; `.-` 862; block range 2,736; Roman numeral 211 (all `child_of`,
block → chapter); sub-code range and free text 215 together.

### 7.2 Duplicates

42 rows are exact duplicates, all of type `dagger_pairs_with_asterisk` (the same asterisk reference
appears in more than one inclusion of a node). So that type has 304 rows but 262 unique pairs.
17,931 rows are unique overall. Deduplicate when loading:

```bash
sqlite3 data/who-icd10/out/icd10_who_2019.sqlite \
  "SELECT type, COUNT(*) FROM (SELECT DISTINCT src, dst, type, note FROM edges) GROUP BY type;"
```

---

## 8. Output: `icd10_who_2019.sqlite`

Same data as the JSONL and CSV files, plus a full-text index. This is the retrieval tool the agents
call.

### 8.1 Schema

```sql
CREATE TABLE nodes (
  code            TEXT PRIMARY KEY,
  kind            TEXT,      -- chapter | block | category
  level           INTEGER,   -- 0, 1, 3, 4, 5
  title           TEXT,
  title_long      TEXT,
  parent          TEXT,
  chapter         TEXT,
  path            TEXT,      -- ancestors joined with ' > ', e.g. 'IV > E10-E14 > E11'
  billable        INTEGER,   -- 0 | 1
  dagger_asterisk TEXT,      -- 'dagger' | 'asterisk' | NULL
  modifier_source TEXT,
  data            TEXT       -- the full JSONL record as a JSON string
);
CREATE TABLE edges (src TEXT, dst TEXT, type TEXT, note TEXT);
CREATE TABLE modifiers (
  code      TEXT PRIMARY KEY,
  character INTEGER,         -- 4 | 5
  optional  INTEGER,         -- 0 | 1
  data      TEXT             -- the full modifiers JSONL record as a JSON string
);
CREATE INDEX edges_src    ON edges(src);
CREATE INDEX edges_dst    ON edges(dst);
CREATE INDEX nodes_parent ON nodes(parent);

CREATE VIRTUAL TABLE search USING fts5(
  code UNINDEXED,
  title,          -- node title
  inclusions,     -- inclusion terms joined with ' | '
  path_titles,    -- ancestor titles joined with ' > '
  subdivisions    -- titles + inclusions of the node's optional subdivision entries
);
```

Fields not given their own column (inclusions, exclusions, notes, hints, subdivisions, pairs) are in
`data`. Read them with SQLite's JSON functions.

### 8.2 Query recipes

```bash
DB=data/who-icd10/out/icd10_who_2019.sqlite
```

Doctor wording to candidate billable codes (the hit comes from the inclusion term, not the title):

```bash
sqlite3 $DB "SELECT n.code, n.title FROM search s JOIN nodes n USING(code)
             WHERE search MATCH 'diabetic AND ulcer' AND n.billable = 1;"
# E10.5 ... E14.5
```

Ranked search on one column:

```bash
sqlite3 $DB "SELECT code, title, bm25(search) AS score FROM search
             WHERE search MATCH 'inclusions:polyneuropathy' ORDER BY score LIMIT 10;"
```

Supplementary wording ("Type II respiratory failure") to the codes it qualifies:

```bash
sqlite3 $DB "SELECT code, title FROM search WHERE search MATCH 'subdivisions:hypercapnic';"
# J96.0, J96.1, J96.9
```

Walk down one level (what the L2/L3 agents are shown):

```bash
sqlite3 $DB "SELECT code, title, billable FROM nodes WHERE parent = 'E11' ORDER BY code;"
```

Inclusions and exclusions of a node:

```bash
sqlite3 $DB "SELECT value FROM nodes, json_each(nodes.data, '$.inclusions') WHERE code = 'E11';"
sqlite3 $DB "SELECT json_extract(value, '$.text') FROM nodes, json_each(nodes.data, '$.exclusions') WHERE code = 'E11';"
```

Optional subdivision entries for a code:

```bash
sqlite3 $DB "SELECT m.code, json_extract(e.value, '$.code'), json_extract(e.value, '$.title')
             FROM nodes n, json_each(n.data, '$.optional_subdivisions') t
             JOIN modifiers m ON m.code = t.value, json_each(m.data, '$.entries') e
             WHERE n.code = 'S72.0';"
# S19S72_5|0|closed
# S19S72_5|1|open
```

Rules the validator enforces for a code:

```bash
sqlite3 $DB "SELECT type, dst, note FROM edges WHERE src = 'G63.2' AND type != 'child_of';"
```

Every code that excludes a given target (reverse lookup):

```bash
sqlite3 $DB "SELECT src, note FROM edges WHERE type = 'excludes' AND dst LIKE 'E11%';"
```

---

## 9. Output: `manifest.json`

Audit record for a build. Use it to prove where the data came from and to spot changes between
WHO releases.

| Key | Contents |
|---|---|
| `generated_at` | UTC time of the build |
| `release` | ClaML title, `version`, `date` |
| `sources` | For each zip: URL, local path, size, SHA-256 |
| `outputs` | For each output file: size, SHA-256 |
| `counts` | Node and table counts (see below) |
| `checks` | The nine hard checks and their result |
| `warnings` | Exclusion references that do not contain a plain code (currently 0) |
| `edge_counts` | Rows per edge type |

Reference values for this release:

| Count | Value |
|---|---|
| chapter / block / category | 22 / 274 / 12,301 |
| billable | 10,636 |
| billable_not_in_meta | `U10.9`, `U11.9`, `U12.9` |
| derived_from_modifiers | 1,058 |
| modifier_tables / optional_tables / optional_entries | 46 / 28 / 101 |
| with_optional_subdivisions | 536 |
| dagger / asterisk | 81 / 373 |
| nodes with inclusions / exclusions | 4,441 / 2,211 |
| exclusion references | 4,980 |

---

## 10. Validation checks

Hard checks. Any failure stops the build before `out/` is written.

| Check | Rule | Why it matters |
|---|---|---|
| 22 chapters | exactly 22 `chapter` nodes | Catches a truncated or wrong file |
| blocks present | at least 250 blocks | Same |
| billable codes present | at least 10,000 billable | Same |
| every meta billable code parsed | every `T` code in `syst_codes.txt` is a node | No valid code is missing |
| every derived code matched a modifier | modifier expansion left nothing unmatched | Expansion logic is complete |
| every parent exists | every `parent` is a node | Tree has no broken links |
| billable codes are leaves | no billable node has children | Agents can treat "billable" as "stop here" |
| **every ClaML text present in output** | Re-reads the XML independently of the parser. Every rubric on every `Class`, `Modifier` and `ModifierClass` must appear in the output field it belongs to, ignoring spacing and punctuation | No text can be silently dropped. Only `modifierlink` pointers are exempt |
| every optional table attached to a billable code | each optional table is on at least one code, unless WHO switches it off with `ExcludeModifier` | Optional subdivisions reach the codes they qualify |

The text check was tested by deliberately deleting an inclusion, cutting a note short, removing a
table heading and damaging an optional entry title. It reported all four.

Info lines (do not stop the build): optional tables not attached to any code, billable codes not in
the meta table, and exclusion references whose text contains no recognisable code.

To check the outputs against a manual download, compare file hashes:

```bash
shasum -a 256 manual-dump/icd102019en.xml data/who-icd10/claml/icd102019en.xml
shasum -a 256 manual-dump/icd102019enMeta/* data/who-icd10/meta/*
```

---

## 11. How the agents use the data

| Agent | Reads | Typical query |
|---|---|---|
| Normaliser | `search` (FTS5) | Doctor phrase → top candidate codes and their paths |
| L1 chapter router | chapter nodes: `title`, `notes`, `exclusions` | `SELECT code, title, data FROM nodes WHERE kind = 'chapter'` |
| L2 category | children of chosen chapter/block + their inclusions/exclusions + `subdivision_notes` | `WHERE parent = ?` |
| L3 4th character | children of chosen category + inclusions; then any `optional_subdivisions` | `WHERE parent = ?`, then `modifiers` |
| Validator | `edges` | `excludes` clashes, `asterisk_needs_dagger`, `dagger_pairs_with_asterisk`, `billable = 1` |

Rules of thumb:

* Show an agent only the subtree in play (one `parent = ?` query), never the whole code set.
* An `excludes` edge re-routes a path to its target. It does not simply kill the path.
* A final code must have `billable = 1`.
* A code with `dagger_asterisk = 'asterisk'` is never the main condition and must be paired with its
  dagger code (for example E11.4 + G63.2).
* When documentation does not support a specific 4th character, use the `.8` / `.9` child and raise
  a query to the doctor.
* Optional subdivisions are extra detail, not part of the code. Record them alongside the code (for
  example `S72.0` + open) if a payer asks for them; follow the defaults in `subdivision_notes`
  (an unstated fracture is closed).

---

## 12. Known quirks and limits

* **No Alphabetic Index (Volume 3).** The only doctor-language bridge in this data is the inclusion
  terms (9.7k). An Indian abbreviation and brand-drug lexicon and a synonym layer still need to be
  built on top.
* **`dst` in edges is raw text.** See 7.1. Resolve ranges, `.-` and free-text references before lookup.
* **42 duplicate edge rows**, all `dagger_pairs_with_asterisk`. See 7.2.
* **Only 4 five-character codes** (`B18.00`, `B18.09`, `B18.10`, `B18.19`: chronic hepatitis B phases).
  Other 5th characters (musculoskeletal site, fracture open/closed, J96 type) are WHO's optional
  supplementary characters and live in `optional_subdivisions` instead (4.4).
* **Optional tables follow the XML exactly.** For example, the musculoskeletal site table is declared on
  M00-M14, M19, M21… but not on M15-M18, so M17.1 has no `optional_subdivisions`.
* **The meta files are older than the XML.** U10.9, U11.9 and U12.9 are made billable by rule (4.5).
  The meta file also lists mortality codes as `UNDEF` for U07.x and U09, where the XML has values;
  the output uses the XML.
* **Formatting is simplified.** Paragraphs, list items and table rows are kept as lines; bold, italic,
  subscript and table cell spans are not.
* **`modifierlink` rubrics are not stored.** They only point to subdivision tables, which are applied
  and stored.
* **Coarser than ICD-10-CM.** No laterality and no 7th character. A diabetic foot ulcer is just
  `E11.5` (CM would be E11.621 + L97.4xx). Keep side and encounter as evidence fields if a payer needs them.
* **Last ICD-10 release.** WHO's newer work is in ICD-11. Keep the graph design independent of the
  code system so a migration only swaps the data.
* **Licence.** The files are © WHO. Check WHO's ICD licensing terms
  (<https://www.who.int/about/policies/publishing/copyright>) and payer requirements before
  commercial use.
