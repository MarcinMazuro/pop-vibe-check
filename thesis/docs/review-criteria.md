# How the thesis is assessed

What the reviewer and the supervisor look at, and what that means for this thesis. Based on the PG thesis review form ("Recenzja pracy dyplomowej") and the diploma seminar on reviews (2026-11-18).

## How the grade is formed

- The **supervisor** and the **reviewer** each grade the thesis on a verbal scale (dostateczny … bardzo dobry). The thesis grade combines both and is rounded, not averaged arithmetically — e.g. "dobry plus" + "bardzo dobry" gives "bardzo dobry".
- The **diploma exam** has three questions; the committee grades each one by consensus.
- The final result weighs the grade average from the studies most; the thesis grade and the exam grade weigh less.

## The review form

Sections 1.1 and 1.2 are not written by the reviewer — they come from MojaPG, set by the supervisor. **The review starts at 1.3.**

| Section | What it covers | Weight |
|---|---|---|
| 1.1 Cel pracy | Goal of the thesis — filled in by the supervisor | — |
| 1.2 Charakter pracy | Type: project / theoretical / experimental / literature review / software — filled in by the supervisor | — |
| 1.3 Stopień realizacji celu i poprawność rozwiązania | Was the stated goal fully delivered, and is the solution correct | **highest — decides the grade** |
| 1.4 Sprawność posługiwania się narzędziami i metodami | Command of tools and methods of the field | almost always rated well |
| 1.5 Znaczenie uzyskanego rozwiązania | Originality, innovation, usefulness | subjective |
| 2.1 Konstrukcja pracy | Structure, completeness, readability | formal — small deductions |
| 2.2 Sposób opisania przedmiotu pracy | Language (terminology, grammar, spelling, punctuation) and editorial requirements | formal — small deductions |
| 2.3 Trafność doboru literatury | Number, kind and currency of sources | depends on the type of thesis |
| 3.1 Mocne i słabe strony | Strengths and weaknesses, a few sentences | — |

## What the reviewer checks, section by section

### 1.3 Delivering the goal (most important)

- The goal and the detailed tasks are stated clearly in the introduction, and each task has a visible delivery and evaluation later in the thesis.
- **The goal can differ from the topic card.** Only the title is fixed; nobody but the supervisor sees the topic card. When the thesis is submitted, the supervisor sets the final goal in MojaPG. A task that was dropped can be removed from the goal — with the supervisor's agreement. A goal left in the form but not delivered lowers the grade sharply.
- Results must be correct and explained. A suspicious or impossible result that is not investigated is a serious complaint (example from the seminar: an error metric above its theoretical maximum, interpreted in one sentence).

### 1.4 Tools and methods

- Rated by what was built and how: the stack used, automation, reproducibility.
- For machine-learning work, "done by the book" means: a correct train/validation/test split with no data leakage, several runs with different random seeds, and reporting the median (or mean) rather than a single run.

### 1.5 Significance

- For an engineering thesis: **usefulness**. Who can use it, what problem it solves.
- **A public GitHub repository is valued explicitly** — others can reproduce and continue the work. Give the link in the thesis.

### 2.1 Structure

- Complete: nothing expected is missing. For an engineering thesis that means a **chapter reviewing the technologies used in industry** for this kind of problem, and a justification of the choices made against the alternatives.
- Key elements illustrated with **figures and tables**.
- The **last section of the introduction describes the structure of the thesis**: every chapter except the first, about three sentences each.

### 2.2 Language and editorial requirements

- Readable: the reviewer should not have to guess what a sentence means.
- Domain terminology used correctly and **consistently**: define a term once, then keep using that one term — no rotating synonyms for the same thing.
- Every table, figure and listing has a number and a title, is **referenced in the text, and the reference comes before the object**.
- Lists of figures and tables and the bibliography are present.

### 2.3 Literature

- **The introduction must cite literature.** Every general claim ("X is becoming important", "methods fall into four groups", "existing approaches have limitations") needs a source. An introduction without citations was the most common complaint at the seminar — up to half a grade off.
- What counts as good literature depends on the type of thesis:
  - research-oriented parts: recent scientific papers;
  - engineering parts: **books** describing the technologies and frameworks (older books are fine when the technology is stable).
- A systematic literature review (search strings, screening) is expected in a master's thesis, **not** in an engineering one.
- Finding sources: Scopus through the MojaPG account; full texts from IEEE, ACM, Springer and Elsevier through the university access.

### 3.1 Strengths and weaknesses

The reviewer always lists some weaknesses. Make the strengths easy to name: goal delivered, reproducible public repo, solid evaluation.

## How reviewers read

A reviewer rarely reads the whole thesis. They **read the introduction carefully**, skim the review chapters, and look at figures and tables. Put the most effort into the introduction, the goal, the evaluation and the figures.

## Checks specific to this thesis

- [ ] **Emotion classification.** Task 1 on the topic card says "klasyfikacja sentymentu i emocji". If emotion classification is not delivered, agree a changed goal with the supervisor before submission.
- [ ] **Terminology.** The title says "nastroje", the goal says "sentyment". Define both early and use them consistently.
- [ ] **Justify each technology choice** against alternatives: Pub/Sub vs Kafka, Beam/Dataflow vs Flink/Spark, MLflow vs other trackers, Terraform vs other IaC tools, Looker Studio vs other dashboards, Steam instead of Reddit (ADR 0001).
- [ ] **Model evaluation rigour:** several seeds, median, test set untouched during training, no leakage between splits.
- [ ] **Explain anomalies**, e.g. the 3 of 10,811 records whose label changed between replays through the Vertex Endpoint.
- [ ] **Link the public repository** (github.com/MarcinMazuro/pop-vibe-check) and describe how to reproduce the results.
- [ ] Introduction: many citations; ends with the structure of the thesis.
