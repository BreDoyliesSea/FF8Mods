"""Checks the Unlimited GF Abilities hext against the real FF8_EN.exe.

1. Static: the hext parses as Junction VIII would and matches the builder's patch list.
   No branch or jump table in .text lands inside a patched instruction range.
2. Dynamic (Unicorn): runs the game's own functions on a synthetic savegame where GF 0
   knows 40 abilities and can learn 11 more (51 entries), against vanilla and patched
   images:
     - the list builder returns all 51 entries, writes nothing past the full-list buffer
     - menu thunks fill the 22-entry window and its count, then paging slides the window
       across every page and stops at both ends; page numbers and arrows follow
     - the GF menu opens on the ability being learned even when it is entry 45
     - the junction GF info popup flips sets of 22 with Left/Right
     - the enlarged stack-frame functions see abilities past the 22nd and return with
       the stack intact
     - teaching an item ability to a GF that already has 51 entries succeeds
"""
import os
import struct
import sys

import capstone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_gf_abilities as B  # noqa: E402
from emu import Emu  # noqa: E402
from ff8hext import Image, parse_hext, default_exe  # noqa: E402

HEXT = os.path.join(os.path.normpath(B.ROOT), "hext", "gf_abilities.hext")
GF_BASE = 0x1CFDCA8
GF_SIZE = 0x44
KERNEL_GF = 0x1CF4DC0
GF_LEVEL = 0x1CFF620
LEARNED = list(range(1, 41))           # 40 learned abilities
LEARNABLE = list(range(50, 61))        # 11 more the GF can still learn
checks = 0


def ok(cond, msg):
    global checks
    if not cond:
        raise AssertionError(msg)
    checks += 1


def images(exe):
    vanilla = Image(exe)
    patched = Image(exe)
    ops = parse_hext(open(HEXT).read())
    patched.apply(ops)
    return vanilla, patched, ops


def static_checks(exe, vanilla, ops):
    code, L, patches = B.build(exe)   # also regenerates the hext, so it must be identical
    ops2 = parse_hext(open(HEXT).read())
    ok(ops == ops2, "hext is not reproducible")
    writes = {(a, bytes(b)) for t, a, b in [o for o in ops if o[0] == "w"]}
    for a, b, _ in patches:
        ok((a, b) in writes, "patch %08X missing from hext" % a)
    # code ranges we overwrite inside existing functions
    ranges = [(a, a + len(b)) for a, b, _ in patches]
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    lo, hi = 0x401000, 0x401000 + 0x768000
    text = vanilla.read(lo, hi - lo)
    targets = set()
    a = lo
    while a < hi:
        last = a
        for i in md.disasm(text[a - lo:min(a - lo + 0x10000, hi - lo)], a):
            last = i.address + i.size
            if i.mnemonic in ("call", "jmp") or i.mnemonic.startswith("j"):
                try:
                    targets.add(int(i.op_str, 16))
                except ValueError:
                    pass
        a = last if last > a else a + 1
    for k in range(0, len(text) - 3):
        v = struct.unpack_from("<I", text, k)[0]
        if lo <= v < hi:
            targets.add(v)
    for s, e in ranges:
        bad = [t for t in targets if s < t < e]
        ok(not bad, "branch target inside patched range %08X-%08X: %s" % (s, e, [hex(t) for t in bad]))
    return L


