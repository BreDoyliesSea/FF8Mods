"""Builds the "Unlimited GF Abilities" Junction VIII mod (FF8 Steam 2013, FF8_EN.exe).

Why GFs stop at 22 abilities
----------------------------
Every ability list the game shows or checks comes from one builder,
    0x4ACB70  int build(int gf, entry8 *out, int include_learnable)
which lists the GF's learned abilities, then the ones it can still learn, and stops
at 22 entries (0x16 checks at 0x4ACBD9, 0x4ACC4F, 0x4ACCC3). Teaching with an item
(0x4FC6C0) refuses once the list holds 22 (0x4FC712). All 14 callers pass buffers sized
exactly 22*8 bytes, and the three menus that show the list (GF menu, item teach/forget,
junction GF info) only know two pages of 11 rows.

What this mod changes
---------------------
* All three caps become 127 (more abilities than exist).
* Callers that keep the buffer on the stack have their frames grown by 0x350 bytes
  (room for 128 entries; see frame.py).
* One shared 1 KB "full list" buffer lives in the unused tail of the EXE's header
  page (0x400400). The three menus keep their original 22-entry buffers, which now act
  as a two-page window onto the full list. When you press Right on the last page (or Left
  on the first), the window slides by one page, so every page can be reached. The menu
  code itself is unchanged. Each refresh rebuilds the list from the save data, so the
  shared buffer never holds stale data.
* Page numbers and the left/right arrows reflect the real page.
* In the junction menu's GF info popup (two columns of 11), Left/Right flip between
  sets of 22 abilities.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ff8hext import Hext, asm, hexbytes, Image, default_exe  # noqa: E402
import frame  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "UnlimitedGFAbilities")

BUILDER = 0x4ACB70
SOUND = 0x4B92A0          # play menu sound effect (cdecl, 1 arg)
KEYS = 0x1D76A9C          # menu keys with auto-repeat (0x2000 right, 0x8000 left)
MAXCAP = 0x7F

# ---- memory we add ----
FULL = 0x400400           # 128 * 8 bytes, unused tail of the PE header page
CTX_GFM = 0x400800        # per-menu context, see refresh()
CTX_ITM = 0x400820
CTX_JNF = 0x400840
DATA_END = 0x400860
CODE = 0xB68940           # zero padding at the end of .text (Triple Triad mod uses 0xB68E00+)
CODE_LIMIT = 0xB68E00

# context layout (dwords)
GF, FLAG, W, TOTAL, WINDOW, COUNTVAR, STEP = range(0, 0x1C, 4)

MENUS = {
    # ctx: (window buffer, count variable, slide step)
    CTX_GFM: (0x1D7D9F0, 0x1D7DAA0, 11),
    CTX_ITM: (0x1D8DD30, 0x1D8DDE8, 11),
    CTX_JNF: (0x1D8B5D0, 0x1D8B140, 22),
}

FRAMES = [
    # entry, frame size, end, expected above-frame accesses
    (0x4A6680, 0xC8, 0x4A6CA6, 0),   # after-battle AP / learning
    (0x4B2EB0, 0xB0, 0x4B2F25, 0),   # learn every ability whose AP is full
    (0x4C2B40, 0xB0, 0x4C2BB9, 0),   # union of learned menu abilities (0x5C..0x73)
    (0x4D7110, 0xB0, 0x4D7180, 1),   # highest GF level among GFs that know ability X
    (0x4D7180, 0xC0, 0x4D73F4, 1),   # same, menu-ability variant
]
DELTA = (128 - 22) * 8


def cave_source():
    """Assembly for the code cave. {NAME} placeholders are filled from globals()."""
    return r"""
; ---------------------------------------------------------------- refresh
; ebx = context. Rebuilds the GF's list into FULL, clamps W, copies the window
; (up to 22 entries) into the menu's buffer and stores the window count.
; Preserves all registers.
refresh:
    pushad
    push dword ptr [ebx+{FLAG}]
    push {FULL}
    push dword ptr [ebx+{GF}]
    call {BUILDER}
    add esp, 12
    mov dword ptr [ebx+{TOTAL}], eax
    mov ecx, dword ptr [ebx+{W}]
