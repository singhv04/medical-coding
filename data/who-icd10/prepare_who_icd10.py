#!/usr/bin/env python3
"""End-to-end data preparation for WHO ICD-10 (2019, incl. COVID-19 updates).

One command does everything:

    python3 prepare_who_icd10.py            # download -> extract -> parse -> validate -> build
    python3 prepare_who_icd10.py --force    # re-download even if the zips are already present

Steps
  1. download  official WHO files from icdcdn.who.int (no login needed) into raw/
  2. extract   ClaML XML -> claml/, plain-text meta tables -> meta/
  3. parse     ClaML hierarchy + coding rules; expand modifier-derived codes (E11 + '.5' -> E11.5)
  4. validate  counts and referential checks; exits non-zero if a hard check fails
  5. build     out/icd10_who_2019_nodes.jsonl, out/icd10_who_2019_edges.csv,
               out/icd10_who_2019_modifiers.jsonl, out/icd10_who_2019.sqlite (with FTS5 search),
               out/manifest.json

Only the Python standard library is used.
"""
import argparse
import csv
import hashlib
import json
import re
import sqlite3
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW, CLAML_DIR, META_DIR, OUT = HERE / "raw", HERE / "claml", HERE / "meta", HERE / "out"

SOURCES = {
    "claml": {
        "url": "https://icdcdn.who.int/icd10/claml/icd102019en.xml.zip",
        "zip": "icd102019en.xml.zip",
        "dest": CLAML_DIR,
    },
    "meta": {
        "url": "https://icdcdn.who.int/icd10/meta/icd102019enMeta.zip",
        "zip": "icd102019enMeta.zip",
        "dest": META_DIR,
    },
}
CLAML_FILE = CLAML_DIR / "icd102019en.xml"
META_CODES = META_DIR / "icd102019syst_codes.txt"

RUBRIC_FIELDS = {
    "inclusion": "inclusions",
    "exclusion": "exclusions",
    "note": "notes",
    "text": "notes",
    "introduction": "notes",
    "footnote": "notes",
    "coding-hint": "coding_hints",
    "definition": "definitions",
}
EXPECTED = {"chapters": 22, "min_blocks": 250, "min_billable": 10000}


def log(step, msg):
    print(f"[{step}] {msg}", flush=True)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- 1. download
