#!/usr/bin/env python3
"""Check other Junction VIII hext mods against FF8 Unlimited (run tools/build_mod.py first).

    compat_check.py <mod.zip | mod.iroj | unpacked mod folder> ...

For every hext file in the other mod (Junction VIII "ADDR = bytes" format with "+base"
lines, as FFNx-style hext/ff8/<lang>/ folders use), it reports:
  * bytes that one of our parts also writes (order-dependent: the last mod applied wins),
  * writes inside functions the All Magic part replaces with its own (they would be dead code),
  * code or data that references our memory regions,
  * code that reads magic from the old savemap / battle-table locations, which the All Magic
    part no longer keeps current.
Only the patch files are read; nothing from the other mod is run.

Last run (2026-10-06) on Cronos 0.7 and FF8 Gameplay Customizer 0.5: only their "Junction value
rework" options conflict, see OTHER_MODS in build_mod.py.
"""
import glob
import io
import lzma
import os
import re
import struct
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ff8hext import parse_hext  # noqa: E402

MOD = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "FF8Unlimited", "options"))
RUNTIME = {"AllMagic": [(0x24B5000, 0x24B7A00), (0x25D5000, 0x25D7980)], "GFAbilities": [(0x400400, 0x400860)]}
# functions the All Magic part jumps away from at entry (or the replaced span)
REPLACED = {"add_magic": (0x4C2C70, 0x4C2D1F), "can_receive": (0x4D9000, 0x4D90DB),
            "battle_to_savemap": (0x486CD0, 0x486D8F), "battle_rand_spell": (0x4837E0, 0x483854),
            "battle_rand_spell40": (0x483D85, 0x483DFA), "swap_junctions": (0x4CB4A0, 0x4CB5BE)}
SAVEMAG = 0x1CFE0E8          # char 0; magic slots at +0x10, 64 bytes, stride 0x98, 8 chars
BATTLE = 0x1CFF000           # battle actor structs, stride 0x1D0; magic table at +0x82, 0xA0 bytes


def old_magic(v):
    if SAVEMAG <= v < SAVEMAG + 8 * 0x98 and 0x10 <= (v - SAVEMAG) % 0x98 < 0x50:
        return "old savemap magic slots"
    if BATTLE <= v < BATTLE + 24 * 0x1D0 and 0x82 <= (v - BATTLE) % 0x1D0 < 0x122:
        return "old battle magic table"
    return None


# ---- Junction VIII .iroj archives (AppWrapper/IrosArc.cs)
def iro_files(blob):
    f = io.BytesIO(blob)
    sig, ver, _flags, directory = struct.unpack("<4i", f.read(16))
    assert sig == 0x534F5249, "not an IRO archive"
    f.seek(directory)
    n = struct.unpack("<i", f.read(4))[0]
    if n == -1:
        f.seek(struct.unpack("<q", f.read(8))[0])
        n = struct.unpack("<i", f.read(4))[0]
    for _ in range(n):
        pos = f.tell()
        ln, flen = struct.unpack("<HH", f.read(4))
        name = f.read(flen).decode("utf-16-le")
        flags = struct.unpack("<i", f.read(4))[0]
        off = struct.unpack("<i" if ver < 0x10001 else "<q", f.read(4 if ver < 0x10001 else 8))[0]
        size = struct.unpack("<i", f.read(4))[0]
        f.seek(pos + ln)
        if name.lower().endswith(".hext"):
            here = f.tell()
            f.seek(off)
            if flags & 3 == 0:
                data = f.read(size)
            else:
                assert flags & 3 == 2, "LZS-compressed entry %s not supported" % name
                dec, ps = struct.unpack("<ii", f.read(8))
                p = f.read(ps)
                filt = {"id": lzma.FILTER_LZMA1, "lc": p[0] % 9, "lp": p[0] // 9 % 5, "pb": p[0] // 45,
                        "dict_size": struct.unpack("<I", p[1:5])[0]}
                data = lzma.LZMADecompressor(lzma.FORMAT_RAW, filters=[filt]).decompress(f.read(size - ps - 8), dec)
            f.seek(here)
            yield name.replace("\\", "/"), data.decode("utf-8", "replace")


def hext_files(path):
    if os.path.isdir(path):
        for p in glob.glob(os.path.join(path, "**", "*.hext"), recursive=True):
            yield os.path.relpath(p, path), open(p, encoding="utf-8", errors="replace").read()
        return
    blob = open(path, "rb").read()
    if blob[:4] == b"IROS":
        yield from iro_files(blob)
        return
    z = zipfile.ZipFile(io.BytesIO(blob))
    for n in z.namelist():
        if n.lower().endswith(".iroj"):
            yield from iro_files(z.read(n))
        elif n.lower().endswith(".hext"):
            yield n, z.read(n).decode("utf-8", "replace")


def writes(text):
    base, out = 0, []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        m = re.fullmatch(r"\+\s*([0-9A-Fa-f]+)", line)
        if m:
            base = int(m.group(1), 16)
            continue
        m = re.fullmatch(r"([0-9A-Fa-f]+)\s*=\s*((?:[0-9A-Fa-f]{2}\s*)+)", line)
        if m:
            out.append((base + int(m.group(1), 16), bytes.fromhex(re.sub(r"\s", "", m.group(2)))))
    return out


def ours():
    parts = {}
    for part in ("AllMagic", "GFAbilities", "PageNumbers", "CardRules"):
        spans = []
        for f in glob.glob(os.path.join(MOD, part, "**", "*.hext"), recursive=True):
            spans += [(a, a + len(b)) for t, a, b in [o for o in parse_hext(open(f).read()) if o[0] == "w"]]
        parts[part] = spans
    return parts


def main():
    parts = ours()
    mem = [(s, e, p) for p, rs in RUNTIME.items() for s, e in rs] + [(s, e, p) for p, rs in parts.items() for s, e in rs]
    found = 0
    for path in sys.argv[1:]:
        print("== %s" % path)
        for name, text in hext_files(path):
            msgs = []
            for a, b in writes(text):
                end = a + len(b)
                for p, rs in parts.items():
                    for s, e in rs:
                        if a < e and s < end:
                            msgs.append("writes %X-%X, which %s also writes (%X-%X)" % (a, end, p, s, e))
                for k, (s, e) in REPLACED.items():
                    if s <= a < e:
                        msgs.append("writes %X inside %s, which All Magic replaces (dead code)" % (a, k))
                for i in range(len(b) - 3):
                    v = struct.unpack_from("<I", b, i)[0]
                    for s, e, p in mem:
                        if s <= v < e and not (s <= a + i < e):
                            msgs.append("code at %X references %X (%s memory)" % (a + i, v, p))
                    what = old_magic(v)
                    if what:
                        msgs.append("code at %X reads %X (%s, stale with All Magic on)" % (a + i, v, what))
            for m in sorted(set(msgs)):
                print("  %s: %s" % (name, m))
            found += bool(msgs)
    print("%d hext file(s) with findings" % found)


if __name__ == "__main__":
    main()