r_clamp:
    test ecx, ecx
    jz r_ok
    lea edx, [ecx+22]
    sub edx, dword ptr [ebx+{STEP}]
    cmp edx, eax
    jl r_ok
    sub ecx, dword ptr [ebx+{STEP}]
    jmp r_clamp
r_ok:
    mov dword ptr [ebx+{W}], ecx
    mov edx, eax
    sub edx, ecx
    cmp edx, 22
    jle r_n1
    mov edx, 22
r_n1:
    test edx, edx
    jge r_n2
    xor edx, edx
r_n2:
    mov eax, dword ptr [ebx+{COUNTVAR}]
    mov dword ptr [eax], edx
    lea esi, [ecx*8+{FULL}]
    mov edi, dword ptr [ebx+{WINDOW}]
    lea ecx, [edx*2]
    cld
    rep movsd dword ptr es:[edi], dword ptr [esi]
    popad
    ret

; ---------------------------------------------------------------- build thunks
; Replace `call BUILDER` at the menu call sites. Stack: [esp+4]=gf [esp+8]=buf [esp+12]=flag
gfm_build:                 ; GF menu: reset window, return full total
    push ebx
    mov ebx, {CTX_GFM}
    call thunk_args_reset
    mov eax, dword ptr [ebx+{TOTAL}]
    pop ebx
    ret
itm_build_total:           ; item teach: reset window, return full total
    push ebx
    mov ebx, {CTX_ITM}
    call thunk_args_reset
    mov eax, dword ptr [ebx+{TOTAL}]
    pop ebx
    ret
itm_build_reset:           ; item list opened: reset window, return window count
    push ebx
    mov ebx, {CTX_ITM}
    call thunk_args_reset
    jmp thunk_ret_window
itm_build_keep:            ; item list rebuilt after forgetting: keep window
    push ebx
    mov ebx, {CTX_ITM}
    call thunk_args_keep
    jmp thunk_ret_window
jnf_build:                 ; junction GF info popup: reset window, return window count
    push ebx
    mov ebx, {CTX_JNF}
    call thunk_args_reset
thunk_ret_window:
    mov eax, dword ptr [ebx+{COUNTVAR}]
    mov eax, dword ptr [eax]
    pop ebx
    ret
; helpers: called from a thunk, so the builder args are at [esp+12] (ret, ebx, ret)
thunk_args_reset:
    mov dword ptr [ebx+{W}], 0
thunk_args_keep:
    mov eax, dword ptr [esp+12]
    cmp eax, dword ptr [ebx+{GF}]
    je tak_same
    mov dword ptr [ebx+{W}], 0
tak_same:
    mov dword ptr [ebx+{GF}], eax
    mov eax, dword ptr [esp+20]
    mov dword ptr [ebx+{FLAG}], eax
    call refresh
    ret

; item list: scan after rebuild-on-forget walks the full list
itm_scanprep:
    mov eax, {FULL}
    mov ecx, dword ptr [{CTX_ITM}+{TOTAL}]
    ret

; ---------------------------------------------------------------- GF menu paging
gf_next:                   ; replaces 4D2C0D: mov cl,[esi+36]; test cl,cl; jne 4D2C56
    mov cl, byte ptr [esi+0x36]
    test cl, cl
    jnz gn_p1
    jmp 0x4D2C14
gn_p1:
    pushad
    mov ebx, {CTX_GFM}
    mov eax, dword ptr [ebx+{W}]
    add eax, 22
    cmp eax, dword ptr [ebx+{TOTAL}]
    jge gn_none
    add dword ptr [ebx+{W}], 11
    call refresh
    popad
    jmp 0x4D2C48           ; same exit as a normal page turn (state 0x19 refreshes info)
gn_none:
    popad
    jmp 0x4D2C56

gf_prev:                   ; replaces 4D2C5F: mov al,[esi+36]; test al,al; je 4D399A
    mov al, byte ptr [esi+0x36]
    test al, al
    jz gp_p0
    jmp 0x4D2C6A
