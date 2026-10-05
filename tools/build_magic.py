"""Builds the "64 magic slots" Junction VIII mod (FF8 Steam 2013, FF8_EN.exe).

Goal: every character can hold up to 64 different spells (so all ~56 game spells,
100 each) instead of the vanilla 32 magic slots.

Design
------
Each character's 32 magic slots live inside the savemap at
``savemap(0x1CFDC58) + 0x490 + 0x98*char + 0x10`` (char0 slot0 = 0x1CFE0F8), 32 slots
of 2 bytes = 0x40 bytes, inside the 0x98-byte per-character record. There is no room to
widen that in place (the next field, commands at +0x50, follows immediately), so the
magic moves to a parallel array ``NEWMAG`` with the *same* 0x98 stride but 0x80 bytes
(64 slots) used per character. For an absolute address A inside a character's magic area
the relocated address is ``A + D`` with ``D = NEWMAG - 0x1CFE0F8``.

The battle magic table (32 entries x 5 bytes inside each battle actor struct at
``0x1CFF000 + k*0x1D0``, magic at +0x82) likewise can't grow to 64 entries in place, so it
moves to ``BMAG`` with the same 0x1D0 stride; ``DB = BMAG - 0x1CFF082``.

`tools/magic_sites.py` is the reviewed, classified list of every code site that touches
either array. This builder consumes it. See that file for the per-kind meaning.

This module is built in stages; see the milestone guard in ``collect``.
"""
import os
import struct
import sys

import capstone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ff8hext import Hext, asm, Image, default_exe  # noqa: E402
import magic_sites  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "AllMagicPerCharacter")

# ---- the two relocated arrays ---------------------------------------------------------
OLD_MAG0 = 0x1CFE0F8          # char0 magic slot0 (savemap + 0x4A0)
OLD_BMAG0 = 0x1CFF082         # battle actor0 magic table (struct0 + 0x82)
SAVEMAP = 0x1CFDC58
SAVE_BLOCK = 0x13A4           # bytes the game reads/writes as one savemap block

# Memory map. Addresses sit in two bss windows that nothing in the entire static image
# references (verified by tools/re scan) and that load as zero; see find_free in README.
# build() asserts each region is zero in the EXE before emitting.
NEWMAG = 0x24B5000       # 16 chars * 0x98 (0x980)
MBAK1 = 0x24B5A00        # magic-exchange backup buffers (0x80 each)
MBAK2 = 0x24B5A80
JMASK = 0x24B5B00        # junction menu 64-bit masks (published / builder / auto / full)
JMASK_B = 0x24B5B08
AJMASK = 0x24B5B10
FULLMASK = 0x24B5B18
CODE = 0x24B6000         # code cave (RWX)
CODE_LIMIT = 0x24B7A00
BMAG = 0x25D5000         # 16 battle actors * 0x1D0 (0x1D00)

D = NEWMAG - OLD_MAG0
DB = BMAG - OLD_BMAG0

# bounds used only to recognise which operand of an instruction is the magic address
MAG_LO, MAG_HI = SAVEMAP, SAVEMAP + SAVE_BLOCK          # savemap magic lives in here
BMAG_LO, BMAG_HI = 0x1CFF000, 0x1CFF000 + 24 * 0x1D0     # battle actor structs

_md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
_md.detail = True


def _insn(img, addr):
    for i in _md.disasm(img.read(addr, 16), addr):
        return i
    raise SystemExit("cannot decode instruction at %08X" % addr)


def _field(raw, value, addr, note):
    """Byte offset of the unique little-endian 32-bit `value` inside instruction `raw`."""
    pat = struct.pack("<I", value & 0xFFFFFFFF)
    k = raw.find(pat)
    if k < 0:
        raise SystemExit("%08X: 32-bit field %08X not found in %s (%s)" % (addr, value & 0xFFFFFFFF, raw.hex(), note))
    if raw.find(pat, k + 1) >= 0:
        raise SystemExit("%08X: 32-bit field %08X not unique in %s (%s)" % (addr, value & 0xFFFFFFFF, raw.hex(), note))
    return k


def _abs_operand(i, lo, hi):
    """Return an absolute address operand (imm or base-less mem disp) of i within [lo,hi)."""
    found = []
    for op in i.operands:
        if op.type == capstone.x86.X86_OP_IMM and lo <= (op.imm & 0xFFFFFFFF) < hi:
            found.append(op.imm & 0xFFFFFFFF)
        elif op.type == capstone.x86.X86_OP_MEM and lo <= (op.mem.disp & 0xFFFFFFFF) < hi:
            found.append(op.mem.disp & 0xFFFFFFFF)
    if len(found) != 1:
        raise SystemExit("%08X %s %s: expected one address in [%X,%X), found %s"
                         % (i.address, i.mnemonic, i.op_str, lo, hi, [hex(x) for x in found]))
    return found[0]


