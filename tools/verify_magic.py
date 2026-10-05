"""Emulation checks for the "All Magic Per Character" mod.

Applies magic.hext exactly as Junction VIII would (parse + apply to the loaded EXE image),
then runs the rewritten functions in the Unicorn CPU emulator and checks their behaviour for
64 slots. Focuses on the hand-written cave hooks, which are the riskiest part.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ff8hext import Image, default_exe  # noqa: E402
from emu import Emu  # noqa: E402
import build_magic as B  # noqa: E402

NEWMAG, D = B.NEWMAG, B.D
SAVEMAG = 0x1CFE0F8      # savemap char0 old 32-slot magic region
LABELS = {}


def patched_image():
    img = Image(default_exe())
    P, code, labels = B.collect(img)
    B.check(img, P, code)
    img.mem[B.CODE - img.BASE:B.CODE - img.BASE + len(code)] = code
    for a, b, _ in P.patches:
        img.mem[a - img.BASE:a - img.BASE + len(b)] = b
    return img, labels


def mag(e, char, slot):
    base = NEWMAG + char * 0x98 + slot * 2
    return e.r8(base), e.r8(base + 1)      # (id, qty)


def set_mag(e, char, slot, sid, qty):
    base = NEWMAG + char * 0x98 + slot * 2
    e.w8(base, sid)
    e.w8(base + 1, qty)


def clear_char(e, char):
    for s in range(64):
        set_mag(e, char, s, 0, 0)


CHECKS = []


def check(name):
    def deco(fn):
        CHECKS.append((name, fn))
        return fn
    return deco


@check("add_magic: new spell into empty list")
def _(e):
    clear_char(e, 0)
    r = e.call(0x4C2C70, 0, 5, 10)
    assert mag(e, 0, 0) == (5, 10), mag(e, 0, 0)
    assert r == 10, r


@check("add_magic: stacks onto existing slot, capped at 100")
def _(e):
    clear_char(e, 0)
    set_mag(e, 0, 3, 5, 40)
    r = e.call(0x4C2C70, 0, 5, 80)
    assert mag(e, 0, 3) == (5, 100), mag(e, 0, 3)
    assert r == 60, r                        # only 60 actually added


@check("add_magic: uses slots beyond 32 (true 64-slot capacity)")
def _(e):
    clear_char(e, 0)
    for s in range(40):                      # fill 40 distinct spells
        set_mag(e, 0, s, s + 1, 1)
    r = e.call(0x4C2C70, 0, 99, 7)           # new spell -> first free slot (40)
    assert mag(e, 0, 40) == (99, 7), mag(e, 0, 40)
    assert r == 7, r


@check("add_magic: all 64 slots full -> no room")
def _(e):
    clear_char(e, 0)
    for s in range(64):
        set_mag(e, 0, s, s + 1, 50)
    r = e.call(0x4C2C70, 0, 99, 7)
    assert r == 0, r
    assert mag(e, 0, 0) == (1, 50)


@check("can_receive: char holding the spell can receive (returns 1)")
def _(e):
    clear_char(e, 0)
    set_mag(e, 0, 10, 5, 30)
    e.w8(0x1D8575C, 0xAA)                     # sentinel in per-char result byte
    r = e.call(0x4D9000, 5, 0x01)             # spell 5, charmask=char0
    assert (r & 1) == 1, r
    assert e.r8(0x1D8575C) == 30, e.r8(0x1D8575C)   # result byte = current qty


@check("can_receive: 64-slot char is never 'full' (room always exists)")
def _(e):
    clear_char(e, 0)
    for s in range(60):                      # 60 occupied, spell absent
        set_mag(e, 0, s, s + 20, 50)
    r = e.call(0x4D9000, 7, 0x01)
    assert (r & 1) == 1, r                    # not full -> can receive
    assert e.r8(0x1D8575C) != 0xFF, e.r8(0x1D8575C)


@check("swap_junctions: swaps both chars' full 64-slot magic")
def _(e):
    clear_char(e, 1)
    clear_char(e, 2)
    set_mag(e, 1, 0, 11, 10)
    set_mag(e, 1, 50, 12, 20)                # a slot beyond 32
    set_mag(e, 2, 0, 21, 30)
    # swap_junctions(char1=1, char2=2): args at entry [esp+4] and [esp+0x18]
    e.call(0x4CB4A0, 1, 0, 0, 0, 0, 2)
    assert mag(e, 1, 0) == (21, 30), mag(e, 1, 0)
    assert mag(e, 2, 0) == (11, 10), mag(e, 2, 0)
    assert mag(e, 2, 50) == (12, 20), mag(e, 2, 50)


def oldbyte(e, char, off):
    return e.r8(SAVEMAG + char * 0x98 + off)


@check("persist: pack writes 0xFF signature + dense qty[id]")
def _(e):
    clear_char(e, 0)
    set_mag(e, 0, 0, 5, 30)
    set_mag(e, 0, 1, 12, 100)
    set_mag(e, 0, 40, 7, 55)                 # a slot beyond 32
    e.call(LABELS["mag_save_pack"])
    assert oldbyte(e, 0, 0) == 0xFF
    assert (oldbyte(e, 0, 5), oldbyte(e, 0, 12), oldbyte(e, 0, 7)) == (30, 100, 55)


@check("persist: pack then unpack round-trips all spells (incl. slot>32)")
def _(e):
    clear_char(e, 0)
    set_mag(e, 0, 0, 5, 30)
    set_mag(e, 0, 40, 7, 55)
    e.call(LABELS["mag_save_pack"])
    for s in range(64):
        set_mag(e, 0, s, 0, 0)               # wipe NEWMAG as a save/load would
    e.call(LABELS["mag_load_unpack"])
    got = {}
    for s in range(64):
        i, q = mag(e, 0, s)
        if i:
            got[i] = q
    assert got == {5: 30, 7: 55}, got


@check("persist: pre-mod (vanilla) save migrates its 32 slots")
def _(e):
    clear_char(e, 0)
    for s in range(64):
        e.w8(SAVEMAG + s, 0)
    e.w8(SAVEMAG + 0, 5); e.w8(SAVEMAG + 1, 30)      # vanilla slot0: spell 5 x30
    e.w8(SAVEMAG + 2, 12); e.w8(SAVEMAG + 3, 100)    # vanilla slot1: spell 12 x100
    for s in range(64):
        set_mag(e, 0, s, 0, 0)
    e.call(LABELS["mag_load_unpack"])                # byte0 != 0xFF -> migrate
    assert mag(e, 0, 0) == (5, 30), mag(e, 0, 0)
    assert mag(e, 0, 1) == (12, 100), mag(e, 0, 1)


@check("battle_to_savemap: battle table -> 64-slot magic + junction cleanup")
def _(e):
    clear_char(e, 0)
    e.w8(0x1D27BCB, 0)                        # actor0 valid
    e.w8(0x1D27BCB + 0xD0, 0xFF)              # actor1 = end sentinel
    e.w8(0x1CFE74C, 0)                        # actor0 -> char0
    bm = B.BMAG
    e.w8(bm + 0, 5); e.w8(bm + 1, 30)         # battle entry0 = spell 5 x30
    e.w8(bm + 5, 12); e.w8(bm + 6, 99)        # battle entry1 = spell 12 x99
    j = 0x1CFE0E8 + 0x5C                       # char0 junction slots (savemap)
    e.w8(j + 0, 5)                            # junction to a held spell -> kept
    e.w8(j + 1, 99)                           # junction to an unheld spell -> cleared
    e.call(0x486CD0)
    assert mag(e, 0, 0) == (5, 30), mag(e, 0, 0)
    assert mag(e, 0, 1) == (12, 99), mag(e, 0, 1)
    assert e.r8(j + 0) == 5 and e.r8(j + 1) == 0, (e.r8(j + 0), e.r8(j + 1))


@check("battle_rand_spell: picks a held spell from the 64-entry battle table")
def _(e):
    bm = B.BMAG
    for i in range(64 * 5):
        e.w8(bm + i, 0)
    e.w8(bm + 0, 5); e.w8(bm + 1, 30)        # entry0 = spell 5
    e.w8(bm + 5, 12); e.w8(bm + 6, 99)       # entry1 = spell 12
    e.stub(0x48F020, 0)                       # RNG -> 0  => index 0
    assert e.call(0x4837E0, 0, 0) == 5        # actor 0, mode 0


@check("battle_rand_spell: empty table returns 0xff")
def _(e):
    bm = B.BMAG
    for i in range(64 * 5):
        e.w8(bm + i, 0)
    e.stub(0x48F020, 0)
    assert e.call(0x4837E0, 0, 0) == 0xFF


def main():
    global LABELS
    img, labels = patched_image()
    LABELS = labels
    ok = 0
    for name, fn in CHECKS:
        e = Emu(img)
        try:
            fn(e)
        except Exception as ex:
            print("FAIL %-55s %s" % (name, ex))
            continue
        print("ok   %s" % name)
        ok += 1
    print("\n%d/%d checks passed" % (ok, len(CHECKS)))
    return ok == len(CHECKS)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