gp_p0:
    pushad
    mov ebx, {CTX_GFM}
    cmp dword ptr [ebx+{W}], 0
    je gp_none
    sub dword ptr [ebx+{W}], 11
    call refresh
    popad
    jmp 0x4D2CA3           ; normal "went to page 0" exit (state 0x1B)
gp_none:
    popad
    jmp 0x4D399A

gf_locate:                 ; replaces 4D338D: mov ebp,[count]. ecx = ability being learned
    pushad
    mov ebx, {CTX_GFM}
    movzx eax, byte ptr [esi+0x31]
    mov dword ptr [ebx+{GF}], eax
    mov dword ptr [ebx+{FLAG}], 1
    mov dword ptr [ebx+{W}], 0
    call refresh
    mov edx, dword ptr [ebx+{TOTAL}]
    xor eax, eax
gl_find:
    cmp eax, edx
    jge gl_nf
    cmp byte ptr [eax*8+{FULL}], cl
    je gl_found
    inc eax
    jmp gl_find
gl_found:
    push eax
    xor edx, edx
    mov ecx, 11
    div ecx
    imul eax, eax, 11
    mov dword ptr [ebx+{W}], eax
    call refresh
    pop eax
    sub eax, dword ptr [ebx+{W}]
    mov dword ptr [esp+0x1C], eax      ; pushad slot of eax
    popad
    mov ebp, dword ptr [{COUNT_GFM}]
    jmp 0x4D33AE
gl_nf:
    popad
    mov ebp, dword ptr [{COUNT_GFM}]
    mov eax, ebp
    jmp 0x4D33AE

; ---------------------------------------------------------------- item menu paging
; ebx = current page (0/1), esi = menu task
it_prev:                   ; replaces 4FAAFB: test ebx,ebx; je 4FAB05; mov word [esi+10],46
    test ebx, ebx
    jz ip_p0
    mov word ptr [esi+0x10], 0x46
    jmp 0x4FAB05
ip_p0:
    pushad
    mov ebx, {CTX_ITM}
    cmp dword ptr [ebx+{W}], 0
    je ip_none
    sub dword ptr [ebx+{W}], 11
    call refresh
    push 1
    call {SOUND}
    add esp, 4
ip_none:
    popad
    jmp 0x4FAB05

it_next:                   ; replaces 4FAB0D: test ebx,ebx; jne 4FAB17; mov word [esi+10],48
    test ebx, ebx
    jnz in_p1
    mov word ptr [esi+0x10], 0x48
    jmp 0x4FAB17
in_p1:
    pushad
    mov ebx, {CTX_ITM}
    mov eax, dword ptr [ebx+{W}]
    add eax, 22
    cmp eax, dword ptr [ebx+{TOTAL}]
    jge in_none
    add dword ptr [ebx+{W}], 11
    call refresh
    push 1
    call {SOUND}
    add esp, 4
in_none:
    popad
    jmp 0x4FAB17

; ---------------------------------------------------------------- junction GF info popup
jnf_input:                 ; called from 4DF877, replaces: mov bl,[esp+18]; mov edi,47
    pushad
    mov ebx, {CTX_JNF}
    mov eax, dword ptr [{KEYS}]
    test eax, 0x2000
    jz jn_left
    mov ecx, dword ptr [ebx+{W}]
    add ecx, 22
    cmp ecx, dword ptr [ebx+{TOTAL}]
    jge jn_done
    mov dword ptr [ebx+{W}], ecx
    jmp jn_moved
jn_left:
    test eax, 0x8000
    jz jn_done
    cmp dword ptr [ebx+{W}], 0
    je jn_done
    sub dword ptr [ebx+{W}], 22
jn_moved:
    call refresh
    push 1
    call {SOUND}
    add esp, 4
jn_done:
    popad
    mov bl, byte ptr [esp+0x1C]
    mov edi, 0x47
    ret

; ---------------------------------------------------------------- page number / arrows
; arrows: in cl = page (0/1); out ecx = 1 (left) | 2 (right); eax, edx preserved
gf_arrows:
    push ebx
    mov ebx, {CTX_GFM}
    jmp arrows