def _mem_disp(i):
    """Return the (base-having) memory displacement operand value of instruction i."""
    disps = [op.mem.disp for op in i.operands
             if op.type == capstone.x86.X86_OP_MEM and op.mem.base != 0]
    if len(disps) != 1:
        raise SystemExit("%08X %s %s: expected one [reg+disp], found %d"
                         % (i.address, i.mnemonic, i.op_str, len(disps)))
    return disps[0]


class Patcher:
    def __init__(self, img):
        self.img = img
        self.patches = []       # (addr, bytes, note)
        self.deferred = []      # (addr, kind, args) needing cave/hook work
        self.skipped = []       # (addr, reason)
        self.counts = {}

    def _put(self, addr, new, expect, note):
        have = self.img.read(addr, len(expect))
        if have != expect:
            raise SystemExit("unexpected bytes at %08X: have %s expected %s (%s)"
                             % (addr, have.hex(), expect.hex(), note))
        self.patches.append((addr, bytes(new), note))

    def _bump(self, kind):
        self.counts[kind] = self.counts.get(kind, 0) + 1

    def site(self, s):
        addr, kind = s[0], s[1]
        args = s[2:]
        self._bump(kind)
        handler = getattr(self, "k_" + kind, None)
        if handler is None:
            raise SystemExit("%08X: unknown site kind %r" % (addr, kind))
        handler(addr, args)

    # ---- kinds that need later cave/hook work ----
    def k_tramp(self, addr, args):
        self.deferred.append((addr, "tramp", args))

    def k_patch(self, addr, args):
        self.deferred.append((addr, "patch", args))

    def k_hook(self, addr, args):
        self.deferred.append((addr, "hook", args))

    def k_skip(self, addr, args):
        self.skipped.append((addr, args[0] if args else ""))

    # ---- mechanical relocations (fully handled here) ----
    def k_rel(self, addr, args):
        i = _insn(self.img, addr)
        raw = self.img.read(addr, i.size)
        a = args[0] if args else _abs_operand(i, MAG_LO, MAG_HI)
        off = _field(raw, a, addr, "rel")
        self._put(addr + off, struct.pack("<I", (a + D) & 0xFFFFFFFF), raw[off:off + 4], "rel %08X->%08X" % (a, a + D))

    def k_end(self, addr, args):
        i = _insn(self.img, addr)
        raw = self.img.read(addr, i.size)
        a = args[0] if args else _abs_operand(i, MAG_LO, MAG_HI)
        new = a + D + 0x40
        off = _field(raw, a, addr, "end")
        self._put(addr + off, struct.pack("<I", new & 0xFFFFFFFF), raw[off:off + 4], "end %08X->%08X" % (a, new))

    def k_disp(self, addr, args):
        i = _insn(self.img, addr)
        raw = self.img.read(addr, i.size)
        disp = _mem_disp(i)
        off = _field(raw, disp, addr, "disp")  # must be disp32-encoded
        new = (disp - D) & 0xFFFFFFFF
        self._put(addr + off, struct.pack("<I", new), raw[off:off + 4], "disp %X->%X" % (disp & 0xFFFFFFFF, new))

    def k_brel(self, addr, args):
        i = _insn(self.img, addr)
        raw = self.img.read(addr, i.size)
        a = args[0] if args else _abs_operand(i, BMAG_LO, BMAG_HI)
        off = _field(raw, a, addr, "brel")
        self._put(addr + off, struct.pack("<I", (a + DB) & 0xFFFFFFFF), raw[off:off + 4], "brel %08X->%08X" % (a, a + DB))

    def k_bend(self, addr, args):
        i = _insn(self.img, addr)
        raw = self.img.read(addr, i.size)
        a = args[0] if args else _abs_operand(i, BMAG_LO, BMAG_HI)
        new = a + DB + 0xA0
        off = _field(raw, a, addr, "bend")
        self._put(addr + off, struct.pack("<I", new & 0xFFFFFFFF), raw[off:off + 4], "bend %08X->%08X" % (a, new))

    def k_bdisp(self, addr, args):
        i = _insn(self.img, addr)
        raw = self.img.read(addr, i.size)
        disp = _mem_disp(i)
        off = _field(raw, disp, addr, "bdisp")
        new = (disp + DB) & 0xFFFFFFFF
        self._put(addr + off, struct.pack("<I", new), raw[off:off + 4], "bdisp %X->%X" % (disp & 0xFFFFFFFF, new))

    def k_asm(self, addr, args):
        old_src, new_src = args
        old = asm(old_src, addr)
        new = asm(new_src, addr)
        if len(new) != len(old):
            # e.g. `push 0x40` (imm8, 2 bytes) -> `push 0x80` (imm32, 5 bytes): 0x80 can't be a
            # signed imm8. Needs a trampoline (the copy length can't grow in place). Defer it.
            self.deferred.append((addr, "asmgrow", (old_src, new_src)))
            self.counts["asm"] -= 1
            self.counts["asmgrow"] = self.counts.get("asmgrow", 0) + 1
            return
        self._put(addr, new, old, "asm %r -> %r" % (old_src, new_src))

    def k_x(self, addr, args):
        old_imm, new_imm = args
        i = _insn(self.img, addr)
        raw = self.img.read(addr, i.size)
        if isinstance(new_imm, str):            # address placeholder resolved from the map
            new_val = RESOLVE[new_imm]
        else:
            new_val = new_imm
        # old_imm may be a small immediate (encoded 1 or 4 bytes). Try 4-byte then 1-byte.
        pat4 = struct.pack("<I", old_imm & 0xFFFFFFFF)
        k = raw.find(pat4)
        if k >= 0 and raw.find(pat4, k + 1) < 0:
            self._put(addr + k, struct.pack("<I", new_val & 0xFFFFFFFF), raw[k:k + 4], "x %X->%X" % (old_imm, new_val))
            return
        pat1 = bytes([old_imm & 0xFF])
        k = raw.rfind(pat1)                     # immediate is the last byte of the instruction
        if k >= 0 and (old_imm <= 0xFF) and (new_val <= 0xFF):
            self._put(addr + k, bytes([new_val & 0xFF]), raw[k:k + 1], "x8 %X->%X" % (old_imm, new_val))
            return
        raise SystemExit("%08X: 'x' immediate %X not uniquely locatable in %s" % (addr, old_imm, raw.hex()))


