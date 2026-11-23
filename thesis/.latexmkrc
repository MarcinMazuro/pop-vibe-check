# latexmk settings for the thesis. VS Code runs this on every save; by hand:
#   latexmk          build build/main.pdf
#   latexmk -c       remove auxiliary files
@default_files = ('main.tex');
$pdf_mode = 4;            # LuaLaTeX
$lualatex = 'lualatex -file-line-error -interaction=nonstopmode -synctex=1 %O %S';
$bibtex_use = 2;          # biber
$out_dir = 'build';

# Shared settings live in config/ (preamble, metadata, title page).
ensure_path('TEXINPUTS', './config//');

# \include{chapters/...} writes build/chapters/*.aux — the folder must exist.
use File::Path qw(make_path);
make_path("$out_dir/chapters", "$out_dir/front");
