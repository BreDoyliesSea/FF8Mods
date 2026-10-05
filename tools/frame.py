"""Stack-frame enlargement for esp-based MSVC functions in FF8_EN.exe.

Several callers of the GF ability-list builder keep its 22-entry output buffer as the
topmost local of their stack frame. To make room for more entries we grow the frame
(`sub esp, F` / `add esp, F`) by DELTA bytes. All locals keep their esp-relative
displacements, so they move down by DELTA together, and the buffer can now grow up into
the new space. Only accesses that reach above the frame (registers saved before the
`sub`, the return address, arguments) must have DELTA added to their displacement.

The analysis follows every branch from the function entry and tracks how many bytes
have been pushed at each instruction, so join points with mismatched depths are caught
instead of guessed.
"""
import struct

import capstone
from capstone import x86_const as X

_md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
_md.detail = True


class FrameError(Exception):
    pass


def _insn(img, addr):
    for i in _md.disasm(img.read(addr, 16), addr):
        return i
    raise FrameError("cannot decode at %08X" % addr)


def analyze(img, entry, frame, end):
    """Return (sub_sites, add_sites, above_frame_accesses).

    entry: function start; frame: the expected `sub esp, frame`; end: first address past
    the function (instructions outside [entry, end) are treated as tail calls/jumps out).
    """
    depth = {}          # addr -> bytes pushed since entry (excluding return address)
    pre_sub = {}        # addr -> bytes pushed before the frame sub (P)
    sub_seen = {}
    work = [(entry, 0, 0, False)]
    insns = {}
    while work:
        a, d, p, s = work.pop()
        if not (entry <= a < end):
            continue
        if a in depth:
            if (depth[a], pre_sub[a], sub_seen[a]) != (d, p, s):
                raise FrameError("stack depth mismatch at %08X: %s vs %s" % (a, (depth[a], pre_sub[a], sub_seen[a]), (d, p, s)))
            continue
        depth[a], pre_sub[a], sub_seen[a] = d, p, s
        i = _insn(img, a)
        insns[a] = i
        m = i.mnemonic
        nd, np_, ns = d, p, s
        ops = i.operands
        if m == "push":
            nd += 4
            if not s:
                np_ += 4
        elif m == "pop":
            nd -= 4
            if not s:
                np_ -= 4
        elif m in ("sub", "add") and ops[0].type == X.X86_OP_REG and ops[0].reg == X.X86_REG_ESP:
            if ops[1].type != X.X86_OP_IMM:
                raise FrameError("non-immediate esp adjust at %08X" % a)
            v = ops[1].imm if m == "sub" else -ops[1].imm
            if m == "sub" and not s and v == frame:
                ns = True
            nd += v
        elif m == "pushfd" or m == "pushal":
            raise FrameError("unsupported %s at %08X" % (m, a))
        nxt = a + i.size
        if m == "ret":
            if nd != 0:
                raise FrameError("ret at %08X with depth %d" % (a, nd))
            continue
        if m == "jmp":
            if ops[0].type == X.X86_OP_IMM:
                work.append((ops[0].imm, nd, np_, ns))
                continue
            # indirect jump: switch table `jmp [reg*4 + table]`
            mem = ops[0].mem
            if ops[0].type == X.X86_OP_MEM and mem.base == 0 and mem.scale == 4:
                t = mem.disp & 0xFFFFFFFF
                k = 0
                while True:
                    tgt = img.u32(t + 4 * k)
                    if not (entry <= tgt < end):
                        break
                    work.append((tgt, nd, np_, ns))
                    k += 1
                if k == 0:
                    raise FrameError("empty switch at %08X" % a)
                continue
            raise FrameError("unhandled indirect jmp at %08X" % a)
        if m.startswith("j") or m in ("loop", "jecxz"):
            work.append((ops[0].imm, nd, np_, ns))
            work.append((nxt, nd, np_, ns))
            continue
        work.append((nxt, nd, np_, ns))

    subs, adds, above = [], [], []
    for a, i in sorted(insns.items()):
        d, p, s = depth[a], pre_sub[a], sub_seen[a]
        m = i.mnemonic
        ops = i.operands
        if m in ("sub", "add") and ops[0].type == X.X86_OP_REG and ops[0].reg == X.X86_REG_ESP and ops[1].imm == frame:
            (subs if m == "sub" else adds).append(a)
            continue
        for op in ops:
            if op.type == X.X86_OP_MEM and op.mem.base == X.X86_REG_ESP:
                disp = op.mem.disp
                # entry-relative address of the access; >= -p means at/above the frame top
                rel = disp - d
                if s and rel >= -p:
                    above.append((a, i, disp))
                elif not s and rel >= -d:
                    pass  # before the frame exists: pushes/args only, unaffected
    return insns, subs, adds, above


def _patch_disp(img, i, old, new):
    """Return (addr, bytes) replacing a 32-bit displacement `old` with `new` in insn i."""
    raw = img.read(i.address, i.size)
    pat = struct.pack("<i", old)
    k = raw.find(pat)
    if k < 0 or raw.find(pat, k + 1) >= 0:
        raise FrameError("disp32 %X not uniquely found in %08X %s %s (needs disp32 encoding)" % (old, i.address, i.mnemonic, i.op_str))
    return i.address + k, struct.pack("<i", new)


def _patch_imm(img, a, old, new):
    raw = img.read(a, 6)
    # sub/add esp, imm32 is 81 EC/C4 imm32
    if raw[0] != 0x81 or raw[1] not in (0xEC, 0xC4) or struct.unpack("<I", raw[2:6])[0] != old:
        raise FrameError("esp adjust at %08X is not the imm32 form: %s" % (a, raw.hex()))
    return a + 2, struct.pack("<I", new)


def enlarge(img, entry, frame, end, delta, expect_above=None):
    """Return list of (addr, bytes) patches growing the frame of `entry` by `delta`."""
    insns, subs, adds, above = analyze(img, entry, frame, end)
    if len(subs) != 1:
        raise FrameError("%08X: expected one `sub esp, %X`, found %s" % (entry, frame, [hex(x) for x in subs]))
    if not adds:
        raise FrameError("%08X: no epilogue `add esp, %X`" % (entry, frame))
    if expect_above is not None and len(above) != expect_above:
        raise FrameError("%08X: expected %d above-frame accesses, found %d: %s" % (
            entry, expect_above, len(above), ["%08X %s %s" % (a, i.mnemonic, i.op_str) for a, i, _ in above]))
    patches = [_patch_imm(img, a, frame, frame + delta) for a in subs + adds]
    for a, i, disp in above:
        patches.append(_patch_disp(img, i, disp, disp + delta))
    return patches, above