MAGBAK = 0x25D7000       # menu-cancel backup of the whole NEWMAG array
OCCMASK = 0x24B5B20      # can_receive: 64-bit "occupied slots" scratch mask
NEWMAG_DWORDS = 0x980 // 4

# names available to cave / patch / tramp assembly as {NAME}
NAMES = dict(
    D=D, DB=DB, NEWMAG=NEWMAG, BMAG=BMAG, JMASK=JMASK, JMASK_B=JMASK_B,
    AJMASK=AJMASK, FULLMASK=FULLMASK, MBAK1=MBAK1, MBAK2=MBAK2, MAGBAK=MAGBAK,
    OCCMASK=OCCMASK, NEWMAG_DWORDS=NEWMAG_DWORDS,
    RELOC_1CFE3F0=0x1CFE3F0 + D, RELOC_1CFE488=0x1CFE488 + D,
)

# hook site -> cave routine. Each overwrites whole instructions (>=5 bytes) at the site
# with a jmp to the routine; the routine either rebuilds the whole function and `ret`s, or
# (swap_junctions / battle_rand_spell40) re-joins the original.
HOOKS = {
    0x4C2C70: "add_magic", 0x4D9000: "can_receive", 0x486CD0: "battle_to_savemap",
    0x4837E0: "battle_rand_spell", 0x483D85: "battle_rand_spell40", 0x4CB4A0: "swap_junctions",
}

# addresses the 'x' template strings resolve to
RESOLVE = {"{MBAK1}": MBAK1, "{MBAK2}": MBAK2}


def subst(src, extra=None):
    """Replace {NAME} with its hex value (longer names first so {JMASK_B} != {JMASK}_B)."""
    table = dict(NAMES)
    if extra:
        table.update(extra)
    for k in sorted(table, key=len, reverse=True):
        src = src.replace("{%s}" % k, "0x%X" % (table[k] & 0xFFFFFFFF))
    return src


