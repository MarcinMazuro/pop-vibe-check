# latexmk settings for the playground. VS Code runs this on every save.
@default_files = ('main.tex');
$pdf_mode = 4;            # LuaLaTeX
$lualatex = 'lualatex -file-line-error -interaction=nonstopmode -synctex=1 %O %S';
$bibtex_use = 2;          # biber
$out_dir = 'build';

# The shared preamble lives in ../config.
ensure_path('TEXINPUTS', '../config//');

use File::Path qw(make_path);
make_path("$out_dir/chapters");
