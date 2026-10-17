# Brainstorming

Working notes: ideas, papers read and what they mean for the WHO ICD-10 auto-coder. Nothing here is
built yet unless it says so. The current design is in [ICD10_Coding_Approach.pdf](ICD10_Coding_Approach.pdf)
and the knowledge base in [WHO_ICD10_Data_Structure.md](WHO_ICD10_Data_Structure.md).

## Contents

1. [Paper: "Understanding the Limits of Agentic ICD Coding" (arXiv 2609.13806)](#1-paper-understanding-the-limits-of-agentic-icd-coding-arxiv-260913806)
2. [Ideas to take into the design](#2-ideas-to-take-into-the-design)
3. [Open questions](#3-open-questions)

---

## 1. Paper: "Understanding the Limits of Agentic ICD Coding" (arXiv 2609.13806)

*Read 17 Oct 2026.* Yock, Cao, Chen, Mao, Jiang (Nanyang Technological University and ASUS
Intelligent Cloud Services, Singapore), arXiv, 12 Sep 2026. <https://arxiv.org/pdf/2609.13806>

### 1.1 What it is

An **evaluation paper, not a new coding system**. It asks where today's automated coders fail, using
**ICD-10-CM** (US) codes on **MIMIC-IV** discharge summaries from a single US hospital.

It compares three kinds of system:

| Type | System | How it works |
|---|---|---|
| Neural classifier | PLM-ICD | Biomedical language model trained on MIMIC-IV; predicts all codes at once as multi-label classification. No reasoning, no lookup |
| Fixed workflow | CodeSeeker ("Code Like Humans", Motzfeldt et al. 2025) | An LLM pipeline whose steps always run in the same order: Analyze → Locate → Assign → Verify |
| Free-form agent | The authors' own setup | An LLM decides which of 9 tools to call, in any order, up to 200 calls |

The free-form agent's 9 tools, built from the CMS 2020 ICD-10-CM XML files, fall into four groups:

| Group | Tools |
|---|---|
| Search | Alphabetical Index (with `>` drill-down), Drug Table, Neoplasm Table, External Cause Index, browse a code's children; optionally PLM-ICD suggestions |
| Verify | Full Tabular List entry for a code, including its coding rules |
| Reference | Official Coding Guidelines, by section |
| Submit | Final submission |

The key design choice is **discovery gating**: the agent can't verify or submit any code that one of
its searches didn't return. That blocks invented codes at the tool level. Rules about companion codes
("code first", "use additional code", the mandatory external-cause sequence) are only written in the
system prompt, not enforced by the tools.

**Test data:**

* 150 notes, 50 each by how often their codes appear in training data: rare (0–100 occurrences),
  uncommon (101–1,000), common (over 1,000).
* A **"multi-step" subset** of 153 notes (480 code instances) with injury codes (Chapter 19, S/T) or
  external-cause codes (Chapter 20, V–Y). The US guidelines require several linked codes for these:
  the injury, the cause, the place (Y92) and a 7th character. 123 of the notes have a Y92 code and 142
  a 7th character.

### 1.2 Results (micro-F1)

| | Rare | Uncommon | Common | Multi-step (rare / unc. / common) |
|---|---|---|---|---|
| PLM-ICD (neural) | .227 | .471 | **.656** | .256 / **.375** / **.435** |
| CodeSeeker + Opus 4.6 (workflow) | **.560** | **.483** | .607 | **.010 / .027 / .013** |
| Agent + Opus 4.6 (free-form) | .354 | .425 | .577 | .276 / .363 / .280 |

Other models in the free-form agent (GPT-5.2, GLM-5 Turbo, Qwen 3.5 Plus, Kimi K2.5, Mistral Large 3)
scored at or below Opus 4.6.

### 1.3 Findings

1. **The neural model is biased toward frequent codes.** It scores .66 on common codes but .23 on rare
   ones, because it only knows what it saw often in training.
2. **The fixed workflow is best on rare codes but almost useless on injuries.** Its retrieval step never
   finds the companion codes (cause, place) the guidelines require, and it can't go back for them later.
3. **The free-form agent does better on injuries than the workflow**, but the plain neural model still
   beats it on common injury cases. No system wins everywhere.
4. **Finding the right code is the bottleneck, not checking it.**
   * 66–86% of missed injury and external-cause codes were never returned by any search.
   * Place-of-occurrence (Y92) codes are the worst case: the guidelines require them, but nothing in the
     note prompts anyone to look for them.
   * Wrong 7th characters account for only 0–3% of misses.
5. **Choosing which candidates to keep is also hard.**
   * Models verify thousands of candidate codes but submit under 4% of them, and only 36–56% of
     submitted codes are correct.
   * 74–95% of wrong codes were verified first. So these are judgment errors, such as coding a symptom
     that's part of a confirmed diagnosis, or an old condition not treated this stay, not invented codes.
6. **Correct codes are found earlier in a session than wrong ones.** The effect is statistically strong
   (Mann–Whitney p < 10⁻¹³ for every model), so how early a code was found can serve as a confidence
   signal.
7. **Ablations (removing one part to measure its effect):**
   * Removing the tools halves rare-code F1. On common injury codes, recall falls to about 2%: models
     almost never produce companion codes from memory.
   * Removing the "mandatory sequence" instruction from the prompt barely changed Opus 4.6, but
     GPT-5.2's common-code F1 fell from .32 to .09.
   * Giving PLM-ICD's suggestions to the agent as a tool hurt Opus 4.6 on rare codes (it searched less
     on its own) but helped GPT-5.2.
8. **Cost per note** for the free-form agent: 57–87 tool calls, 65–363 seconds, about 20–35k tokens.

### 1.4 Weaknesses to keep in mind

* The samples are small (50 notes per group) with wide confidence intervals, and the authors
  themselves say the free-form agents can't be ranked against each other.
* MIMIC labels are noisy. Their own case study counts a reasonable code (OSA, obstructive sleep
  apnoea, a chronic condition) as a false positive.
* Absolute scores are low for every system (F1 0.3–0.6).
* Opus 4.6's injury-subset scores differ slightly between Table 1 (.276/.363/.280) and Table 4
  (.267/.357/.318), which suggests different runs.
* They never test discovery gating or individual tools in isolation.
* US-only: ICD-10-CM, US Official Coding Guidelines, one hospital.

### 1.5 Is their approach different from ours?

The goal is the same. The scope and the design are different.

| | Paper | Our design |
|---|---|---|
| Code set | ICD-10-CM (US, about 70k codes, 7th characters) | WHO ICD-10 (10.6k codes, no 7th character) |
| How codes are found | **Alphabetical Index first, then Tabular check**: how human coders work | **Top-down tree walk**: chapter → category → 4th character, plus full-text search over titles and inclusion terms |
| Control flow | Agent chooses its own tool order | Fixed L1 → L2 → L3 stages with a beam (several paths kept open) |
| Companion-code rules | Written in the prompt only | **Stored as edges in the graph and enforced by the validator** |
| Blocking invented codes | Discovery gating at the tool level | Only valid leaves from the knowledge base can be output |
| Reference material | Index, Drug, Neoplasm and External Cause tables, Guidelines | Tabular only. **WHO's download has no Alphabetical Index or drug/neoplasm tables** |

### 1.6 What it means for us

1. **The paper's main warning applies to our design.** Our L1→L2→L3 pipeline is a fixed workflow like
   CodeSeeker, which failed almost completely on companion codes. A top-down walk follows one concept
   down one branch, so codes that belong to a different chapter (external cause, asterisk
   manifestation, Z codes) only appear if something actively goes to fetch them.
2. **The pressure is lower in WHO ICD-10, but it doesn't go away.** In our data, 222 of the 232
   coding hints say "if desired", and place and activity are optional separate variables, not required
   codes like the US Y92. Chapter XX's note still says an external-cause code "shall be used in
   addition to" the nature-of-injury code where applicable. If Indian payers require external-cause
   codes, this becomes our hardest case too.
3. **Finding candidates is where effort pays off, and we have the weakest search.** The paper's agents
   found 59% of rare codes through about 35 index searches per note. We only have inclusion terms
   (about 9.7k).
4. **Their tool-level gating confirms our design.** Keep the rule that nothing can be output unless
   retrieval or the graph produced it.
5. **Most remaining errors are judgment errors, which our validator is designed for**: coding a symptom
   that's part of a confirmed diagnosis, coding a past condition not treated this stay, and coding
   "vs / probable" diagnoses wrongly.
6. **Neural and LLM approaches complement each other, but the neural one shouldn't go first.** A
   classifier helps common codes, but feeding its suggestions to the agent made strong models search
   less.

---

## 2. Ideas to take into the design

Status for all: **proposed**, not built.

### 2.1 Deterministic companion-code expansion

After codes are chosen, add companion candidates from the graph instead of relying on prompt
instructions:

| Trigger | Companion | Source in our data |
|---|---|---|
| Dagger code chosen | Its asterisk code(s) | `dagger_pairs_with_asterisk` edges |
| Asterisk code chosen | Its dagger code | `asterisk_needs_dagger` edges |
| Code with a "Use additional code …" hint | The referenced code or chapter | `coding_hints` (free text today; needs parsing into edges) |
| Injury code (S00-T98) | A Chapter XX cause code | Chapter XX note |
| Insulin or other long-term drug in discharge meds | Z92.x | Drug lexicon (to build) |

Each companion still needs evidence in the note before it is kept. The point is that the search for
it always happens.

### 2.2 Better candidate search: borrow the ICD-10-CM index

The ICD-10-CM Alphabetical Index, Drug Table, Neoplasm Table and External Cause Index are free US
government files. Use them purely as a search layer:

1. Look up the doctor's term in the CM index → CM code (e.g. E11.621 diabetic foot ulcer).
2. Cut it back to its WHO form (E11.621 → E11.6 → E11) until it matches a code in our WHO knowledge base.
3. Accept the result only as a candidate, which the normal L2/L3 walk then confirms. Here the WHO answer
   is E11.5, not E11.6, so CM → WHO cannot be a direct mapping.

Needs checking first: how often truncation lands on the right WHO category, and where CM and WHO
diverge below the 3-character level.

### 2.3 Allow re-entry instead of a strictly fixed pipeline

Let the L2/L3 agents call search again when a branch dead-ends or when a coding hint points to
another chapter, instead of only walking down the branch L1 chose. Keeps the cost benefits of the
subtree-scoped design while avoiding CodeSeeker's failure mode.

### 2.4 Discovery order as a confidence feature

Record the step at which each candidate was first found and add it to the beam score. Cheap, and the
paper shows it separates correct from wrong codes for every model it tested.

### 2.5 Neural classifier as a separate voter, later

If we get enough labelled Indian discharge summaries to train a classifier, use it as an independent
vote merged at the end, not as the agent's first step.

### 2.6 Evaluation design for our gold set

Copy the paper's evaluation design:

* Split results by code frequency, plus a "companion code" subset (dagger/asterisk, external cause).
* Report a funnel: correct codes found → checked → submitted → exactly right.
* Break down misses by the stage where they were lost.
* 95% bootstrap confidence intervals over notes.
* Measure cost per note (calls, seconds, tokens) and compare with the paper's 57–87 calls and
  65–363 s per note.

---

## 3. Open questions

* Do PM-JAY or private insurers in India require external-cause (Chapter XX) codes, place of
  occurrence or the optional supplementary characters (open/closed fracture, J96 type)?
* Is the ICD-10-CM index (2.2) good enough after truncation, or does it need a hand-built CM → WHO
  map for the most common categories?
* How many labelled discharge summaries can we get, and from how many hospitals?