# Fixed cave routines. {NAME} placeholders are substituted by subst().
CAVE_FIXED = r"""
; ---- junction menu 64-bit "junctionable slot" mask -------------------------------------
jm_test:                                 ; ZF = (JMASK bit cl == 0); all GP regs preserved
    push eax
    push edx
    mov eax, ecx
    and eax, 0x20
    shr eax, 3
    mov edx, 1
    shl edx, cl
    test dword ptr [eax + {JMASK}], edx
    pop edx
    pop eax
    ret
jm_store_44:                             ; mov [esi+44],al + publish JMASK_B -> JMASK
    mov byte ptr [esi + 0x44], al
    push eax
    mov eax, dword ptr [{JMASK_B}]
    mov dword ptr [esi + 0x2c], eax
    mov dword ptr [{JMASK}], eax
    mov eax, dword ptr [{JMASK_B} + 4]
    mov dword ptr [{JMASK} + 4], eax
    xor eax, eax
    mov dword ptr [{JMASK_B}], eax
    mov dword ptr [{JMASK_B} + 4], eax
    pop eax
    ret
jm_store_bl18:                           ; mov bl,[esp+18] (orig) + publish
    mov bl, byte ptr [esp + 0x1C]
    push eax
    mov eax, dword ptr [{JMASK_B}]
    mov dword ptr [esi + 0x2c], eax
    mov dword ptr [{JMASK}], eax
    mov eax, dword ptr [{JMASK_B} + 4]
    mov dword ptr [{JMASK} + 4], eax
    xor eax, eax
    mov dword ptr [{JMASK_B}], eax
    mov dword ptr [{JMASK_B} + 4], eax
    pop eax
    ret
jm_store_idiv:                           ; publish (ebx dead) + cdq; idiv ecx
    mov ebx, dword ptr [{JMASK_B}]
    mov dword ptr [esi + 0x2c], ebx
    mov dword ptr [{JMASK}], ebx
    mov ebx, dword ptr [{JMASK_B} + 4]
    mov dword ptr [{JMASK} + 4], ebx
    xor ebx, ebx
    mov dword ptr [{JMASK_B}], ebx
    mov dword ptr [{JMASK_B} + 4], ebx
    cdq
    idiv ecx
    ret
jm_store_imul:                           ; publish (ebx dead) + imul ecx
    mov ebx, dword ptr [{JMASK_B}]
    mov dword ptr [esi + 0x2c], ebx
    mov dword ptr [{JMASK}], ebx
    mov ebx, dword ptr [{JMASK_B} + 4]
    mov dword ptr [{JMASK} + 4], ebx
    xor ebx, ebx
    mov dword ptr [{JMASK_B}], ebx
    mov dword ptr [{JMASK_B} + 4], ebx
    imul ecx
    ret

; ---- auto-junction 64-bit "usable slot" mask -------------------------------------------
aj_done:                                 ; clear AJMASK, then xor ecx,ecx; mov cl,[esi+43]
    xor ecx, ecx
    mov dword ptr [{AJMASK}], ecx
    mov dword ptr [{AJMASK} + 4], ecx
    mov cl, byte ptr [esi + 0x43]
    ret

; ---- magic-exchange 64-bit "occupied slot" mask ----------------------------------------
fm_clear:                                ; clear FULLMASK, then mov edx,eax; xor eax,eax; xor ecx,ecx
    mov edx, eax
    xor eax, eax
    mov dword ptr [{FULLMASK}], eax
    mov dword ptr [{FULLMASK} + 4], eax
    xor ecx, ecx
    ret
fm_isfull:                               ; ZF = 1 iff all 64 bits of FULLMASK set
    push eax
    mov eax, dword ptr [{FULLMASK}]
    and eax, dword ptr [{FULLMASK} + 4]
    cmp eax, -1
    pop eax
    ret

; ---- menu-cancel backup / restore also covers the relocated magic ----------------------
chars_backup:                            ; mov esi,0x1cfe0e8; rep movsd (orig) + save NEWMAG
    mov esi, 0x1cfe0e8
    rep movsd dword ptr es:[edi], dword ptr [esi]
    push esi
    push edi
    push ecx
    mov esi, {NEWMAG}
    mov edi, {MAGBAK}
    mov ecx, {NEWMAG_DWORDS}
    rep movsd dword ptr es:[edi], dword ptr [esi]
    pop ecx
    pop edi
    pop esi
    ret
chars_restore:                           ; mov edi,0x1cfe0e8; rep movsd (orig) + restore NEWMAG
    mov edi, 0x1cfe0e8
    rep movsd dword ptr es:[edi], dword ptr [esi]
    push esi
    push edi
    push ecx
    mov esi, {MAGBAK}
    mov edi, {NEWMAG}
    mov ecx, {NEWMAG_DWORDS}
    rep movsd dword ptr es:[edi], dword ptr [esi]
    pop ecx
    pop edi
    pop esi
    ret
"""