def download(force):
    RAW.mkdir(exist_ok=True)
    files = {}
    for name, src in SOURCES.items():
        path = RAW / src["zip"]
        if path.exists() and not force:
            log("download", f"{src['zip']} already present, skipping (use --force to refresh)")
        else:
            log("download", f"{src['url']}")
            req = urllib.request.Request(src["url"], headers={"User-Agent": "icd10-prep/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r, open(path, "wb") as f:
                f.write(r.read())
        if not zipfile.is_zipfile(path):
            sys.exit(f"[download] {path} is not a valid zip")
        files[name] = {"url": src["url"], "file": str(path.relative_to(HERE)), "bytes": path.stat().st_size,
                       "sha256": sha256(path)}
    return files


# ----------------------------------------------------------------- 2. extract
def extract():
    for src in SOURCES.values():
        src["dest"].mkdir(exist_ok=True)
        with zipfile.ZipFile(RAW / src["zip"]) as z:
            for member in z.namelist():
                target = (src["dest"] / member).resolve()
                if src["dest"].resolve() not in target.parents:
                    sys.exit(f"[extract] unsafe path in zip: {member}")
            z.extractall(src["dest"])
        log("extract", f"{src['zip']} -> {src['dest'].name}/")
    for p in (CLAML_FILE, META_CODES):
        if not p.exists():
            sys.exit(f"[extract] expected file missing: {p}")


# ------------------------------------------------------------------- 3. parse
BLOCK_TAGS = {"Para", "List", "Table", "THead", "TBody"}


def label_text(label, with_refs=True):
    """Flatten a ClaML <Label>. List fragments read 'Diabetic: ulcer'; references become ' (E12.-)'.

    Paragraphs, list items and table rows become separate lines ('- item', 'cell | cell'),
    so multi-paragraph notes keep their layout.
    """
    def flat(el):
        parts = [el.text or ""]
        for child in el:
            if child.tag == "Reference":
                if with_refs:
                    parts.append(f" ({(child.text or child.get('code') or '').strip()})")
            elif child.tag in BLOCK_TAGS:
                parts.append(f"\n{flat(child)}\n")
            elif child.tag == "ListItem":
                parts.append(f"\n- {flat(child)}\n")
            elif child.tag == "Row":
                parts.append("\n" + " | ".join(" ".join(flat(c).split()) for c in child.findall("Cell")) + "\n")
            elif child.tag == "Term" and child.get("class") == "tab":
                parts.append(" " + flat(child))
            else:
                parts.append(flat(child))
            parts.append(child.tail or "")
        return "".join(parts)

    def tidy(s):
        return "\n".join(line for line in (" ".join(l.split()) for l in s.split("\n")) if line)

    frags = label.findall("Fragment")
    if frags:
        return " ".join(tidy(flat(f)) for f in frags)
    return tidy(flat(label))


def label_refs(label):
    return [{"text": (r.text or "").strip(), "code": r.get("code") or (r.text or "").strip(),
             "usage": r.get("usage")} for r in label.iter("Reference")]


def read_rubrics(el):
    out = {"title": None, "title_long": None, "title_refs": []}
    for rub in el.findall("Rubric"):
        kind, label = rub.get("kind"), rub.find("Label")
        if label is None:
            continue
        if kind == "preferred":
            out["title"] = label_text(label, with_refs=False)
            out["title_refs"] = label_refs(label)
        elif kind == "preferredLong":
            out["title_long"] = label_text(label, with_refs=False)
        elif kind in RUBRIC_FIELDS:
            item = {"text": label_text(label)}
            refs = label_refs(label)
            if refs:
                item["refs"] = refs
            usage = next((f.get("usage") for f in label.findall("Fragment") if f.get("usage")), None)
            if usage:
                item["usage"] = usage
            out.setdefault(RUBRIC_FIELDS[kind], []).append(item)
    return out


def load_meta():
    rows = {}
    with open(META_CODES, encoding="latin-1") as f:
        for line in f:
            p = line.rstrip("\r\n").split(";")
            rows[p[6]] = {"level": int(p[0]), "terminal": p[1] == "T", "derived": p[2] == "S"}
    return rows


def parse():
    root = ET.parse(CLAML_FILE).getroot()
    title = root.find("Title")
    meta = load_meta()

    modifiers = {}
    for mc in root.findall("ModifierClass"):
        r = read_rubrics(mc)
        r["usage"] = mc.get("usage")
        modifiers.setdefault(mc.get("modifier"), {})[mc.get("code")] = r

    # Shared subdivision tables, kept whole: heading text plus every entry. Tables whose entries are
    # not valid codes (WHO's "optional supplementary" subdivisions) are only reachable from here.
    tables = {}
    for m in root.findall("Modifier"):
        code, r = m.get("code"), read_rubrics(m)
        char = re.search(r"_(\d)$", code)
        tables[code] = {
            "code": code, "character": int(char.group(1)) if char else None, "optional": None,
            "notes": [i["text"] for i in r.get("notes", [])], "declared_on": [], "excluded_on": [],
            "entries": [{"code": sfx, "title": e["title"],
                         "dagger_asterisk": {"dagger": "dagger", "aster": "asterisk"}.get(e.get("usage")),
                         "inclusions": [i["text"] for i in e.get("inclusions", [])],
                         "exclusions": e.get("exclusions", []),
                         "notes": [i["text"] for i in e.get("notes", [])],
                         "coding_hints": [i["text"] for i in e.get("coding_hints", [])],
                         "definitions": [i["text"] for i in e.get("definitions", [])]}
                        for sfx, e in modifiers.get(code, {}).items()],
        }

    classes = {}
    for c in root.findall("Class"):
        sup = c.find("SuperClass")
        node = {"code": c.get("code"), "kind": c.get("kind"), "usage": c.get("usage"),
                "parent": sup.get("code") if sup is not None else None,
                "children": [s.get("code") for s in c.findall("SubClass")],
                "modified_by": [{"code": m.get("code"), "all": m.get("all") == "true"}
                                for m in c.findall("ModifiedBy")],
                "exclude_modifiers": [m.get("code") for m in c.findall("ExcludeModifier")],
                "mortality": {m.get("name"): m.get("value") for m in c.findall("Meta")}}
        node.update(read_rubrics(c))
        classes[node["code"]] = node
        for m in node["modified_by"]:
            tables[m["code"]]["declared_on"].append(node["code"])
        for m in node["exclude_modifiers"]:
            tables[m]["excluded_on"].append(node["code"])

    def ancestors(code):
        path, p = [], classes[code]["parent"]
        while p:
            path.append(p)
            p = classes[p]["parent"]
        return path

    def applicable_modifiers(code):
        mods = [m["code"] for m in classes[code]["modified_by"]]
        excluded = set(classes[code]["exclude_modifiers"])
        for a in ancestors(code):
            excluded |= set(classes[a]["exclude_modifiers"])
            mods += [m["code"] for m in classes[a]["modified_by"] if m["all"]]
        return [m for m in mods if m not in excluded]

    # Codes such as E11.5 are not <Class> elements: they come from E11 + modifier S04E10_4 '.5'.
    # The meta file lists exactly which derived codes are valid, so expand only those.
    unmatched = []
    for code, m in meta.items():
        if not m["derived"] or code in classes:
            continue
        base = code[:-1].rstrip(".")
        while base not in classes and len(base) > 3:
            base = base[:-1].rstrip(".")
        suffix, digits = code[len(base):], len(code.replace(".", ""))
        hit = None
        for mod in applicable_modifiers(base):
            opts = modifiers.get(mod, {})
            key = suffix if suffix in opts else suffix[-1:]
            if key in opts and mod.endswith("_4") == (digits == 4):
                hit = (mod, opts[key])
                break
        if hit is None:
            unmatched.append(code)
            continue
        mod, rub = hit
        node = {"code": code, "kind": "category", "usage": rub.get("usage"), "parent": base, "children": [],
                "title": f"{classes[base]['title']}: {rub['title']}", "title_long": None, "title_refs": [],
                "modifier_source": mod, "modified_by": [], "exclude_modifiers": [],
                "mortality": classes[base]["mortality"]}
        for k in ("inclusions", "exclusions", "notes", "coding_hints", "definitions"):
            if rub.get(k):
                node[k] = rub[k]
        classes[code] = node
        classes[base]["children"].append(code)

    used = {n.get("modifier_source") for n in classes.values()}
    for t in tables.values():
        t["optional"] = t["code"] not in used

    def optional_tables(code):
        # Optional tables apply to every code below the class that declares them (WHO does not always
        # set all="true" on these), except subtrees that switch them off with ExcludeModifier.
        chain = [code] + ancestors(code)
        excluded = {x for a in chain for x in classes[a]["exclude_modifiers"]}
        return [m["code"] for a in reversed(chain) for m in classes[a]["modified_by"]
                if tables[m["code"]]["optional"] and m["code"] not in excluded]

    # Codes added to the ClaML after the meta tables were published (U10.9, U11.9, U12.9) are missing
    # from meta. Treat such leaves as billable, except WHO's "Emergency use of Uxx" placeholders.
    def is_billable(code, n):
        if code in meta:
            return meta[code]["terminal"]
        return n["kind"] == "category" and not n["children"] and not n["title"].startswith("Emergency use of")

    nodes = []
    for code, n in classes.items():
        anc = ancestors(code)
        billable = is_billable(code, n)
        nodes.append({
            "code": code,
            "kind": n["kind"],
            "level": {"chapter": 0, "block": 1}.get(n["kind"], len(code.replace(".", ""))),
            "title": n["title"],
            "title_long": n.get("title_long"),
            "parent": n["parent"],
            "path": list(reversed(anc)),
            "chapter": anc[-1] if anc else code,
            "children": n["children"],
            "billable": billable,
            "dagger_asterisk": {"dagger": "dagger", "aster": "asterisk"}.get(n.get("usage")),
            "inclusions": [i["text"] for i in n.get("inclusions", [])],
            "exclusions": n.get("exclusions", []),
            "notes": [i["text"] for i in n.get("notes", [])],
            "coding_hints": [i["text"] for i in n.get("coding_hints", [])],
            "definitions": [i["text"] for i in n.get("definitions", [])],
            "subdivision_notes": [t for m in n["modified_by"] for t in tables[m["code"]]["notes"]],
            "optional_subdivisions": optional_tables(code) if billable else [],
            "title_refs": n["title_refs"],
            "pairs_with": [r["text"] for i in n.get("inclusions", []) for r in i.get("refs", [])
                           if r.get("usage") == "aster"],
            "modifier_source": n.get("modifier_source"),
            "mortality_lists": n["mortality"] or None,
        })
    log("parse", f"{len(nodes)} nodes from ClaML '{title.get('version')}' ({title.get('date')}), "
                 f"{len(tables)} modifier tables ({sum(t['optional'] for t in tables.values())} optional)")
    release = {"title": title.text, "version": title.get("version"), "date": title.get("date")}
    return nodes, list(tables.values()), meta, unmatched, release


# ---------------------------------------------------------------- 4. validate
CODE_RE = re.compile(r"[A-Z]\d{2}(?:\.\d{1,2})?")
NON_ALNUM = re.compile(r"[\W_]+")
FIELD_OF_KIND = {"preferred": "title", "preferredLong": "title_long", **RUBRIC_FIELDS}


def squash(s):
    return NON_ALNUM.sub("", (s or "").lower())


def source_text(label, drop_refs):
    """Plain text of a ClaML <Label>, read independently of label_text()."""
    def walk(el):
        out = [el.text or ""]
        for child in el:
            if not (drop_refs and child.tag == "Reference"):
                out.append(walk(child))
            out.append(child.tail or "")
        return "".join(out)
    return walk(label)


def missing_text(nodes, tables):
    """Every rubric in the ClaML must appear (ignoring spacing and punctuation) in the output field
    it belongs to. Returns the rubrics that do not. 'modifierlink' rubrics are only pointers
    ('[See before E10 for subdivisions]') and are represented by the expansion itself."""
    by_code = {n["code"]: n for n in nodes}
    entries = {(t["code"], e["code"]): e for t in tables for e in t["entries"]}
    table_by = {t["code"]: t for t in tables}

    def field_text(rec, field):
        v = rec.get(field)
        items = v if isinstance(v, list) else [v]
        return squash(" ".join(i["text"] if isinstance(i, dict) else (i or "") for i in items))

    lost = []
    for el in ET.parse(CLAML_FILE).getroot():
        if el.tag == "Class":
            rec, where = by_code.get(el.get("code")), el.get("code")
        elif el.tag == "ModifierClass":
            rec, where = entries.get((el.get("modifier"), el.get("code"))), f"{el.get('modifier')} {el.get('code')}"
        elif el.tag == "Modifier":
            rec, where = table_by.get(el.get("code")), el.get("code")
        else:
            continue
        for rub in el.findall("Rubric"):
            kind, label = rub.get("kind"), rub.find("Label")
            if kind == "modifierlink" or label is None:
                continue
            field = FIELD_OF_KIND.get(kind)
            want = squash(source_text(label, drop_refs=kind in ("preferred", "preferredLong")))
            if rec is None or field is None or want not in field_text(rec, field):
                lost.append(f"{where} {kind}")
    return lost


def validate(nodes, tables, meta, unmatched):
    by_code = {n["code"]: n for n in nodes}
    kinds = {k: sum(1 for n in nodes if n["kind"] == k) for k in ("chapter", "block", "category")}
    billable = [n for n in nodes if n["billable"]]
    meta_billable = {c for c, m in meta.items() if m["terminal"]}
    three = {c for c in by_code if len(c) == 3}

    def resolves(text):
        codes = CODE_RE.findall(text)
        return bool(codes) and all(c in by_code or c[:3] in three for c in codes)

    excl_refs = [r["text"] for n in nodes for e in n["exclusions"] for r in e.get("refs", [])]
    unresolved = sorted({t for t in excl_refs if not resolves(t)})
    lost = missing_text(nodes, tables)
    attached = {t for n in nodes for t in n["optional_subdivisions"]}
    optional = [t for t in tables if t["optional"]]
    billable_not_in_meta = sorted(n["code"] for n in billable if n["code"] not in meta)

    hard = {
        "22 chapters": kinds["chapter"] == EXPECTED["chapters"],
        "blocks present": kinds["block"] >= EXPECTED["min_blocks"],
        "billable codes present": len(billable) >= EXPECTED["min_billable"],
        "every meta billable code parsed": meta_billable <= set(by_code),
        "every derived code matched a modifier": not unmatched,
        "every parent exists": all(n["parent"] is None or n["parent"] in by_code for n in nodes),
        "billable codes are leaves": all(not n["children"] for n in billable),
        "every ClaML text present in output": not lost,
        # Tables WHO switches off with ExcludeModifier (place of occurrence, activity) are separate
        # variables, not extra characters, so they live only in the modifiers file.
        "every optional table attached to a billable code": all(t["code"] in attached or t["excluded_on"]
                                                                for t in optional),
    }
    report = {
        "counts": {**kinds, "billable": len(billable), "billable_not_in_meta": billable_not_in_meta,
                   "derived_from_modifiers": sum(1 for n in nodes if n["modifier_source"]),
                   "modifier_tables": len(tables), "optional_tables": len(optional),
                   "optional_entries": sum(len(t["entries"]) for t in optional),
                   "with_optional_subdivisions": sum(1 for n in nodes if n["optional_subdivisions"]),
                   "dagger": sum(1 for n in nodes if n["dagger_asterisk"] == "dagger"),
                   "asterisk": sum(1 for n in nodes if n["dagger_asterisk"] == "asterisk"),
                   "with_inclusions": sum(1 for n in nodes if n["inclusions"]),
                   "with_exclusions": sum(1 for n in nodes if n["exclusions"]),
                   "exclusion_references": len(excl_refs)},
        "checks": hard,
        "warnings": {"exclusion_refs_not_a_plain_code": len(unresolved), "examples": unresolved[:8]},
    }
    for name, ok in hard.items():
        log("validate", f"{'PASS' if ok else 'FAIL'}  {name}")
    if lost:
        log("validate", f"      {len(lost)} rubrics missing from output, e.g. {lost[:5]}")
    unattached = [t["code"] for t in optional if t["code"] not in attached]
    if unattached:
        log("validate", f"info  optional tables not attached to codes (WHO ExcludeModifier): {unattached}")
    log("validate", f"info  billable but not in meta table: {billable_not_in_meta}")
    log("validate", f"info  {len(unresolved)} exclusion refs are free text, not plain codes "
                    f"(e.g. {unresolved[:3]})")
    if not all(hard.values()):
        sys.exit("[validate] hard checks failed; outputs not written")
    return report


# ------------------------------------------------------------------- 5. build
SCHEMA = """
CREATE TABLE nodes (
  code TEXT PRIMARY KEY, kind TEXT, level INTEGER, title TEXT, title_long TEXT,
  parent TEXT, chapter TEXT, path TEXT, billable INTEGER, dagger_asterisk TEXT,
  modifier_source TEXT, data TEXT
);
CREATE TABLE edges (src TEXT, dst TEXT, type TEXT, note TEXT);
CREATE TABLE modifiers (code TEXT PRIMARY KEY, character INTEGER, optional INTEGER, data TEXT);
CREATE INDEX edges_src ON edges(src);
CREATE INDEX edges_dst ON edges(dst);
CREATE INDEX nodes_parent ON nodes(parent);
CREATE VIRTUAL TABLE search USING fts5(code UNINDEXED, title, inclusions, path_titles, subdivisions);
"""


def build_edges(nodes):
    edges = []
    for n in nodes:
        if n["parent"]:
            edges.append((n["code"], n["parent"], "child_of", ""))
        for e in n["exclusions"]:
            for r in e.get("refs", []):
                edges.append((n["code"], r["text"] or r["code"], "excludes", e["text"]))
        for r in n["title_refs"]:
            if r.get("usage") == "dagger":
                edges.append((n["code"], r["text"], "asterisk_needs_dagger", ""))
        for target in n["pairs_with"]:
            edges.append((n["code"], target, "dagger_pairs_with_asterisk", ""))
    return edges


def build(nodes, tables, report, sources, release):
    OUT.mkdir(exist_ok=True)
    edges = build_edges(nodes)
    titles = {n["code"]: n["title"] for n in nodes}
    table_by = {t["code"]: t for t in tables}

    def subdivision_terms(n):
        return " | ".join(term for t in n["optional_subdivisions"] for e in table_by[t]["entries"]
                          for term in [e["title"], *e["inclusions"]])

    with open(OUT / "icd10_who_2019_nodes.jsonl", "w") as f:
        for n in nodes:
            f.write(json.dumps(n, ensure_ascii=False) + "\n")
    with open(OUT / "icd10_who_2019_modifiers.jsonl", "w") as f:
        for t in tables:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    with open(OUT / "icd10_who_2019_edges.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["src", "dst", "type", "note"])
        w.writerows(edges)

    db = OUT / "icd10_who_2019.sqlite"
    db.unlink(missing_ok=True)
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [
        (n["code"], n["kind"], n["level"], n["title"], n["title_long"], n["parent"], n["chapter"],
         " > ".join(n["path"]), int(n["billable"]), n["dagger_asterisk"], n["modifier_source"],
         json.dumps(n, ensure_ascii=False)) for n in nodes])
    con.executemany("INSERT INTO edges VALUES (?,?,?,?)", edges)
    con.executemany("INSERT INTO modifiers VALUES (?,?,?,?)", [
        (t["code"], t["character"], int(t["optional"]), json.dumps(t, ensure_ascii=False)) for t in tables])
    con.executemany("INSERT INTO search VALUES (?,?,?,?,?)", [
        (n["code"], n["title"], " | ".join(n["inclusions"]), " > ".join(titles[p] for p in n["path"]),
         subdivision_terms(n)) for n in nodes])
    con.commit()
    con.close()

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "release": release,
        "sources": sources,
        "outputs": {p.name: {"bytes": p.stat().st_size, "sha256": sha256(p)}
                    for p in sorted(OUT.iterdir()) if p.name != "manifest.json"},
        **report,
        "edge_counts": {t: sum(1 for e in edges if e[2] == t) for t in sorted({e[2] for e in edges})},
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    for name, info in manifest["outputs"].items():
        log("build", f"out/{name}  {info['bytes'] / 1e6:.1f} MB")
    log("build", f"edges: {manifest['edge_counts']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="re-download the WHO zips")
    args = ap.parse_args()
    sources = download(args.force)
    extract()
    nodes, tables, meta, unmatched, release = parse()
    report = validate(nodes, tables, meta, unmatched)
    build(nodes, tables, report, sources, release)
    log("done", f"{report['counts']['billable']} billable WHO ICD-10 codes ready in {OUT.relative_to(HERE)}/")


if __name__ == "__main__":
    main()
