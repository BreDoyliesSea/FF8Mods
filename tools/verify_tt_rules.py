"""Emulates the patched CARDGAME call site with Unicorn against the real FF8_EN.exe image,
for every option of every rule, and checks the resulting rule/trade globals."""
import itertools
import os
import struct
import sys

import unicorn as uc
from unicorn.x86_const import UC_X86_REG_ESP, UC_X86_REG_EIP

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_tt_rules as B  # noqa: E402
from ff8hext import Image, parse_hext, default_exe  # noqa: E402

MOD = os.path.normpath(B.ROOT)


def load(path):
    return parse_hext(open(path).read())


def run(options, rules_in, trade_in, exe):
    img = Image(exe)
    assert img.read(B.HOOK, 5) == B.HOOK_ORIG, "hook site bytes differ from expected"
    assert img.read(B.CAVE, 0x40) == b"\0" * 0x40, "cave not empty in original exe"
    img.apply(load(os.path.join(MOD, "hext", "00_tt_rules_hook.hext")))
    for folder in options:
        d = os.path.join(MOD, folder, "hext")
        for f in sorted(os.listdir(d)):
            img.apply(load(os.path.join(d, f)))
    mu = uc.Uc(uc.UC_ARCH_X86, uc.UC_MODE_32)
    mu.mem_map(img.BASE, (len(img.mem) + 0xFFF) & ~0xFFF)
    mu.mem_write(img.BASE, bytes(img.mem))
    mu.mem_map(0x10000000, 0x10000)
    esp = 0x1000F000
    mu.reg_write(UC_X86_REG_ESP, esp)
    mu.mem_write(B.RULES, struct.pack("<I", rules_in))
    mu.mem_write(B.TRADE, bytes([trade_in]))
    hit = {}

    def hook(m, addr, size, _):
        if addr == B.COUNT_CARDS:
            hit["ret"] = struct.unpack("<I", m.mem_read(m.reg_read(UC_X86_REG_ESP), 4))[0]
            hit["esp"] = m.reg_read(UC_X86_REG_ESP)
            m.emu_stop()
    mu.hook_add(uc.UC_HOOK_CODE, hook)
    mu.emu_start(B.HOOK, 0, count=200)
    assert hit.get("ret") == B.HOOK + 5, "did not reach original call target with correct return address"
    assert hit["esp"] == esp - 4
    rules = struct.unpack("<I", mu.mem_read(B.RULES, 4))[0]
    trade = mu.mem_read(B.TRADE, 1)[0]
    return rules, trade


def main():
    exe = sys.argv[1] if len(sys.argv) > 1 else default_exe()
    checks = 0
    # every single-rule option against a few inputs
    for (rid, name, bit, _), state in itertools.product(B.RULE_LIST, (0, 1, 2)):
        for rin in (0x00, 0xFF, 0x20000000 | 0x5A, 0x80000000 | 0x01):
            opts = [] if state == 0 else ["options/%s_%s" % (rid, "On" if state == 1 else "Off")]
            r, t = run(opts, rin, 3, exe)
            exp = rin if state == 0 else (rin | bit if state == 1 else rin & ~bit)
            assert r == exp, (name, state, hex(rin), hex(r), hex(exp))
            assert t == 3
            checks += 1
    for val, name, tbyte, _ in B.TRADE_LIST:
        r, t = run(["options/Trade_%s" % name.split()[0]], 0x40000004, 1, exe)
        assert (r, t) == (0x40000004, tbyte), (name, r, t)
        checks += 1
    # a mixed configuration
    r, t = run(["options/Open_On", "options/Same_Off", "options/Elemental_On", "options/Trade_All"], 0x20000006, 1, exe)
    assert (r, t) == (0x20000085, 4), (hex(r), t)
    checks += 1
    print("OK: %d emulated scenarios passed" % checks)


if __name__ == "__main__":
    main()
