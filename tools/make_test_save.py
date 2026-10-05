#!/usr/bin/env python3
"""Make a play-test save for the GF-ability and All-Magic mods from an existing Steam save.

    make_test_save.py <user_NNN save dir> <source slot file> <target slot file>
    e.g. make_test_save.py ".../FINAL FANTASY VIII Steam/user_<steamid>" slot1_save01.ff8 slot1_save02.ff8

Starting from the source save, it changes only:
  * GFs: Quezacotl and Shiva are obtained (exists bit, as the game's add-GF opcode at 0x47E480
    does). Quezacotl keeps its starting abilities: 22 entries, the vanilla cap. Shiva gets
    23 learned abilities plus 11 still to learn, so 34 entries (4 pages), and is set to be
    learning an ability that sits on page 4.
  * Magic, stored in the All Magic mod's save format (0xFF signature, dense qty[id]): Squall
    (the only party member in the source save) has the 50 spells that can't be drawn near
    Balamb, x100 each (13 menu pages). Drawing Fire/Blizzard/Thunder/Cure/Esuna/Scan adds the
    51st-56th.
  * Items: ability-teaching items and Amnesia Greens.
Then it recomputes the save checksum by running the game's own CRC routine (0x500310), writes
the target slot, and signs it in metadata.xml (md5 of file + Steam user id).

Needs the All Magic mod active to load the magic (vanilla would read garbage slots).
"""
import hashlib
import os
import re
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ff8hext import Image, default_exe, parse_hext  # noqa: E402
from emu import Emu  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAVEMAP = 0x1CFDC58          # in-memory savemap; the file holds it at raw offset 0x180
RAW = 0x180
GF_OFF, GF_SIZE = 0x50, 0x44
CHAR_OFF, CHAR_SIZE = 0x490, 0x98
ITEMS_OFF, ITEM_SLOTS = 0xB44, 198
KERNEL_GF = 0x1CF4DC0
GF_LEVEL = 0x1CFF620
BUILDER = 0x4ACB70
CRC = 0x500310

QUEZACOTL, SHIVA = 0, 1
SQUALL = 0
# ability ids (kernel.bin text order): junction 1-19, commands 20-38, stat% 39-57,
# character 58-77, party 78-82, GF 83-91, menu 92-115
# The Learn list shows learned abilities, then the GF's own abilities whose prerequisite is met.
# Quezacotl learns all of its own: 21 + Draw = 22 entries, the vanilla cap.
# Shiva learns all of its own except four, plus 12 taught extras: 30 learned + 4 to learn = 34.
SHIVA_UNLEARNED = [98, 3, 51, 2]   # I Mag-RF, Vit-J, Spr+20%, Str-J: none has a prerequisite
SHIVA_EXTRA = [1, 4, 6, 7, 9, 25, 31, 33, 60, 62, 64, 65]
SHIVA_LEARNING = 98                 # the builder lists it last (entry 34) -> page 4
NEAR_BALAMB = {1, 4, 7, 21, 27, 50}  # Fire Blizzard Thunder Cure Esuna Scan
# kernel item-name order: battle items 1-32, then non-battle items from 33 (Tent)
TEST_ITEMS = {"Rosetta Stone": 5, "Healing Ring": 3, "Phoenix Spirit": 3, "Hungry Cookpot": 3,
              "Monk's Code": 3, "Knight's Code": 3, "Amnesia Greens": 20, "HP-J Scroll": 3}


# ---- FF8 LZSS (4 KB window, start 0xFEE, flag bit 1 = literal)
def lzss_decompress(data):
    out, win, r, i = bytearray(), bytearray(4096), 0xFEE, 0
    while i < len(data):
        flags = data[i]
        i += 1
        for b in range(8):
            if i >= len(data):
                break
            if flags >> b & 1:
                c = data[i]
                i += 1
                out.append(c)
                win[r] = c
                r = (r + 1) & 0xFFF
            else:
                lo, hi = data[i], data[i + 1]
                i += 2
                off, n = lo | (hi & 0xF0) << 4, (hi & 0xF) + 3
                for k in range(n):
                    c = win[(off + k) & 0xFFF]
                    out.append(c)
                    win[r] = c
                    r = (r + 1) & 0xFFF
    return bytes(out)


