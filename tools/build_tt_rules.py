"""Builds the "Triple Triad Rule Select" Junction VIII mod.

How it works
------------
Field scripts start a card game with the CARDGAME opcode (handler 0x5225A0). It pops
its arguments into globals, among them:
    0x1DCD7A8 (dword) rule flags; the low byte holds the rules
                      01 Open  02 Same  04 Plus  08 Random  10 Sudden Death
                      40 Same Wall  80 Elemental   (20 is an internal flag, left alone)
    0x1DCD7AC (byte)  trade rule 0 none, 1 One, 2 Diff, 3 Direct, 4 All
and then calls 0x5349B0 (count Squall's cards) at 0x522652. The card game copies the
globals above into its own state later, at 0x534350 / 0x5343A5 / 0x5346DF.

We redirect that call to a small routine in unused padding at the end of .text. The
routine adjusts the rule byte and trade rule, then tail-jumps to 0x5349B0, so the
original flow continues unchanged. The routine has one 7-byte slot per rule, plus one
for the trade rule. The base patch fills every slot with NOPs ("region default"), and
each option folder overwrites its own slot with an OR (force on), an AND (force off) or
a MOV (trade rule). Junction VIII applies the root hext/ files before option-folder
files, so the option always wins.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ff8hext import Hext, asm, hexbytes  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "FF8Unlimited", "options", "CardRules")

HOOK = 0x522652          # call 0x5349B0 inside the CARDGAME opcode
HOOK_ORIG = bytes.fromhex("E859230100")
COUNT_CARDS = 0x5349B0
RULES = 0x1DCD7A8
TRADE = 0x1DCD7AC
CAVE = 0xB68E00          # zero padding at the end of .text (0xB68933..0xB69000)
SLOT = 7

RULE_LIST = [
    # id, name, bit, description
    ("Open", "Open", 0x01, "Both hands are visible to both players."),
    ("Same", "Same", 0x02, "Flip neighbours when two or more touching sides are equal."),
    ("Plus", "Plus", 0x04, "Flip neighbours when two or more touching sides add up to the same sum."),
    ("Random", "Random", 0x08, "Your five cards are picked at random from your collection."),
    ("SuddenDeath", "Sudden Death", 0x10, "A draw restarts the match with the cards each player owns on the board."),
    ("SameWall", "Same Wall", 0x40, "The board edges count as A for Same (only matters when Same is also on)."),
    ("Elemental", "Elemental", 0x80, "Elemental squares raise or lower card ranks."),
]
TRADE_LIST = [
    # option value, name, trade byte, description
    (1, "One", 1, "The winner takes one card of their choice."),
    (2, "Diff", 2, "The winner takes as many cards as the score difference."),
    (3, "Direct", 3, "Each player keeps the cards they captured on the board."),
    (4, "All", 4, "The winner takes all five cards."),
    (5, "None (no cards change hands)", 0, "Nobody loses cards, win or lose."),
]


def slot_addr(i):
    return CAVE + i * SLOT


def nop_slot():
    return b"\x90" * SLOT


def build():
    n_slots = len(RULE_LIST) + 1
    jmp_at = slot_addr(n_slots)
    tail = asm("jmp 0x%X" % COUNT_CARDS, jmp_at)
    cave_len = n_slots * SLOT + len(tail)

    # ---- base patch (always active) ----
    h = Hext("Triple Triad Rule Select - base hook (FF8 Steam 2013, FF8_EN.exe)")
    h.comment("Target: FF8_EN.exe sha1 03230c11328f8a1f9635435096e1659d9bfd002d (Steam 2013, English).")
    h.comment("Original bytes at %08X: %s (call %08X)" % (HOOK, hexbytes(HOOK_ORIG), COUNT_CARDS))
    h.blank()
    h.protect(CAVE, cave_len, "Make the code cave writable/executable")
    for i, (_, name, _, _) in enumerate(RULE_LIST):
        h.write(slot_addr(i), nop_slot(), "slot %d: %s (region default)" % (i, name))
    h.write(slot_addr(len(RULE_LIST)), nop_slot(), "slot %d: trade rule (region default)" % len(RULE_LIST))
    h.write(jmp_at, tail, "continue to the original call target")
    h.blank()
    h.write(HOOK, asm("call 0x%X" % CAVE, HOOK), "CARDGAME opcode: call the cave instead of %08X" % COUNT_CARDS)
    h.save(os.path.join(ROOT, "hext", "00_tt_rules_hook.hext"))

    folders = []
    # ---- per-rule option folders ----
    for i, (rid, name, bit, _) in enumerate(RULE_LIST):
        a = slot_addr(i)
        on = asm("or byte ptr [0x%X], 0x%X" % (RULES, bit), a)
        off = asm("and byte ptr [0x%X], 0x%X" % (RULES, 0xFF & ~bit), a)
        assert len(on) == SLOT and len(off) == SLOT
        for val, state, code in ((1, "On", on), (2, "Off", off)):
            folder = "options/%s_%s" % (rid, state)
            hh = Hext("Triple Triad Rule Select - %s always %s" % (name, state.lower()))
            hh.write(a, code, "slot %d: %s forced %s" % (i, name, state.lower()))
            hh.save(os.path.join(ROOT, folder, "hext", "tt_rule_%s_%s.hext" % (rid.lower(), state.lower())))
            folders.append((folder, "Rule%s=%d" % (rid, val)))
    # ---- trade rule ----
    a = slot_addr(len(RULE_LIST))
    for val, name, tbyte, _ in TRADE_LIST:
        code = asm("mov byte ptr [0x%X], 0x%X" % (TRADE, tbyte), a)
        assert len(code) == SLOT
        tag = name.split()[0]
        folder = "options/Trade_%s" % tag
        hh = Hext("Triple Triad Rule Select - trade rule %s" % name)
        hh.write(a, code, "slot %d: trade rule forced to %d (%s)" % (len(RULE_LIST), tbyte, name))
        hh.save(os.path.join(ROOT, folder, "hext", "tt_trade_%s.hext" % tag.lower()))
        folders.append((folder, "TradeRule=%d" % val))

    return folders  # (folder relative to ROOT, ActiveWhen condition); mod.xml is written by build_mod.py


if __name__ == "__main__":
    build()
    print("built", os.path.normpath(ROOT))