def setup_save(e, learned=LEARNED, learnable=LEARNABLE, gf=0, level=10):
    g = GF_BASE + gf * GF_SIZE
    e.w8(g + 0x11, 1)                          # exists
    bits = bytearray(16)
    for ab in learned:
        bits[ab // 8] |= 1 << (ab % 8)
    e.wb(g + 0x14, bits)
    e.wb(g + 0x24, bytes(24))                  # APs
    e.w32(g + 0x40, 0)                         # learning + forgotten bits
    k = KERNEL_GF + gf * 0x84
    for s in range(21):
        if s < len(learnable):
            e.wb(k + 0x1C + 4 * s, bytes([0, 0xFF, learnable[s], 0]))
        else:
            e.wb(k + 0x1C + 4 * s, bytes([0xFF, 0xFF, 0, 0]))
    e.w8(GF_LEVEL + gf * 12, level)


def blank_kernel(e):
    for gf in range(16):
        k = KERNEL_GF + gf * 0x84
        for s in range(21):
            e.wb(k + 0x1C + 4 * s, bytes([0xFF, 0xFF, 0, 0]))


def entries(e, addr, n):
    return [e.rb(addr + 8 * i, 8) for i in range(n)]


def test_builder(vanilla, patched):
    for img, expect in ((vanilla, 22), (patched, 51)):
        e = Emu(img)
        blank_kernel(e)
        setup_save(e)
        buf = 0x11000000
        e.watch = (buf, buf + 0x10000)
        n = e.call(B.BUILDER, 0, buf, 1)
        ok(n == expect, "builder returned %d, expected %d" % (n, expect))
        ids = [x[0] for x in entries(e, buf, n)]
        ok(ids == (LEARNED + LEARNABLE)[:expect], "builder order/content wrong: %s" % ids)
        ok(all(a + s <= buf + 8 * n for a, s in e.writes), "builder wrote past its entries")
    # learned-only list
    e = Emu(patched)
    blank_kernel(e)
    setup_save(e)
    n = e.call(B.BUILDER, 0, 0x11000000, 0)
    ok(n == 40, "learned-only list has %d entries" % n)


def menu_emu(patched):
    e = Emu(patched)
    blank_kernel(e)
    setup_save(e)
    return e


def window_ids(e, ctx):
    win, cnt, _ = B.MENUS[ctx]
    n = e.r32(cnt)
    return [x[0] for x in entries(e, win, n)]


ALL = LEARNED + LEARNABLE


def test_gf_menu(patched, L):
    e = menu_emu(patched)
    total = e.call(L["gfm_build"], 0, B.MENUS[B.CTX_GFM][0], 1)
    ok(total == 51, "gfm_build returned %d" % total)
    ok(window_ids(e, B.CTX_GFM) == ALL[:22], "GF window after build")
    task = 0x11008000
    e.wb(task, bytes(0x80))
    # page 0 + Right -> vanilla page turn
    e.w8(task + 0x36, 0)
    ok(e.run_until(L["gf_next"], {0x4D2C14, 0x4D2C48, 0x4D2C56}, regs=dict(esi=task)) == 0x4D2C14, "page0 Right should take vanilla path")
    # page 1 + Right repeatedly slides by 11 until the end
    e.w8(task + 0x36, 1)
    for w in (11, 22, 33):
        stop = e.run_until(L["gf_next"], {0x4D2C14, 0x4D2C48, 0x4D2C56}, regs=dict(esi=task))
        ok(stop == 0x4D2C48, "slide to W=%d did not exit through page-turn path" % w)
        ok(e.r32(B.CTX_GFM + B.W) == w, "W=%d expected, got %d" % (w, e.r32(B.CTX_GFM + B.W)))
        ok(window_ids(e, B.CTX_GFM) == ALL[w:w + 22], "window content at W=%d" % w)
        ok(e.r32(task + 0x36) & 0xFF == 1, "page must stay 1")
    stop = e.run_until(L["gf_next"], {0x4D2C14, 0x4D2C48, 0x4D2C56}, regs=dict(esi=task))
    ok(stop == 0x4D2C56 and e.r32(B.CTX_GFM + B.W) == 33, "Right on the final page must do nothing")
    # page number / arrows on the last page (W=33, page 1): logical page 4 of 5 shown as 4 -> 4+1 drawn by game
    e.setreg("ecx", 1)
    e.call(L["gf_pnum"], regs=dict(ecx=1))
    ok(e.reg("ecx") == 1 + 3, "page number at W=33 page 1")
    e.call(L["gf_arrows"], regs=dict(ecx=1))
    ok(e.reg("ecx") == 1, "last page shows only the left arrow")
    e.call(L["gf_arrows"], regs=dict(ecx=0))
    ok(e.reg("ecx") == 3, "W>0 page 0 shows both arrows")
    # Left on page 0 slides back
    e.w8(task + 0x36, 0)
    for w in (22, 11, 0):
        stop = e.run_until(L["gf_prev"], {0x4D2C6A, 0x4D2CA3, 0x4D399A}, regs=dict(esi=task))
        ok(stop == 0x4D2CA3 and e.r32(B.CTX_GFM + B.W) == w, "slide back to W=%d" % w)
        ok(window_ids(e, B.CTX_GFM) == ALL[w:w + 22], "window content at W=%d (back)" % w)
    stop = e.run_until(L["gf_prev"], {0x4D2C6A, 0x4D2CA3, 0x4D399A}, regs=dict(esi=task))
    ok(stop == 0x4D399A, "Left on first page does nothing")
    e.call(L["gf_arrows"], regs=dict(ecx=0))
    ok(e.reg("ecx") == 2, "first page shows only the right arrow")
    e.w8(task + 0x36, 1)
    ok(e.run_until(L["gf_prev"], {0x4D2C6A, 0x4D2CA3, 0x4D399A}, regs=dict(esi=task)) == 0x4D2C6A, "page1 Left is vanilla")
    # locate: GF is learning entry 45 (ability 55)
    e.w8(task + 0x31, 0)
    target = ALL.index(55)
    stop = e.run_until(L["gf_locate"], {0x4D33AE}, regs=dict(esi=task, ecx=55))
    w = e.r32(B.CTX_GFM + B.W)
    idx, cnt = e.reg("eax"), e.reg("ebp")
    ok(stop == 0x4D33AE and w <= target < w + 22 and idx == target - w and idx < cnt, "locate: W=%d idx=%d cnt=%d" % (w, idx, cnt))
    ok(window_ids(e, B.CTX_GFM)[idx] == 55, "located entry is the learning ability")
    stop = e.run_until(L["gf_locate"], {0x4D33AE}, regs=dict(esi=task, ecx=0x7E))
    ok(e.reg("eax") == e.reg("ebp"), "locate: missing ability reports not-found")
    # small list: no sliding at all
    setup_save(e, learned=list(range(1, 6)), learnable=[50, 51])
    total = e.call(L["gfm_build"], 0, B.MENUS[B.CTX_GFM][0], 1)
    ok(total == 7 and e.r32(B.MENUS[B.CTX_GFM][1]) == 7, "small list")
    e.w8(task + 0x36, 1)
    ok(e.run_until(L["gf_next"], {0x4D2C14, 0x4D2C48, 0x4D2C56}, regs=dict(esi=task)) == 0x4D2C56, "no slide for short list")


def test_item_menu(patched, L):
    e = menu_emu(patched)
    e.stub(B.SOUND)
    n = e.call(L["itm_build_reset"], 0, B.MENUS[B.CTX_ITM][0], 1)
    ok(n == 22 and window_ids(e, B.CTX_ITM) == ALL[:22], "item window after open")
    task = 0x11008000
    stops = {0x4FAB05, 0x4FAB17}
    ok(e.run_until(L["it_next"], stops, regs=dict(ebx=0, esi=task)) == 0x4FAB17 and e.r32(task + 0x10) & 0xFFFF == 0x48,
       "item: Right on page 0 starts vanilla page turn")
    for w in (11, 22, 33):
        e.run_until(L["it_next"], stops, regs=dict(ebx=1, esi=task))
        ok(e.r32(B.CTX_ITM + B.W) == w and window_ids(e, B.CTX_ITM) == ALL[w:w + 22], "item slide W=%d" % w)
        ok(e.reg("ebx") == 1, "item: ebx (page) preserved")
    e.run_until(L["it_next"], stops, regs=dict(ebx=1, esi=task))
    ok(e.r32(B.CTX_ITM + B.W) == 33, "item: stops at the end")
    e.call(L["it_pnum"], regs=dict(ecx=1, ebp=0x100))
    ok(e.reg("eax") == 4 and e.reg("ebp") == 0x128, "item page number / ebp adjust")
    for w in (22, 11, 0):
        e.run_until(L["it_prev"], stops, regs=dict(ebx=0, esi=task))
        ok(e.r32(B.CTX_ITM + B.W) == w, "item slide back W=%d" % w)
    e.w32(task + 0x10, 0)
    ok(e.run_until(L["it_prev"], stops, regs=dict(ebx=1, esi=task)) == 0x4FAB05 and e.r32(task + 0x10) & 0xFFFF == 0x46,
       "item: Left on page 1 is vanilla")
    # rebuild after forgetting keeps the window, then the scan helper exposes the full list
    e.w32(B.CTX_ITM + B.W, 22)
    n = e.call(L["itm_build_keep"], 0, B.MENUS[B.CTX_ITM][0], 1)
    ok(e.r32(B.CTX_ITM + B.W) == 22 and n == 22, "keep window on rebuild")
    e.call(L["itm_scanprep"])
    ok(e.reg("eax") == B.FULL and e.reg("ecx") == 51, "scanprep")
    # a different GF resets the window
    setup_save(e, gf=3, learned=list(range(1, 30)), learnable=[])
    e.call(L["itm_build_keep"], 3, B.MENUS[B.CTX_ITM][0], 1)
    ok(e.r32(B.CTX_ITM + B.W) == 0, "keep resets for another GF")


def test_junction_info(patched, L):
    e = menu_emu(patched)
    e.stub(B.SOUND)
    n = e.call(L["jnf_build"], 0, B.MENUS[B.CTX_JNF][0], 0)
    ok(n == 22 and window_ids(e, B.CTX_JNF) == LEARNED[:22], "junction info window")
    sp = 0x10EFE000
    e.w32(sp + 4 + 0x18, 0x77)  # caller's [esp+18] (bl source), seen by the cave at [esp+1C]
    for keys, w in ((0x2000, 22), (0x2000, 22), (0x8000, 0), (0x8000, 0)):
        e.w32(B.KEYS, keys)
        e.w32(sp, 0x0FFF0000)
        e.setreg("ebx", 0xAABBCC00)
        e.run_until(L["jnf_input"], {0x0FFF0000}, esp=sp)
        ok(e.r32(B.CTX_JNF + B.W) == w, "junction info W=%d after keys %X" % (w, keys))
        ok(e.reg("ebx") == 0xAABBCC77 and e.reg("edi") == 0x47, "junction info: bl/edi as original code")
        ok(window_ids(e, B.CTX_JNF) == LEARNED[w:w + 22], "junction info window W=%d" % w)


def test_frames(vanilla, patched):
    many = LEARNED + [0x60, 0x70]       # menu abilities past the 22nd learned entry
    for img, patched_img in ((vanilla, False), (patched, True)):
        e = Emu(img)
        blank_kernel(e)
        setup_save(e, learned=many, learnable=[], level=37)
        # 0x4C2B40: bitmask of learned menu abilities 0x5C..0x73 over all GFs
        e.call(0x4C2B40)
        mask = e.r32(0x1D772F4)
        exp = (1 << (0x60 - 0x5C)) | (1 << (0x70 - 0x5C))
        ok((mask == exp) if patched_img else (mask == 0), "4C2B40 mask %X (patched=%s)" % (mask, patched_img))
        # 0x4D7110(ability): highest level of a GF that knows it
        lvl = e.call(0x4D7110, 0x70)
        ok(lvl == (37 if patched_img else 0), "4D7110 -> %d (patched=%s)" % (lvl, patched_img))
        # 0x4B2EB0: learns every learnable ability whose AP is full (all, here)
        e2 = Emu(img)
        blank_kernel(e2)
        setup_save(e2, learned=LEARNED, learnable=LEARNABLE)
        e2.call(0x4B2EB0)
        bits = e2.rb(GF_BASE + 0x14, 16)
        got = [ab for ab in LEARNABLE if bits[ab // 8] >> (ab % 8) & 1]
        ok(got == (LEARNABLE if patched_img else []), "4B2EB0 learned %s (patched=%s)" % (got, patched_img))


def test_item_teach(vanilla, patched, L):
    for img, expect in ((vanilla, 0), (patched, 1)):
        e = Emu(img)
        blank_kernel(e)
        setup_save(e)
        for f in (0x4BD630, 0x4F7A60, 0x495EF0):
            e.stub(f, ret=0x11000F00)
        r = e.call(0x4FC6C0, 0x10, 0x70)
        bits = e.rb(GF_BASE + 0x14, 16)
        learned = bits[0x70 // 8] >> (0x70 % 8) & 1
        ok(r == expect and learned == expect, "item teach on a 51-entry GF: ret=%d learned=%d (expect %d)" % (r, learned, expect))


def main():
    exe = sys.argv[1] if len(sys.argv) > 1 else default_exe()
    vanilla, patched, ops = images(exe)
    L = static_checks(exe, vanilla, ops)
    test_builder(vanilla, patched)
    test_gf_menu(patched, L)
    test_item_menu(patched, L)
    test_junction_info(patched, L)
    test_frames(vanilla, patched)
    test_item_teach(vanilla, patched, L)
    print("OK: %d checks passed" % checks)


if __name__ == "__main__":
    main()