CAVE_HOOKS = r"""
; ======================================================================= hooks
; ---- add_magic(char, spell, qty) -> eax = amount added. Full rewrite (64 slots). --------
add_magic:
    push ebx
    push esi
    push edi
    mov esi, dword ptr [esp + 0x10]          ; char
    mov ebx, dword ptr [esp + 0x14]          ; spell
    mov eax, esi
    imul eax, eax, 0x98
    lea edx, [eax + {NEWMAG}]
    xor ecx, ecx
am_find:
    movsx eax, byte ptr [edx]
    cmp eax, ebx
    jne am_next
    cmp byte ptr [edx + 1], 0
    jne am_existing
am_next:
    add edx, 2
    inc ecx
    cmp ecx, 0x40
    jl am_find
    mov eax, esi
    imul eax, eax, 0x98
    lea edx, [eax + {NEWMAG}]
    xor ecx, ecx
am_free:
    cmp byte ptr [edx], 0
    je am_putfree
    add edx, 2
    inc ecx
    cmp ecx, 0x40
    jl am_free
    xor eax, eax
    jmp am_ret
am_putfree:
    mov eax, dword ptr [esp + 0x18]          ; qty
    test eax, eax
    jge am_f1
    xor eax, eax
am_f1:
    cmp eax, 0x64
    jle am_f2
    mov eax, 0x64
am_f2:
    mov byte ptr [edx], bl
    mov byte ptr [edx + 1], al
    jmp am_ret
am_existing:
    movsx eax, byte ptr [edx + 1]
    mov edi, dword ptr [esp + 0x18]          ; qty
    mov ecx, eax
    add eax, edi
    cmp eax, 0x64
    jl am_e1
    mov eax, 0x64
am_e1:
    mov byte ptr [edx + 1], al
    sub eax, ecx
am_ret:
    pop edi
    pop esi
    pop ebx
    ret

; ---- can_receive(spell, charmask). Full rewrite (64 slots, 8 chars). -------------------
can_receive:
    push ebx
    push ebp
    push esi
    push edi
    xor ebp, ebp                             ; full_mask
    xor edi, edi                             ; char index
cr_char:
    mov eax, dword ptr [esp + 0x18]          ; charmask
    bt eax, edi
    jnc cr_nextchar
    mov byte ptr [edi + 0x1d8575c], 0
    xor eax, eax
    mov dword ptr [{OCCMASK}], eax
    mov dword ptr [{OCCMASK} + 4], eax
    mov eax, edi
    imul eax, eax, 0x98
    lea edx, [eax + {NEWMAG} + 1]            ; qty byte of slot0 (id at edx-1)
    xor ecx, ecx
cr_slot:
    movzx esi, byte ptr [edx - 1]            ; id
    movzx ebx, byte ptr [edx]                ; qty
    test esi, esi
    je cr_slotnext
    test ebx, ebx
    je cr_notocc
    bts dword ptr [{OCCMASK}], ecx
cr_notocc:
    cmp esi, dword ptr [esp + 0x14]          ; id == spell ?
    jne cr_slotnext
    test ebx, ebx
    je cr_slotnext
    mov byte ptr [edi + 0x1d8575c], bl
    xor eax, eax
    mov dword ptr [{OCCMASK}], eax
    mov dword ptr [{OCCMASK} + 4], eax
cr_slotnext:
    inc ecx
    add edx, 2
    cmp ecx, 0x40
    jl cr_slot
    mov eax, dword ptr [{OCCMASK}]
    and eax, dword ptr [{OCCMASK} + 4]
    cmp eax, -1
    jne cr_nextchar
    mov byte ptr [edi + 0x1d8575c], 0xff
    bts ebp, edi
cr_nextchar:
    inc edi
    cmp edi, 8
    jl cr_char
    mov ecx, dword ptr [esp + 0x18]          ; charmask
    xor eax, eax
    cmp ebp, ecx
    setne al
    pop edi
    pop esi
    pop ebp
    pop ebx
    ret

; ---- battle_to_savemap: copy each party actor's battle table (BMAG) back to NEWMAG ------
battle_to_savemap:
    push ebx
    push ebp
    push esi
    push edi
    xor ebp, ebp                             ; actor k
bts_actor:
    cmp ebp, 3
    jge bts_done
    mov eax, ebp
    imul eax, eax, 0xd0
    cmp byte ptr [eax + 0x1d27bcb], 0xff
    je bts_done
    movzx eax, byte ptr [ebp + 0x1cfe74c]    ; char id
    imul eax, eax, 0x98
    lea edi, [eax + {NEWMAG}]                 ; dest magic (id at edi, qty edi+1)
    mov esi, ebp
    imul esi, esi, 0x1d0
    add esi, {BMAG}                           ; src battle table (id at esi, qty esi+1)
    mov ecx, 0x40
bts_copy:
    mov al, byte ptr [esi]
    mov byte ptr [edi], al
    mov al, byte ptr [esi + 1]
    mov byte ptr [edi + 1], al
    add esi, 5
    add edi, 2
    dec ecx
    jne bts_copy
    movzx eax, byte ptr [ebp + 0x1cfe74c]
    imul eax, eax, 0x98
    lea edi, [eax + {NEWMAG}]                 ; magic base for id scan
    lea ebx, [eax + 0x1cfe0e8 + 0x5c]         ; savemap junction slots (char+0x5c)
    xor edx, edx
bts_jloop:
    mov al, byte ptr [ebx + edx]
    xor ecx, ecx
bts_scan:
    cmp al, byte ptr [edi + ecx*2]
    je bts_keep
    inc ecx
    cmp ecx, 0x40
    jl bts_scan
    mov byte ptr [ebx + edx], 0
bts_keep:
    inc edx
    cmp edx, 0x14
    jl bts_jloop
    inc ebp
    jmp bts_actor
bts_done:
    pop edi
    pop esi
    pop ebp
    pop ebx
    ret

; ---- battle_rand_spell(actor, mode) -> random held spell id (or 0xff). Full rewrite. ----
battle_rand_spell:
    mov eax, dword ptr [esp + 4]             ; actor
    push esi
    push edi
    xor edi, edi
    lea ecx, [eax*8]
    sub ecx, eax
    lea esi, [eax + ecx*4]
    shl esi, 4
    add esi, 0x1cff000
    mov eax, dword ptr [esp + 0x10]          ; mode
    test eax, eax
    jne brs_ret
    lea eax, [esi + 0x82 + {DB}]
    mov ecx, 0x40
brs_count:
    cmp byte ptr [eax], 0
    je brs_c2
    inc edi
brs_c2:
    add eax, 5
    dec ecx
    jne brs_count
    test edi, edi
    jne brs_pick
    pop edi
    mov eax, 0xff
    pop esi
    ret
brs_pick:
    call 0x48f020
    and eax, 0xff
    cdq
    idiv edi
brs_walk:
    lea eax, [esi + edx*4 + 0x68 + {DB}]
    mov cl, byte ptr [edx + eax + 0x1a]
    test cl, cl
    jne brs_found
    inc edx
    and edx, 0x3f
    jmp brs_walk
brs_found:
    lea ecx, [esi + edx*4 + 0x68 + {DB}]
    xor eax, eax
    mov al, byte ptr [edx + ecx + 0x1a]
brs_ret:
    pop edi
    pop esi
    ret

; ---- battle_rand_spell40 partial hook @0x483D85 (esi=struct, bl=0x40, edi=0 on entry) ---
battle_rand_spell40:
    lea ecx, [esi + 0x82 + {DB}]
    mov edx, 0x40
brs40_count:
    mov al, byte ptr [ecx]
    test al, al
    je brs40_c2
    and eax, 0xff
    imul eax, eax, 0x3c
    test byte ptr [eax + 0x1cf406e], bl
    je brs40_c2
    inc edi
brs40_c2:
    add ecx, 5
    dec edx
    jne brs40_count
    test edi, edi
    jne brs40_pick
    mov eax, 0xff
    jmp 0x483dfa
brs40_pick:
    call 0x48f020
    and eax, 0xff
    mov ecx, eax
    and ecx, 0x8000003f
    jns brs40_p1
    dec ecx
    or ecx, 0xffffffc0
    inc ecx
brs40_p1:
    lea edx, [esi + ecx*4 + 0x68 + {DB}]
    mov al, byte ptr [ecx + edx + 0x1a]
    test al, al
    je brs40_wk
    and eax, 0xff
    imul eax, eax, 0x3c
    test byte ptr [eax + 0x1cf406e], bl
    jne brs40_found
brs40_wk:
    inc ecx
    and ecx, 0x3f
    jmp brs40_p1
brs40_found:
    lea eax, [esi + ecx*4 + 0x68 + {DB}]
    xor edx, edx
    mov dl, byte ptr [ecx + eax + 0x1a]
    mov eax, edx
    jmp 0x483dfa

; ---- swap_junctions entry detour: swap the two chars' NEWMAG magic, then run original ---
swap_junctions:
    pushad
    mov esi, dword ptr [esp + 0x24]          ; char1 (entry [esp+4])
    mov edi, dword ptr [esp + 0x38]          ; char2 (entry [esp+0x18])
    imul esi, esi, 0x98
    imul edi, edi, 0x98
    add esi, {NEWMAG}
    add edi, {NEWMAG}
    mov ecx, 0x80
sj_swap:
    mov al, byte ptr [esi]
    mov dl, byte ptr [edi]
    mov byte ptr [esi], dl
    mov byte ptr [edi], al
    inc esi
    inc edi
    dec ecx
    jne sj_swap
    popad
    sub esp, 0xa0
    jmp 0x4cb4a6

; ---- persistence: pack/unpack NEWMAG <-> dense qty[spell_id] in the saved old region --------
; The vanilla 32-slot region (char+0x10, 0x40 bytes) is still written to / read from the save
; but is now dead. At save we pack each char's 64-slot NEWMAG into it as a dense array
; dense[id]=qty (id 1..63; byte 0 = 0xFF signature). At load we unpack it, or - if byte 0 is
; not 0xFF - migrate the vanilla (id,qty) slots. 8 magic-holding characters (0..7).
mag_save_pack:
    pushad
    pushfd
    xor ebx, ebx
msp_c:
    cmp ebx, 8
    jge msp_d
    mov eax, ebx
    imul eax, eax, 0x98
    lea edi, [eax + 0x1cfe0f8]                 ; dense dest = savemap char+0x10
    push edi
    xor eax, eax
    mov ecx, 16
    rep stosd dword ptr es:[edi], eax          ; zero 64 bytes
    pop edi
    mov byte ptr [edi], 0xff                    ; signature
    mov eax, ebx
    imul eax, eax, 0x98
    lea esi, [eax + {NEWMAG}]                   ; src = NEWMAG[char]
    mov ecx, 0x40
msp_s:
    movzx eax, byte ptr [esi]                   ; slot id
    test eax, eax
    je msp_n
    cmp eax, 0x40
    jae msp_n
    mov dl, byte ptr [esi + 1]                  ; qty
    mov byte ptr [edi + eax], dl                ; dense[id] = qty
msp_n:
    add esi, 2
    dec ecx
    jne msp_s
    inc ebx
    jmp msp_c
msp_d:
    popfd
    popad
    ret

mag_load_unpack:
    pushad
    pushfd
    xor ebx, ebx
mlu_c:
    cmp ebx, 8
    jge mlu_d
    mov eax, ebx
    imul eax, eax, 0x98
    lea esi, [eax + 0x1cfe0f8]                  ; dense src = loaded savemap char+0x10
    mov eax, ebx
    imul eax, eax, 0x98
    lea edi, [eax + {NEWMAG}]                   ; dest = NEWMAG[char]
    push esi
    push edi
    xor eax, eax
    mov ecx, 0x20
    rep stosd dword ptr es:[edi], eax           ; zero NEWMAG[char] (128 bytes)
    pop edi
    pop esi
    cmp byte ptr [esi], 0xff
    jne mlu_van
    mov ecx, 1                                  ; dense: id 1..63
mlu_dl:
    mov al, byte ptr [esi + ecx]
    test al, al
    je mlu_dn
    mov byte ptr [edi], cl                      ; slot id
    mov byte ptr [edi + 1], al                  ; slot qty
    add edi, 2
mlu_dn:
    inc ecx
    cmp ecx, 0x40
    jl mlu_dl
    jmp mlu_cn
mlu_van:
    mov ecx, 16                                 ; vanilla: copy 32 (id,qty) slots as-is
    rep movsd dword ptr es:[edi], dword ptr [esi]
mlu_cn:
    inc ebx
    jmp mlu_c
mlu_d:
    popfd
    popad
    ret
"""

