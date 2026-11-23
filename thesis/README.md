# Engineering thesis

LaTeX sources of the engineering thesis *„Strumieniowa analiza nastrojów
wokół premier popkulturowych z wykorzystaniem chmury obliczeniowej
i platformy MLOps”* (Gdańsk University of Technology, WETI). The thesis is
written in Polish; file and folder names are English. It lives on the
`inzynierka` branch of the project repository, next to the code it
describes.

## What is where

```
thesis/            ← open THIS folder in VS Code
  chapters/          WRITE HERE — one file per chapter
  figures/           images (PDF from draw.io, PNG for screenshots)
  front/             abstracts (PL, EN)
  acronyms.tex       list of acronyms
  references.bib     bibliography — exported from Zotero, never edited by hand
  main.tex           order of the parts
  playground/        toy document (a soup recipe) for trying things out
  config/            shared settings — rarely touched
    preamble.tex       packages, fonts, typography
    metadata.tex       title, authors, supervisor
    title-page.tex     placeholder title page
    latexindent.yaml   formatting rules
  docs/              how the thesis is assessed (review-criteria.md)
```

The rest of the repository (`dataflow/`, `nlp/`, `docs/`, …) is the project
itself — the source of every fact in the thesis.

## Setup (once)

1. **LaTeX:** TeX Live — Windows: <https://tug.org/texlive/windows.html>;
   Linux: `texlive-full` from the package manager; Mac: MacTeX.
   Anything with **LuaLaTeX** and **biber** works.
2. **VS Code** with the two recommended extensions (VS Code offers them):
   *LaTeX Workshop* (build and PDF preview) and *LTeX+* (Polish grammar).
3. **Zotero 7** with the *Better BibTeX* plugin — see Bibliography below.
4. **Get the branch:** `git fetch && git switch inzynierka`, then in VS Code
   *File → Open Folder… → `thesis`* (the settings live in `thesis/.vscode`).

Check: open `playground/main.tex`; the PDF appears in a tab next to it.

## Writing

- Open a chapter in `chapters/` and press **Ctrl+Alt+V** for the PDF.
- Type. After a 1.5 s pause the file saves itself and the PDF refreshes
  (a few seconds). **Ctrl+click** in the PDF jumps to that line of source.
- **Ctrl+S** also tidies the formatting (indentation, aligned tables).
- **One sentence per line.** The PDF still shows normal paragraphs (an
  empty line starts a new one), and git shows changes sentence by sentence.

## Conventions

- **Font:** one font for everything — TeX Gyre Termes (Times-like), 12 pt,
  set in `config/preamble.tex`. Do not change fonts in the text; use
  `\emph{…}` for emphasis and `\textbf{…}` sparingly.
- **Polish typography:** quotes `\enquote{tekst}` → „tekst”; a dash in a
  sentence ` -- `; ranges `10--20`; decimals `\num{0.87}` → 0,87; units
  `\qty{5}{\liter}`. One-letter words at line ends are handled for you.
- **Figures and tables:** table caption above, figure caption below; every
  one referenced in the text before it appears: `tabela~\ref{tab:…}`.
- **Labels:** English, with a prefix: `chap:`, `sec:`, `fig:`, `tab:`,
  `lst:`, `eq:` — e.g. `\label{fig:pipeline-architecture}`.
- **Acronyms:** add to `acronyms.tex`; in the text `\ac{gcp}` prints the
  short form. Write the first use out by hand in the right case:
  „…platformy Google Cloud (\ac{gcp})…”.
- **Code from the project:** `\lstinputlisting[firstline=…, lastline=…]{../dataflow/pipeline.py}`
  (paths are relative to `thesis/`).
- **Notes for each other:** `\marcin{…}`, `\oskar{…}`, `\kacper{…}`,
  `\supervisor{…}` — coloured margin notes. `\workingdraftfalse` in
  `main.tex` hides them all for the final version.

The playground shows every one of these; its README lists what to try.

## Bibliography

One shared Zotero library generates `references.bib`; nobody edits that
file by hand.

1. Everyone installs Zotero 7, the browser *Zotero Connector* and the
   *Better BibTeX* plugin.
2. One person creates a private **group** on zotero.org and invites the
   others.
3. Better BibTeX settings: citation key formula
   `auth.lower + year + shorttitle(1,0).lower` (keys like
   `akidau2018streaming`).
4. Import the current `references.bib` into the group once.
5. One person exports the group: right-click → *Export Collection…* →
   *Better BibLaTeX*, tick **Keep updated**, save as
   `thesis/references.bib`.

**Adding a source:** Zotero's magic wand → paste a DOI or ISBN. Web pages:
the Zotero Connector button. **Citing:** type `\cite{` and VS Code suggests
the keys; a page: `\cite[s.~12]{key}`.

## Working together

Pull before you start; work on a branch made from `inzynierka` and open a
pull request into `inzynierka` (not `main` — `main` is the project code).

## Still to settle

- Page layout, font size and title page per the PG guidelines (MojaPG).
- Citation style (now numeric `[1]`) — ask the supervisor.
- The chapter outline and who writes what.