it_arrows:
    push ebx
    mov ebx, {CTX_ITM}
arrows:
    push eax
    movzx ecx, cl
    xor eax, eax
    test ecx, ecx
    jnz ar_l
    cmp dword ptr [ebx+{W}], 0
    je ar_nol
ar_l:
    or eax, 1
ar_nol:
    test ecx, ecx
    jz ar_r
    push edx
    mov edx, dword ptr [ebx+{W}]
    add edx, 22
    cmp edx, dword ptr [ebx+{TOTAL}]
    pop edx
    jge ar_nor
ar_r:
    or eax, 2
ar_nor:
    mov ecx, eax
    pop eax
    pop ebx
    ret

gf_pnum:                   ; replaces 4D3C89: and ecx,0FFh  -> ecx = page + W/11
    movzx ecx, cl
    push eax
    push edx
    push ebx
    mov eax, dword ptr [{CTX_GFM}+{W}]
    xor edx, edx
    mov ebx, 11
    div ebx
    add ecx, eax
    pop ebx
    pop edx
    pop eax
    ret

it_pnum:                   ; replaces 4FCE2D: xor eax,eax; add ebp,28h; mov al,cl
    push edx
    push ebx
    mov eax, dword ptr [{CTX_ITM}+{W}]
    xor edx, edx
    mov ebx, 11
    div ebx
    movzx ebx, cl
    add eax, ebx
    pop ebx
    pop edx
    add ebp, 0x28
    ret