# persistence trampolines added by the builder (not in magic_sites): each runs the pack/unpack
# cave routine around the savemap<->disk transfer. (addr, nbytes, body, expected original hex)
PERSIST_TRAMPS = [
    (0x4E2F29, 5, "call mag_save_pack; push 0x13A4", "68a4130000"),        # menu save
    (0x47F57F, 5, "call mag_save_pack; push 0x13A4", "68a4130000"),        # new-game write
    (0x4E4F23, 8, "add esp, 0xC; call mag_load_unpack; call 0x495EF0", "83c40ce8c50ffbff"),  # load
]


def cave_source(tramps):
    """Full cave: fixed routines + hooks + one tr_<addr> routine per tramp site."""
    import re
    src = CAVE_FIXED + CAVE_HOOKS
    for addr, nbytes, body in tramps:
        src += "\ntr_%X:\n%s\njmp 0x%X\n" % (addr, body, addr + nbytes)
    src = subst(src)
    # any {name} left is an intra-cave label reference (e.g. a tramp calling fm_isfull);
    # keystone resolves it by bare name within the cave.
    return re.sub(r"\{(\w+)\}", r"\1", src)


def assemble_cave(tramps):
    import keystone
    src = cave_source(tramps)
    lines = []
    for ln in src.splitlines():
        ln = ln.split(";", 1)[0].rstrip()
        if ln.strip():
            lines.append(ln.strip())
    src = "\n".join(lines)
    ks = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_32)
    names = [ln[:-1] for ln in lines if ln.endswith(":")]
    enc, _ = ks.asm(src + "\n" + "\n".join(".long %s" % n for n in names), CODE)
    enc = bytes(enc)
    code = enc[:len(enc) - 4 * len(names)]
    table = enc[len(code):]
    labels = {n: int.from_bytes(table[4 * i:4 * i + 4], "little") for i, n in enumerate(names)}
    assert bytes(ks.asm(src, CODE)[0]) == code
    return code, labels