def lzss_literal(raw):
    """Valid LZSS made only of literals (the game's decoder doesn't care about ratio)."""
    out = bytearray()
    for i in range(0, len(raw), 8):
        chunk = raw[i:i + 8]
        out.append((1 << len(chunk)) - 1)
        out += chunk
    return bytes(out)


def read_slot(path):
    d = open(path, "rb").read()
    n = struct.unpack_from("<I", d)[0]
    assert n == len(d) - 4, "not an FF8 Steam save"
    return bytearray(lzss_decompress(d[4:]))


# ---- kernel.bin from Data/lang-en/main.fs
def kernel_bin(exe):
    lang = os.path.join(os.path.dirname(exe), "Data", "lang-en")
    names = open(os.path.join(lang, "main.fl"), "rb").read().decode("latin1").splitlines()
    i = next(k for k, n in enumerate(names) if n.lower().endswith("kernel.bin"))
    size, off, comp = struct.unpack_from("<III", open(os.path.join(lang, "main.fi"), "rb").read(), 12 * i)
    with open(os.path.join(lang, "main.fs"), "rb") as fs:
        fs.seek(off)
        if not comp:
            return fs.read(size)
        n = struct.unpack("<I", fs.read(4))[0]
        return lzss_decompress(fs.read(n))[:size]


def kernel_section(k, s):
    n = struct.unpack_from("<I", k)[0]
    offs = list(struct.unpack_from("<%dI" % n, k, 4)) + [len(k)]
    return k[offs[s]:offs[s + 1]]


def ff8_text(b):
    def ch(c):
        if 0x45 <= c <= 0x5E:
            return chr(ord("A") + c - 0x45)
        if 0x5F <= c <= 0x78:
            return chr(ord("a") + c - 0x5F)
        return {0x20: " ", 0x02: "\n"}.get(c, "?")
    return "".join(ch(c) for c in b)


def item_ids(k):
    """name -> id; '?' in kernel names stands for punctuation, so match on letters only."""
    ids = {}
    for sec, first in ((38, 1), (39, 33)):
        for n, raw in enumerate(kernel_section(k, sec).split(b"\0")[0::2]):
            ids[re.sub("[^A-Za-z ]", "", ff8_text(raw))] = first + n
    return ids


