#!/usr/bin/env python3
"""Checks for the combined FF8 Unlimited mod (run tools/build_mod.py first).

1. mod.xml: every ModFolder exists, and every folder with hext has a ModFolder.
2. No two parts write the same bytes, so any combination of options is safe. Within the
   card rules, only choices of the same option (never active together) may overlap.
3. Page numbers: the rewritten 0x4C0370 draws "P.2" and "P.9" exactly as vanilla, and
   "P.12" / "P.16" with both digits; vanilla drops the tens digit. Also checked with every
   part applied, so no other part overwrites the fix.
The per-part logic is checked by verify_magic.py, verify_gf_abilities.py and verify_tt_rules.py.
"""
import glob
import os
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from emu import Emu, page_header_sprites, PAGE_HEADER_EXPECT  # noqa: E402
from ff8hext import Image, default_exe, parse_hext  # noqa: E402

MOD = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "FF8Unlimited"))
checks = 0


def ok(cond, msg):
    global checks
    if not cond:
        raise AssertionError(msg)
    checks += 1


def hext_ops(folder):
    ops = []
    for f in sorted(glob.glob(os.path.join(MOD, folder, "hext", "*.hext"))):
        ops += parse_hext(open(f).read())
    return ops


def spans(ops):
    return [(a, a + len(b)) for t, a, b in [o for o in ops if o[0] == "w"]]


def overlaps(s1, s2):
    return [(a, b) for a in s1 for b in s2 if a[0] < b[1] and b[0] < a[1]]


def main():
    exe = sys.argv[1] if len(sys.argv) > 1 else default_exe()
    root = ET.parse(os.path.join(MOD, "mod.xml")).getroot()
    folders = [f.get("Folder").replace("\\", "/") for f in root.findall("ModFolder")]
    for f in folders:
        ok(glob.glob(os.path.join(MOD, f, "hext", "*.hext")), "ModFolder %s has no hext" % f)
    on_disk = {os.path.relpath(os.path.dirname(os.path.dirname(p)), MOD).replace(os.sep, "/")
               for p in glob.glob(os.path.join(MOD, "**", "hext", "*.hext"), recursive=True)}
    ok(on_disk == set(folders), "folders with hext but no ModFolder (or the reverse): %s" % (on_disk ^ set(folders)))
    ok(not glob.glob(os.path.join(MOD, "hext", "*")), "nothing may load unconditionally from the mod root")

    parts = {p: spans(hext_ops("options/" + p)) for p in ("AllMagic", "GFAbilities", "PageNumbers", "CardRules")}
    card_opts = [f for f in folders if f.startswith("options/CardRules/options/")]
    parts["CardRules"] += [s for f in card_opts for s in spans(hext_ops(f))]
    names = list(parts)
    for i, p in enumerate(names):
        for q in names[i + 1:]:
            ok(not overlaps(parts[p], parts[q]), "%s and %s write the same bytes: %s" % (p, q, overlaps(parts[p], parts[q])[:3]))
    rule = {f: re.sub(r"_[A-Za-z]+$", "", f) for f in card_opts}   # Open_On/Open_Off, Trade_One/Trade_All...
    for i, f in enumerate(card_opts):
        for g in card_opts[i + 1:]:
            if rule[f] != rule[g]:
                ok(not overlaps(spans(hext_ops(f)), spans(hext_ops(g))), "%s and %s overlap" % (f, g))

    vanilla = Image(exe)
    ok(page_header_sprites(Emu(vanilla), 11) == [(0x32, 100), (0x2A, 109)], "vanilla page 12 should draw only '2'")
    alone = Image(exe)
    alone.apply(hext_ops("options/PageNumbers"))
    full = Image(exe)
    for p in ("AllMagic", "GFAbilities", "PageNumbers", "CardRules"):
        full.apply(hext_ops("options/" + p))
    for img, label in ((alone, "page numbers alone"), (full, "all parts")):
        for page, expect in PAGE_HEADER_EXPECT.items():
            got = page_header_sprites(Emu(img), page)
            ok(got == expect, "%s: page %d drew %s" % (label, page + 1, got))
    print("OK: %d checks passed (%d folders, parts: %s)" % (checks, len(folders), ", ".join(
        "%s %d writes" % (p, len(s)) for p, s in parts.items())))


if __name__ == "__main__":
    main()