def collect(img):
    P = Patcher(img)
    for s in magic_sites.SITES:
        P.site(s)

    tramps = [(addr, args[0], args[1]) for addr, kind, args in P.deferred if kind == "tramp"]
    # 0x56DB20's tramp subsumes its two neighbouring rel pushes (0x56DB22/0x56DB27).
    tramps += [(a, n, body) for a, n, body, _ in PERSIST_TRAMPS]
    code, labels = assemble_cave(tramps)
    if CODE + len(code) > CODE_LIMIT:
        raise SystemExit("cave too large: %d bytes (limit %d)" % (len(code), CODE_LIMIT - CODE))

    def assemble_at(addr, text, nbytes, note):
        b = asm(subst(text, labels), addr)
        if len(b) > nbytes:
            raise SystemExit("%08X: %r assembled to %d bytes > %d" % (addr, text, len(b), nbytes))
        return addr, b + b"\x90" * (nbytes - len(b)), note

    def overwrite_len(addr):
        """Smallest whole number of instructions at addr totalling >= 5 bytes."""
        n = 0
        for i in _md.disasm(img.read(addr, 24), addr):
            n += i.size
            if n >= 5:
                return n
        raise SystemExit("%08X: cannot find >=5 byte instruction boundary" % addr)

    for addr, kind, args in P.deferred:
        if kind == "patch":
            nbytes, text = args
            P.patches.append(assemble_at(addr, text, nbytes, "patch: %s" % text))
        elif kind == "tramp":
            nbytes, text = args
            jmp = asm("jmp 0x%X" % labels["tr_%X" % addr], addr)
            P.patches.append((addr, jmp + b"\x90" * (nbytes - len(jmp)), "tramp -> tr_%X" % addr))
        elif kind == "hook":
            name = args[0]
            nbytes = overwrite_len(addr)
            jmp = asm("jmp 0x%X" % labels[name], addr)
            P.patches.append((addr, jmp + b"\x90" * (nbytes - len(jmp)), "hook -> %s" % name))

    for addr, nbytes, _body, expect in PERSIST_TRAMPS:
        have = img.read(addr, nbytes).hex()
        if have != expect:
            raise SystemExit("persist tramp %08X: have %s expected %s" % (addr, have, expect))
        jmp = asm("jmp 0x%X" % labels["tr_%X" % addr], addr)
        P.patches.append((addr, jmp + b"\x90" * (nbytes - len(jmp)), "persist tramp @%08X" % addr))
    return P, code, labels


