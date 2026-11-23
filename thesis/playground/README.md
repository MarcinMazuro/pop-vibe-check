# playground — a toy document for learning the setup

A small LaTeX document ("Rosół według przepisu babci") that loads the
thesis's own preamble (`../config/preamble.tex`), so it looks and behaves
exactly like the thesis. It is **not** part of the thesis: break it, change
it, try things here before using them for real.

The bibliography (`references.bib`) is **fictional** — none of those works
exist. Real sources come from the team's Zotero library only.

## Build

Needs a LaTeX distribution with LuaLaTeX and biber (TeX Live recommended).
In this folder:

```
latexmk          # builds build/main.pdf
latexmk -pvc     # rebuilds on every save
latexmk -c       # removes auxiliary files
```

In VS Code, open any file here and press Ctrl+Alt+V for the PDF. Type, pause
for a moment — the file saves itself and the PDF refreshes. Ctrl+click in
the PDF jumps to the source line.

## What to try

| Feature | Where | Try |
|---|---|---|
| One sentence per line | `chapters/introduction.tex` | Change one word, look at `git diff` |
| Citations | `\cite{babcia1987zupy}` | Add a page: `\cite[s.~12]{…}` |
| Polish quotes, dashes | `\enquote{…}`, ` -- `, `2--3` | Compare with `"…"` and `-` |
| One-letter words at line end | any paragraph | Nothing to do — `luavlna` handles them |
| Table + decimal comma | `chapters/ingredients.tex` | Change `1.50` to `1.75`, see `1,75` |
| Units | `\qty{5}{\liter}` | Try `\qty{0.5}{\kilo\gram}` |
| Acronyms (variant B) | `\ac{tp}` | First use written out by hand, then `\ac{tp}` |
| Author notes | `\oskar{…}`, `\marcin{…}`, `\kacper{…}`, `\supervisor{…}` | Set `\workingdraftfalse` in `main.tex` — all notes disappear |
| Figure | TikZ in `chapters/cooking.tex` | Swap in `\includegraphics[width=0.6\textwidth]{example-image}` |
| Equation + reference | `\eqref{eq:time}` | Add a second equation and reference it |
| Code from a file | `\lstinputlisting{scripts/scale_recipe.py}` | Edit the script, rebuild |
| Lists of figures/tables/listings | end of `main.tex` | Add a table, see it appear |

Captions: a table's caption goes **above** it, a figure's **below** — and
every table, figure and listing is referenced in the text before it appears
(the reviewer checks this).