def main():
    save_dir, src, dst = sys.argv[1:4]
    exe = default_exe()
    k = kernel_bin(exe)
    raw = read_slot(os.path.join(save_dir, src))
    sm = memoryview(raw)[RAW:RAW + 0x13A4]
    e = Emu(Image(exe))
    e.wb(SAVEMAP, bytes(sm))
    assert e.call(CRC, 0x1350, SAVEMAP + 0x50) & 0xFFFF == struct.unpack_from("<H", sm)[0], \
        "source save checksum does not match the game's CRC"

    # GFs
    gfdata = kernel_section(k, 2)

    def own_abilities(gf):
        return [gfdata[gf * 0x84 + 0x1C + 4 * i + 2] for i in range(21)]

    def learn(gf, abilities):
        g = GF_OFF + gf * GF_SIZE
        sm[g + 0x11] |= 1               # obtained
        for ab in abilities:
            sm[g + 0x14 + ab // 8] |= 1 << (ab % 8)

    learn(QUEZACOTL, own_abilities(QUEZACOTL))
    learn(SHIVA, [a for a in own_abilities(SHIVA) if a not in SHIVA_UNLEARNED] + SHIVA_EXTRA)
    shiva = GF_OFF + SHIVA * GF_SIZE
    sm[shiva + 0x40] = SHIVA_LEARNING

    # magic, All Magic mod format at char+0x10: [0]=0xFF, [id]=qty
    def set_magic(char, qty):
        region = bytearray(64)
        region[0] = 0xFF
        for sid, q in qty.items():
            region[sid] = q
        sm[CHAR_OFF + char * CHAR_SIZE + 0x10:CHAR_OFF + char * CHAR_SIZE + 0x50] = region
    set_magic(SQUALL, {sid: 100 for sid in range(1, 57) if sid not in NEAR_BALAMB})

    # items: top up existing stacks, else use empty slots
    ids = item_ids(k)
    for name, qty in TEST_ITEMS.items():
        iid = ids[re.sub("[^A-Za-z ]", "", name)]
        slots = [ITEMS_OFF + 2 * s for s in range(ITEM_SLOTS)]
        slot = next((a for a in slots if sm[a] == iid), None) or next(a for a in slots if sm[a] == 0)
        sm[slot], sm[slot + 1] = iid, min(100, sm[slot + 1] + qty)

    # check with the patched game code, then checksum with the game's CRC
    img = Image(exe)
    for hext in ("UnlimitedGFAbilities/hext/gf_abilities.hext", "AllMagicPerCharacter/hext/magic.hext"):
        img.apply(parse_hext(open(os.path.join(ROOT, hext)).read()))
    e = Emu(img)
    e.wb(SAVEMAP, bytes(sm))
    e.wb(KERNEL_GF, gfdata)
    for gf in range(16):
        e.w8(GF_LEVEL + gf * 12, 10)
    counts = [e.call(BUILDER, gf, 0x11000000, 1) for gf in (QUEZACOTL, SHIVA)]
    shiva_list = [e.r8(0x11000000 + 8 * i) for i in range(counts[1])]
    print("GF list entries: Quezacotl %d, Shiva %d (learning ability %d is entry %d -> page %d)"
          % (counts[0], counts[1], SHIVA_LEARNING, shiva_list.index(SHIVA_LEARNING),
             shiva_list.index(SHIVA_LEARNING) // 11 + 1))
    assert counts == [22, 34] and shiva_list.index(SHIVA_LEARNING) // 11 + 1 == 4, counts
    crc = e.call(CRC, 0x1350, SAVEMAP + 0x50) & 0xFFFF
    struct.pack_into("<H", sm, 0, crc)
    struct.pack_into("<H", sm, 0x13A0, crc)

    out = struct.pack("<I", len(lzss_literal(bytes(raw)))) + lzss_literal(bytes(raw))
    assert read_slot_bytes(out) == bytes(raw)
    open(os.path.join(save_dir, dst), "wb").write(out)

    # sign it in metadata.xml
    user = re.search(r"user_(\d+)", os.path.abspath(save_dir)).group(1)
    num = int(re.search(r"save(\d+)", dst).group(1))
    slot = int(re.search(r"slot(\d+)", dst).group(1))
    meta_path = os.path.join(save_dir, "metadata.xml")
    meta = open(meta_path, encoding="utf-8", newline="").read()
    sig = hashlib.md5(out + user.encode()).hexdigest()
    pat = re.compile(r'(<savefile num="%d" type="ff8" slot="%d">\s*)<timestamp\s*/>|(<savefile num="%d" type="ff8" '
                     r'slot="%d">\s*)<timestamp>\d*</timestamp>' % (num, slot, num, slot))
    meta, n1 = pat.subn(lambda m: (m.group(1) or m.group(2)) + "<timestamp>%d</timestamp>" % int(time.time() * 1000), meta)
    meta, n2 = re.subn(r'(<savefile num="%d" type="ff8" slot="%d">\s*<timestamp>\d+</timestamp>\s*<signature>)[0-9a-f]*'
                       % (num, slot), lambda m: m.group(1) + sig, meta)
    assert n1 == 1 and n2 == 1, "metadata.xml entry for slot %d save %d not found" % (slot, num)
    open(meta_path, "w", encoding="utf-8", newline="").write(meta)
    print("wrote %s (checksum %04X), signed in metadata.xml" % (dst, crc))


def read_slot_bytes(d):
    return lzss_decompress(d[4:4 + struct.unpack_from("<I", d)[0]])


if __name__ == "__main__":
    main()