"""


def fmt_source():
    names = dict(BUILDER=BUILDER, SOUND=SOUND, KEYS=KEYS, FULL=FULL,
                 CTX_GFM=CTX_GFM, CTX_ITM=CTX_ITM, CTX_JNF=CTX_JNF,
                 COUNT_GFM=MENUS[CTX_GFM][1],
                 GF=GF, FLAG=FLAG, W=W, TOTAL=TOTAL, WINDOW=WINDOW, COUNTVAR=COUNTVAR, STEP=STEP)
    src = cave_source()
    for k, v in names.items():
        src = src.replace("{%s}" % k, "0x%X" % v)
    lines = []
    for ln in src.splitlines():
        ln = ln.split(";", 1)[0].rstrip()
        if ln.strip():
            lines.append(ln.strip())
    return "\n".join(lines)


def assemble_cave():
    import keystone
    src = fmt_source()
    ks = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_32)
    names = [ln[:-1] for ln in src.splitlines() if ln.endswith(":")]
    # append a table of label addresses, read it back, then drop it from the code
    enc, _ = ks.asm(src + "\n" + "\n".join(".long %s" % n for n in names), CODE)
    enc = bytes(enc)
    code = enc[:len(enc) - 4 * len(names)]
    table = enc[len(code):]
    labels = {n: int.from_bytes(table[4 * i:4 * i + 4], "little") for i, n in enumerate(names)}
    assert bytes(ks.asm(src, CODE)[0]) == code
    return code, labels


class Patcher:
    def __init__(self, img):
        self.img = img
        self.patches = []   # (addr, bytes, note)

    def put(self, addr, new, expect=None, note=""):
        if expect is not None:
            expect = bytes.fromhex(expect) if isinstance(expect, str) else expect
            have = self.img.read(addr, len(expect))
            if have != expect:
                raise SystemExit("unexpected bytes at %08X: have %s, expected %s (%s)" % (addr, have.hex(), expect.hex(), note))
        self.patches.append((addr, bytes(new), note))

    def call(self, at, target, expect, note):
        b = asm("call 0x%X" % target, at)
        n = len(bytes.fromhex(expect))
        self.put(at, b + b"\x90" * (n - len(b)), expect, note)

    def jmp(self, at, target, expect, note):
        b = asm("jmp 0x%X" % target, at)
        n = len(bytes.fromhex(expect))
        assert len(b) == 5
        self.put(at, b + b"\x90" * (n - len(b)), expect, note)

    def imm32(self, at, opcode_len, old, new, note):
        raw = self.img.read(at, opcode_len + 4)
        assert int.from_bytes(raw[opcode_len:], "little") == old, (hex(at), raw.hex(), note)
        self.put(at + opcode_len, new.to_bytes(4, "little"), raw[opcode_len:], note)


def collect(img):
    code, L = assemble_cave()
    if CODE + len(code) > CODE_LIMIT:
        raise SystemExit("cave too large: %d bytes" % len(code))
    if img.read(CODE, len(code)) != b"\0" * len(code):
        raise SystemExit("code cave is not empty in this EXE")
    if img.read(FULL, DATA_END - FULL) != b"\0" * (DATA_END - FULL):
        raise SystemExit("header-page area is not empty in this EXE")
    P = Patcher(img)

    # 1. caps
    P.put(0x4ACBD9, bytes([0x83, 0xFB, MAXCAP]), "83FB16", "builder: learned-ability cap")
    P.put(0x4ACC4F, bytes([0x83, 0xFF, MAXCAP]), "83FF16", "builder: learnable-ability cap")
    P.put(0x4ACCC3, bytes([0x83, 0xFF, MAXCAP]), "83FF16", "builder: learnable (item list) cap")
    P.put(0x4FC712, bytes([0x83, 0xF8, MAXCAP]), "83F816", "item teach: 'GF is full' check")

    # 2. stack frames
    for entry, fsize, end, nabove in FRAMES:
        ps, above = frame.enlarge(img, entry, fsize, end, DELTA, expect_above=nabove)
        for a, b in ps:
            P.put(a, b, img.read(a, len(b)), "frame %08X: %X -> %X" % (entry, fsize, fsize + DELTA))

    # 3. builder call sites
    def site(call_at, target, note):
        P.call(call_at, target, "E8" + (BUILDER - (call_at + 5) & 0xFFFFFFFF).to_bytes(4, "little").hex(), note)

    nop5 = b"\x90" * 5
    # GF menu: open list / next GF / previous GF
    for call_at, store_at, scan_at, scan_op in ((0x4D2F13, 0x4D2F24, 0x4D2F37, "BA"),
                                                 (0x4D311D, 0x4D312E, 0x4D3141, "BF"),
                                                 (0x4D3251, 0x4D3262, 0x4D3275, "BF")):
        site(call_at, L["gfm_build"], "GF menu: build into full list + window")
        P.put(store_at, nop5, "A3A0DAD701", "GF menu: window count already stored")
        P.put(scan_at, bytes.fromhex(scan_op) + FULL.to_bytes(4, "little"), scan_op + "F0D9D701",
              "GF menu: 'is the current learning ability listed' scan uses the full list")
    # item menu
    site(0x4FA7C7, L["itm_build_reset"], "item menu: list opened")
    site(0x4FB267, L["itm_build_keep"], "item menu: list rebuilt after forgetting")
    P.call(0x4FB2B8, L["itm_scanprep"], "B830DDD801", "item menu: learning-ability scan uses full list")
    site(0x4FC6E6, L["itm_build_total"], "item teach: build full list")
    P.put(0x4FC6F4, nop5, "A3E8DDD801", "item teach: window count already stored")
    P.put(0x4FC6FD, b"\xB9" + FULL.to_bytes(4, "little"), "B930DDD801", "item teach: search full list")
    P.imm32(0x4FC77A, 3, 0x1D8DD32, FULL + 2, "item teach: read entry state from full list")
    P.imm32(0x4FC79C, 3, 0x1D8DD30, FULL, "item teach: read entry id from full list")
    # junction menu
    site(0x4DF745, L["jnf_build"], "junction GF info popup")
    P.put(0x4E2C6B, b"\x68" + FULL.to_bytes(4, "little"), "68D0B5D801", "junction: per-GF command scan builds into full list")
    P.put(0x4E2C8B, b"\xBA" + FULL.to_bytes(4, "little"), "BAD0B5D801", "junction: per-GF command scan reads full list")

    # 4. paging
    P.jmp(0x4D2C0D, L["gf_next"], "8A4E3684C97542", "GF menu: Right on last page slides the window")
    P.jmp(0x4D2C5F, L["gf_prev"], "8A463684C00F84" + (0x4D399A - (0x4D2C64 + 6) & 0xFFFFFFFF).to_bytes(4, "little").hex(),
          "GF menu: Left on first page slides the window")
    P.jmp(0x4D338D, L["gf_locate"], "8B2DA0DAD701", "GF menu: open the list on the ability being learned")
    P.jmp(0x4FAAFB, L["it_prev"], "85DB740666C746104600", "item menu: Left on first page slides the window")
    P.jmp(0x4FAB0D, L["it_next"], "85DB750666C746104800", "item menu: Right on last page slides the window")
    P.call(0x4DF877, L["jnf_input"], "8A5C2418BF47000000", "junction GF info: Left/Right flip 22 abilities")

    # 5. page indicator
    P.call(0x4D3C89, L["gf_pnum"], "81E1FF000000", "GF menu: page number")
    P.call(0x4D3CAA, L["gf_arrows"], "F6D91BC983C102", "GF menu: page arrows")
    P.call(0x4FCE2D, L["it_pnum"], "33C083C5288AC1", "item menu: page number")
    P.call(0x4FCE4F, L["it_arrows"], "F6D91BC983C102", "item menu: page arrows")

    # data
    data = bytearray(DATA_END - CTX_GFM)
    for ctx, (win, cnt, step) in MENUS.items():
        o = ctx - CTX_GFM
        data[o + WINDOW:o + WINDOW + 4] = win.to_bytes(4, "little")
        data[o + COUNTVAR:o + COUNTVAR + 4] = cnt.to_bytes(4, "little")
        data[o + STEP:o + STEP + 4] = step.to_bytes(4, "little")
    return code, L, P.patches, bytes(data)


def build(exe=None):
    img = Image(exe or default_exe())
    code, L, patches, data = collect(img)
    h = Hext("Unlimited GF Abilities (FF8 Steam 2013, FF8_EN.exe)")
    h.comment("Target: FF8_EN.exe sha1 03230c11328f8a1f9635435096e1659d9bfd002d (Steam 2013, English).")
    h.comment("Generated by tools/build_gf_abilities.py - edit that, not this file.")
    h.blank()
    h.protect(FULL & ~0xFFF, 0x1000, "header page tail (0x400400+) holds the full ability list and menu state")
    h.protect(CODE, len(code), "code cave at the end of .text")
    h.write(CTX_GFM, data, "menu contexts: gf, flag, window start, total, window buffer, count variable, step")
    h.write(CODE, code, "code cave (%d bytes)" % len(code))
    h.blank()
    for a, b, note in patches:
        h.write(a, b, note)
    h.save(os.path.join(ROOT, "hext", "gf_abilities.hext"))
    write_modxml()
    return code, L, patches


def write_modxml():
    from xml.sax.saxutils import escape as e
    desc = ("Removes the 22-ability limit per GF. GFs can learn every ability they are taught, "
            "and the GF menu, the item teach/forget list and the junction GF info popup page "
            "through all of them (Left/Right). Requires the Steam 2013 English FF8_EN.exe.")
    xml = """<?xml version="1.0" encoding="utf-8"?>
<ModInfo>
  <ID>9b7e3c21-5d4a-4f0e-8c6b-1a2f3e4d5c02</ID>
  <Name>Unlimited GF Abilities</Name>
  <Author>BreDoyliesSea</Author>
  <Version>1.0</Version>
  <Description>%s</Description>
  <ReleaseNotes>Initial release.</ReleaseNotes>
  <ReleaseDate>2026-10-05</ReleaseDate>
  <Category>Gameplay</Category>
  <Link>https://github.com/BreDoyliesSea/FF8Mods-releases</Link>
  <DonationLink />
  <GameLanguage>EN</GameLanguage>
</ModInfo>
""" % e(desc)
    with open(os.path.join(ROOT, "mod.xml"), "w", newline="\r\n") as f:
        f.write(xml)


if __name__ == "__main__":
    code, L, patches = build(sys.argv[1] if len(sys.argv) > 1 else None)
    print("built %s: cave %d bytes, %d patch sites" % (os.path.normpath(ROOT), len(code), len(patches)))