# reserved memory regions that must be zero (unused) in the stock EXE
RESERVED = [
    ("NEWMAG", NEWMAG, 0x980), ("backups/masks", MBAK1, OCCMASK + 8 - MBAK1),
    ("BMAG", BMAG, 0x1D00), ("MAGBAK", MAGBAK, 0x980),
]


def check(img, P, code):
    if CODE + len(code) > CODE_LIMIT:
        raise SystemExit("cave too large: %d > %d" % (len(code), CODE_LIMIT - CODE))
    for name, a, n in RESERVED + [("CAVE", CODE, len(code))]:
        if img.read(a, n) != b"\0" * n:
            raise SystemExit("reserved region %s (%08X..%08X) is not empty in this EXE" % (name, a, a + n))
    spans = sorted((a, a + len(b), note) for a, b, note in P.patches)
    for (a0, a1, n0), (b0, b1, n1) in zip(spans, spans[1:]):
        if b0 < a1:
            raise SystemExit("patch overlap: %08X..%08X (%s) vs %08X.. (%s)" % (a0, a1, n0, b0, n1))


def build(exe=None):
    img = Image(exe or default_exe())
    P, code, labels = collect(img)
    check(img, P, code)
    h = Hext("All Magic Per Character (FF8 Steam 2013, FF8_EN.exe)")
    h.comment("Target: FF8_EN.exe sha1 03230c11328f8a1f9635435096e1659d9bfd002d (Steam 2013, English).")
    h.comment("Generated by tools/build_magic.py - edit that, not this file.")
    h.blank()
    h.protect(CODE & ~0xFFF, ((len(code) + 0xFFF) & ~0xFFF) + 0x1000, "code cave (executable)")
    h.write(CODE, code, "code cave (%d bytes): mask subsystems, hooks, trampolines" % len(code))
    h.blank()
    for a, b, note in sorted(P.patches):
        h.write(a, b, note)
    h.save(os.path.join(ROOT, "hext", "magic.hext"))
    write_modxml()
    return P, code, labels


def write_modxml():
    from xml.sax.saxutils import escape as e
    desc = ("Every character can hold up to 64 different magic spells (so all spells in the game, "
            "100 each) instead of the vanilla 32-slot limit. All menus, junction, draw/cast, refine "
            "and party swaps page through the full list. Saves keep working: the extra magic is "
            "stored in the save, and existing (pre-mod) saves are migrated on load. Requires the "
            "Steam 2013 English FF8_EN.exe.")
    xml = """<?xml version="1.0" encoding="utf-8"?>
<ModInfo>
  <ID>9b7e3c21-5d4a-4f0e-8c6b-1a2f3e4d5c03</ID>
  <Name>All Magic Per Character</Name>
  <Author>FF8Mods</Author>
  <Version>1.0</Version>
  <Description>%s</Description>
  <ReleaseNotes>Initial release.</ReleaseNotes>
  <ReleaseDate>2026-10-04</ReleaseDate>
  <Category>Gameplay</Category>
  <Link></Link>
  <DonationLink />
  <GameLanguage>EN</GameLanguage>
</ModInfo>
""" % e(desc)
    with open(os.path.join(ROOT, "mod.xml"), "w", newline="\r\n") as f:
        f.write(xml)


def main():
    import sys as _s
    P, code, labels = build(_s.argv[1] if len(_s.argv) > 1 else None)
    print("sites:", sum(P.counts.values()), "| cave: %d bytes, %d labels" % (len(code), len(labels)))
    print("patch sites written:", len(P.patches), "| skipped (not magic):", len(P.skipped))
    print("wrote", os.path.normpath(os.path.join(ROOT, "hext", "magic.hext")))


if __name__ == "__main__":
    main()
