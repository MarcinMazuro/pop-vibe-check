-- listings only knows 8-bit characters. Under LuaLaTeX a character above
-- U+00FF in a code file bypasses listings and is typeset directly: it even
-- leaks out of the lines that firstline= skips, as a stray first line of
-- dashes. While a listing is being read, such characters are replaced with
-- ASCII. Loaded from preamble.tex; switched on and off by listings hooks.

local map = {
  ["\u{2014}"] = "--",  -- em dash
  ["\u{2013}"] = "-",   -- en dash
  ["\u{2026}"] = "...", -- ellipsis
  ["\u{2018}"] = "'", ["\u{2019}"] = "'",
  ["\u{201C}"] = '"', ["\u{201D}"] = '"',
  ["\u{00D7}"] = "x",
  ["\u{2192}"] = "->", ["\u{2190}"] = "<-",
  ["\u{2265}"] = ">=", ["\u{2264}"] = "<=",
  ["\u{00A0}"] = " ",
}

function pvc_listings_ascii(line)
  return (line:gsub(utf8.charpattern, function(c)
    if #c > 1 then
      return map[c] or "?"
    end
  end))
end

local active = false

function pvc_listings_on()
  if not active then
    luatexbase.add_to_callback("process_input_buffer", pvc_listings_ascii, "pvc_listings_ascii")
    active = true
  end
end

function pvc_listings_off()
  if active then
    luatexbase.remove_from_callback("process_input_buffer", "pvc_listings_ascii")
    active = false
  end
end
