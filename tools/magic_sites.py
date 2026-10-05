"""Reviewed list of every place FF8_EN.exe touches character magic, and what the
"64 magic slots" mod does there. Consumed by build_magic.py.

Design (see build_magic.py): each character's 32 magic slots (savemap char + 0x10, 64 bytes)
move to NEWMAG + c*0x98 (128 bytes = 64 slots), keeping the 0x98 stride. For an absolute
address A inside a character's magic area the new address is A + D, D = NEWMAG - 0x1CFE0F8.

Site kinds
  rel   instruction holds an absolute magic address (or a per-character magic base used as a
        loop sentinel, e.g. char8 + 0x10). Replace it with A + D.
  end   instruction holds the end of a character's magic list (char + 0x50 / 0x51).
        Replace it with A + D + 0x40 (end of the 64-slot list).
  disp  memory operand [reg + disp32] where reg holds a *relocated magic pointer*, but the
        access targets another character field (exists flag, commands, ...). New disp =
        disp - D, so it still hits the savemap field.
  asm   replace the instruction with the given assembly (same length), e.g. slot count
        0x20 -> 0x40 or byte size 0x40 -> 0x80. The original text is checked.
  x     (addr, "x", old_imm, new_imm): change one immediate in the instruction (slot counts
        0x20 -> 0x40, last slot 0x1F -> 0x3F, byte sizes 0x40 -> 0x80). Checked.
  brel  absolute address inside the battle magic table (battle char k at 0x1CFF082 + k*0x1D0,
        32 entries of 5 bytes). Relocated like `rel` to BMAG (64 entries, same 0x1D0 stride).
  bend  end of a battle magic table (entry 32) -> entry 64.
  bdisp [reg + disp32] where reg is a battle character struct (0x1CFF000 + k*0x1D0) and disp
        points into its magic table: disp += DB.
  tramp (addr, "tramp", nbytes, asm): overwrite nbytes (whole instructions, no branch targets
        inside except addr) with a jump to new code running `asm` (may use {D}, {DB}, {NEWMAG},
        {BMAG}), then jump back to addr + nbytes.
  patch (addr, "patch", nbytes, asm): assemble `asm` at addr in place (NOP-padded to nbytes).
        May reference cave labels / data as {name}.
  skip  not character magic (GF loop sentinel, command field, ...). Reason given.
  hook  handled by a custom routine in build_magic.py (named).
"""

SITES = [
    # ---- 0x47ED90 can_take_magic(char, spell): is there room / not at 100
    (0x47EDAD, "rel"),
    (0x47EDC2, "asm", "cmp eax, 0x20", "cmp eax, 0x40"),
    (0x47EDD4, "asm", "cmp eax, 0x20", "cmp eax, 0x40"),
    (0x47EDEE, "rel"),
    # ---- 0x47EE00 add_one_magic(char, spell)
    (0x47EE1F, "rel"),
    (0x47EE34, "asm", "cmp esi, 0x20", "cmp esi, 0x40"),
    (0x47EE46, "asm", "cmp ecx, 0x20", "cmp ecx, 0x40"),
    (0x47EE5E, "rel"), (0x47EE6D, "rel"), (0x47EE91, "rel"), (0x47EE97, "rel"), (0x47EEA0, "rel"),
    # ---- 0x48B7E0 / 0x48B8B0 battle start/end: mark party spells in a bitmask
    (0x48B815, "asm", "mov edi, 0x20", "mov edi, 0x40"),
    (0x48B81D, "rel"),
    (0x48B902, "asm", "mov edi, 0x20", "mov edi, 0x40"),
    (0x48B90A, "rel"),
    # ---- 0x4C3120 clear ids of empty slots
    (0x4C312A, "asm", "mov ecx, 0x20", "mov ecx, 0x40"),
    (0x4C312F, "rel"),
    # ---- 0x56DB20 move char5 magic to char6 (memcpy 0x40, then zero 4*16 bytes)
    # push 0x80 can't be a 2-byte imm8 (it would sign-extend to -128 and the memcpy, which
    # tests the length with `jle`, would copy nothing), so the whole 3-push arg setup is a
    # trampoline that pushes 0x80 and the two relocated magic pointers.
    (0x56DB20, "tramp", 12, "push 0x80; push {RELOC_1CFE3F0}; push {RELOC_1CFE488}"),
    (0x56DB31, "asm", "push 4", "push 8"),
    (0x56DB33, "rel"),
    # ---- 0x56DB50 hand char7's magic out to the other characters, then clear it
    (0x56DB55, "rel"),
    (0x56DB81, "rel"),
    (0x56DB86, "disp"),                      # test [magptr+0x84] = char exists flag
    (0x56DBA3, "asm", "cmp eax, 0x20", "cmp eax, 0x40"),
    (0x56DBB7, "rel"), (0x56DBC8, "rel"),
    (0x56DBE2, "rel"),                       # char8 magic base: loop end over characters
    (0x56DBF4, "rel"),
    (0x56DBF9, "disp"),
    (0x56DC0F, "asm", "cmp eax, 0x20", "cmp eax, 0x40"),
    (0x56DC1B, "rel"),
    (0x56DC35, "rel"),
    (0x56DC48, "rel"),
    (0x56DC4D, "disp"),
    (0x56DC6A, "asm", "cmp eax, 0x20", "cmp eax, 0x40"),
    (0x56DC7C, "asm", "cmp eax, 0x20", "cmp eax, 0x40"),
    (0x56DC88, "rel"),
    (0x56DCA3, "rel"), (0x56DCA9, "rel"),
    (0x56DCB6, "end"),                       # char7 qty end
    (0x56DCC5, "asm", "push 4", "push 8"),
    (0x56DCC7, "rel"),

    # ---- 0x47EEF0 / 0x482950 debug new-game setup: fills 30 + 20 spells for character pairs
    (0x47F643, "skip", "GF loop end (stride 0x44)"),
    (0x47F668, "skip", "GF loop end (stride 0x44)"),
    (0x47F6B3, "rel"),
    (0x47F6EE, "rel", 0x1CFE651),           # char9 qty: end of the 2-characters-per-pass loop
    (0x47F6F6, "skip", "commands"), (0x47F6FD, "skip", "commands"),
    (0x47F70B, "skip", "commands"), (0x47F712, "skip", "commands"),
    (0x47F720, "skip", "commands"), (0x47F727, "skip", "commands"),
    (0x482A6E, "skip", "GF loop end"), (0x482A98, "skip", "GF loop end"),
    (0x482AE3, "rel"),
    (0x482B22, "rel", 0x1CFE651),
    (0x482B2E, "skip", "commands"), (0x482B39, "skip", "commands"), (0x482B4B, "skip", "commands"),
    (0x482B51, "skip", "commands"), (0x482B57, "skip", "commands"), (0x482B5D, "skip", "commands"),
    # ---- GF loops that end at 0x1CFE0F9 / 0x1CFE0FA / 0x1CFE0FC (not magic)
    (0x485AC8, "skip", "GF loop end"), (0x490CA7, "skip", "GF loop end"),
    (0x49571B, "skip", "GF loop end"), (0x495EDB, "skip", "GF loop end"), (0x495F3B, "skip", "GF loop end"),
    (0x495729, "skip", "commands pointer"),
    # ---- 0x495530 battle setup: clear the battle magic table (32 x 5 bytes)
    (0x495662, "bdisp"),
    (0x495668, "asm", "mov ecx, 0x20", "mov ecx, 0x40"),
    # ---- 0x496310 junction stat helper: find junctioned spell's quantity
    (0x49633F, "rel"),
    (0x496351, "asm", "cmp eax, 0x20", "cmp eax, 0x40"),
    (0x4963CB, "rel"),
    # ---- 0x486A10 battle: add one / remove one spell in the battle table (draw, cast)
    (0x486A44, "brel"),
    (0x486A5E, "asm", "cmp eax, 0x20", "cmp eax, 0x40"),
    (0x486A70, "asm", "cmp eax, 0x20", "cmp eax, 0x40"),
    (0x486A82, "brel"), (0x486AA4, "brel"), (0x486AAA, "brel"), (0x486AB2, "brel"),
    (0x486ADC, "brel"),
    (0x486AEE, "asm", "cmp eax, 0x20", "cmp eax, 0x40"),
    (0x486B02, "brel"), (0x486B0E, "brel"), (0x486B1B, "brel"),
    # ---- 0x486CD0 battle end: copy battle table back to the savemap -> rewritten
    (0x486CD0, "hook", "battle_to_savemap"),

    # ---- 0x496440 / 0x496960 / 0x496B50 junction stat bonuses: quantity of the junctioned spell
    (0x49662E, "rel"), (0x496644, "x", 0x20, 0x40), (0x4966E5, "rel"),
    (0x4966FB, "rel"), (0x49670D, "x", 0x20, 0x40), (0x496788, "rel"),
    (0x49683C, "rel"), (0x49684E, "x", 0x20, 0x40), (0x496893, "rel"),
    (0x4968D0, "rel"), (0x4968E2, "x", 0x20, 0x40), (0x496921, "rel"),
    (0x496990, "rel"), (0x4969A2, "x", 0x20, 0x40), (0x4969D1, "rel"),
    (0x496A3B, "rel"), (0x496A4D, "x", 0x20, 0x40), (0x496AAE, "rel"),
    (0x496B80, "rel"), (0x496B92, "x", 0x20, 0x40), (0x496BC1, "rel"),
    (0x496C2C, "rel"), (0x496C3E, "x", 0x20, 0x40), (0x496C9D, "rel"),
    # ---- 0x48D7E0 battle: is spell in the battle table
    (0x48D802, "brel"), (0x48D814, "x", 0x20, 0x40),
    # ---- 0x4C8820 battle Magic menu: table getter; menu opened with 0x20 rows at 0x4BC902
    (0x4C8833, "brel"),
    (0x4BC902, "x", 0x20, 0x40),

    # ---- GF loops (stride 0x44) whose end sentinel lands in char0 magic
    (0x4AD0AC, "skip", "GF loop end"), (0x4AD305, "skip", "GF loop end"), (0x4BEC35, "skip", "GF loop end"),
    # ---- 0x4BE790 tidy a character's magic, drop junctions of spells no longer held
    (0x4BE7BE, "x", 0x20, 0x40), (0x4BE7C6, "rel"),
    # ---- 0x4C2C70 add_magic(char, spell, qty): uses a 32-bit free-slot mask -> rewritten
    (0x4C2C70, "hook", "add_magic"),
    (0x4C2C84, "skip", "inside rewritten add_magic"), (0x4C2D11, "skip", "inside rewritten add_magic"),
    (0x4C2D17, "skip", "inside rewritten add_magic"),
    # ---- 0x4C2D50 remove_magic(char, spell, qty)
    (0x4C2D66, "rel"), (0x4C2D7F, "x", 0x20, 0x40),

    # ---- 0x4D7110..0x4D9100 magic menu (use / exchange / draw-target states)
    (0x4D716B, "skip", "GF loop end"), (0x4D7262, "skip", "GF loop end"),
    (0x4D7747, "rel"), (0x4D774D, "rel"),           # [esi+0x4A] = selected slot index (byte)
    (0x4D7809, "rel"), (0x4D781E, "x", 0x20, 0x40),
    (0x4D7BD7, "rel"), (0x4D7BEE, "x", 0x20, 0x40),
    (0x4D8CE7, "rel"),                              # magic list base for the generic list callback
    (0x4D8E39, "rel"), (0x4D8E5A, "x", 0x20, 0x40),
    (0x4D8EC3, "rel"), (0x4D8EDE, "x", 0x20, 0x40), (0x4D8F01, "x", 0x20, 0x40),
    # ---- 0x4D9000 can_receive(spell, charmask): 32-bit "all slots full" mask -> rewritten
    (0x4D9000, "hook", "can_receive"),
    (0x4D9009, "skip", "inside rewritten can_receive"), (0x4D90B4, "skip", "inside rewritten can_receive"),

    # ---- magic menu list UI: 4 rows per page, slot = page*4 + row ([esi+0x4A]); 8 pages -> 16
    (0x4D8691, "x", 7, 0xF),                     # previous page wraps to the last page
    (0x4D87CE, "x", 8, 0x10),                    # next page wraps after the last page
    (0x4D9AA6, "rel"), (0x4D9AB2, "rel"),        # row draw callback 0x4D9A60

    # ---- 0x4DA230 junction menu setup
    (0x4DA2D9, "tramp", 11, "lea edx, [edi + 0x10 + {D}]; mov dword ptr [esp + 0x10], 0x40"),  # count spells per char
    (0x4DA3B0, "skip", "GF loop end"), (0x4DA47F, "skip", "GF loop end"),
    (0x4DA4F1, "rel"), (0x4DA513, "x", 0x20, 0x40),   # spell id -> slot index table 0x1D8B590
    # ---- commands field (char + 0x50), not magic
    (0x4DA56A, "skip", "commands"), (0x4DA611, "skip", "commands"), (0x4DA64A, "skip", "commands"),

    # ---- 0x4DA9B0 junction menu. Junctionable-slot mask [esi+0x2C] (32 bit) becomes the 64-bit
    #      JMASK: builders set bits in JMASK_B with bts, the store publishes JMASK_B -> JMASK.
    (0x4DB4FE, "rel"),
    (0x4DB534, "patch", 11, "bts dword ptr [{JMASK_B}], ebx"),
    (0x4DB540, "x", 0x20, 0x40),
    (0x4DB55A, "patch", 6, "call {jm_store_44}"),      # mov [esi+2C],ebp; mov [esi+44],al
    (0x4DE472, "rel"),
    (0x4DE4A8, "patch", 11, "bts dword ptr [{JMASK_B}], ebx"),
    (0x4DE4B4, "x", 0x20, 0x40),
    (0x4DE4B9, "patch", 7, "call {jm_store_bl18}"),    # mov bl,[esp+18]; mov [esi+2C],ebp
    (0x4DE751, "rel"),
    (0x4DE787, "patch", 11, "bts dword ptr [{JMASK_B}], ebp"),
    (0x4DE793, "x", 0x20, 0x40),
    (0x4DE7A2, "patch", 6, "call {jm_store_idiv}"),    # mov [esi+2C],ebx; cdq; idiv ecx
    (0x4DE999, "rel"),
    (0x4DE9C7, "patch", 11, "bts dword ptr [{JMASK_B}], ebp"),
    (0x4DE9D3, "x", 0x20, 0x40),
    (0x4DE9E2, "patch", 5, "call {jm_store_imul}"),    # mov [esi+2C],ebx; imul ecx
    # tests: shl r,cl ; test [esi+2C],r   -> ZF from JMASK bit cl
    (0x4DB71A, "patch", 5, "call {jm_test}"),
    (0x4DB747, "patch", 5, "call {jm_test}"),
    (0x4DED86, "patch", 5, "call {jm_test}"),
    (0x4DF087, "patch", 5, "call {jm_test}"),
    (0x4E24B3, "patch", 9, "call {jm_test}"),          # row callback: mov edx,1; shl edx,cl; test eax,edx
    (0x4DB6FD, "rel"), (0x4DED69, "rel"), (0x4DF06A, "rel"), (0x4DF322, "rel"),
    (0x4E2419, "rel"), (0x4E2423, "rel"),              # row draw callback 0x4E23F0
    # spell id -> slot index table 0x1D8B590
    (0x4DBD85, "rel"), (0x4DBDAE, "x", 0x20, 0x40),
    (0x4DBFFD, "rel"), (0x4DC024, "x", 0x20, 0x40),
    # junction spell list pages (4 rows/page, slot [esi+0x50]): 8 pages -> 16
    (0x4DED46, "x", 7, 0xF),
    (0x4DF045, "x", 8, 0x10),
    # Auto junction: 32-bit usable-slot mask [esp+14] / picker 0x4DFE90 -> 64-bit AJMASK
    (0x4DC464, "rel"),
    (0x4DC490, "patch", 21, "bts dword ptr [{AJMASK}], ebp"),
    (0x4DC4A6, "x", 0x20, 0x40),
    (0x4DC526, "patch", 7, "call {aj_done}; push -1"),   # clears AJMASK; xor ecx,ecx; mov cl,[esi+43]
    (0x4DFEB1, "patch", 17, "bt dword ptr [{AJMASK}], ebx; jnc 0x4DFF7A"),
    (0x4DFF82, "x", 0x20, 0x40),
    (0x4DFF9B, "patch", 11, "btr dword ptr [{AJMASK}], ecx"),
    # GF loops in the junction menu
    (0x4DDE1B, "skip", "GF loop end"), (0x4DE6D4, "skip", "GF loop end"),
    (0x4DF438, "skip", "GF loop end"), (0x4DFB20, "skip", "GF loop end"),

    (0x4E00F7, "skip", "GF loop end"), (0x4E0173, "skip", "GF loop end"), (0x4E03AA, "skip", "GF loop end"),
    (0x4E0BA7, "rel"),                               # junction screen: spell in selected slot
    # ---- 0x4F0030 magic Sort: tally by spell id, clear slots, rewrite in table order
    (0x4F0062, "x", 0x20, 0x40), (0x4F006D, "rel"), (0x4F0092, "x", 0x20, 0x40),

    # ---- 0x4F02F0 magic menu (use / exchange / sort): all slot loops 32 -> 64, exchange
    #      backups 0x1D8D810 / 0x1D8D850 (0x40 bytes each) -> MBAK1 / MBAK2 (0x80), 3 list page wraps
    (0x4F05BE, "rel"), (0x4F05C4, "rel"), (0x4F0613, "rel"), (0x4F061B, "rel"),
    (0x4F0697, "rel"), (0x4F06A5, "rel"), (0x4F08C4, "rel"), (0x4F08CA, "rel"),
    (0x4F0962, "rel"), (0x4F0970, "rel"), (0x4F09D0, "rel"), (0x4F09E4, "rel"),
    (0x4F09FD, "x", 0x20, 0x40), (0x4F0A16, "rel"), (0x4F0A2F, "x", 0x20, 0x40), (0x4F0B8D, "rel"),
    (0x4F0B93, "rel"), (0x4F0BF4, "rel"), (0x4F0C0E, "rel"), (0x4F0C76, "rel"),
    (0x4F0C7C, "x", 0x1D8D810, "{MBAK1}"), (0x4F0C83, "x", 0x40, 0x80), (0x4F0CC8, "rel"), (0x4F0CCE, "x", 0x1D8D850, "{MBAK2}"),
    (0x4F0CD5, "x", 0x40, 0x80), (0x4F0D69, "x", 0x1D8D810, "{MBAK1}"), (0x4F0D75, "rel"), (0x4F0D7D, "x", 0x40, 0x80),
    (0x4F0DCC, "x", 0x1D8D850, "{MBAK2}"), (0x4F0DD8, "rel"), (0x4F0DE0, "x", 0x40, 0x80), (0x4F0E40, "rel"),
    (0x4F0E4E, "rel"), (0x4F0FB4, "rel"), (0x4F0FCC, "rel"), (0x4F11BC, "rel"),
    (0x4F11C2, "x", 0x1D8D810, "{MBAK1}"), (0x4F11C9, "x", 0x40, 0x80), (0x4F120E, "rel"), (0x4F1214, "x", 0x1D8D850, "{MBAK2}"),
    (0x4F121B, "x", 0x40, 0x80), (0x4F1246, "rel"), (0x4F1257, "rel"), (0x4F1269, "x", 0x20, 0x40),
    (0x4F1291, "rel"), (0x4F12A7, "rel"), (0x4F12DA, "rel"), (0x4F12F7, "rel"),
    (0x4F1358, "x", 0x1D8D810, "{MBAK1}"), (0x4F1364, "rel"), (0x4F136C, "x", 0x40, 0x80), (0x4F13BB, "x", 0x1D8D850, "{MBAK2}"),
    (0x4F13C7, "rel"), (0x4F13CF, "x", 0x40, 0x80), (0x4F15E6, "x", 0x40, 0x80), (0x4F15F2, "rel"),
    (0x4F15F8, "x", 0x1D8D810, "{MBAK1}"), (0x4F1649, "x", 0x1D8D850, "{MBAK2}"), (0x4F1655, "rel"), (0x4F165D, "x", 0x40, 0x80),
    (0x4F16D0, "rel"), (0x4F16EE, "rel"), (0x4F170C, "rel"), (0x4F172A, "rel"),
    (0x4F179C, "rel"), (0x4F17A8, "rel"), (0x4F198E, "rel"), (0x4F199A, "rel"),
    (0x4F19FE, "rel"), (0x4F1A0C, "rel"), (0x4F1A54, "rel"), (0x4F1A60, "rel"),
    (0x4F1A88, "rel"), (0x4F1A9A, "rel"), (0x4F1AA6, "rel"), (0x4F1AC5, "rel"),
    (0x4F1ACB, "rel"), (0x4F1AE8, "rel"), (0x4F1B02, "rel"), (0x4F1B1C, "rel"),
    (0x4F1DB7, "rel"), (0x4F2A8E, "rel"), (0x4F2A94, "rel"), (0x4F2C20, "rel"),
    (0x4F2C26, "rel"), (0x4F2EE2, "rel"), (0x4F3020, "rel"), (0x4F3029, "rel"),
    (0x4F3044, "rel"), (0x4F304E, "rel"), (0x4F3069, "rel"), (0x4F37B1, "rel"),
    (0x4F37C6, "x", 0x20, 0x40), (0x4F37DE, "rel"), (0x4F3804, "x", 0x20, 0x40), (0x4F3831, "rel"),
    (0x4F384B, "x", 0x20, 0x40), (0x4F387B, "rel"), (0x4F3895, "x", 0x20, 0x40), (0x4F3A07, "rel"),
    (0x4F3A0D, "rel"), (0x4F3C26, "rel"), (0x4F3C2C, "rel"), (0x4F3F0F, "rel"),
    (0x4F3F20, "rel"), (0x4F3F32, "x", 0x20, 0x40), (0x4F3F5A, "rel"), (0x4F3F70, "rel"),
    (0x4F3FA3, "rel"), (0x4F3FBE, "rel"), (0x4F4039, "rel"), (0x4F403F, "x", 0x1D8D810, "{MBAK1}"),
    (0x4F4046, "x", 0x40, 0x80), (0x4F408B, "rel"), (0x4F4091, "x", 0x1D8D850, "{MBAK2}"), (0x4F4098, "x", 0x40, 0x80),
    (0x4F40C1, "rel"), (0x4F40D2, "rel"), (0x4F40E4, "x", 0x20, 0x40), (0x4F4128, "rel"),
    (0x4F4131, "rel"), (0x4F4149, "rel"), (0x4F4166, "rel"), (0x4F41F0, "rel"),
    (0x4F41F6, "x", 0x1D8D810, "{MBAK1}"), (0x4F41FD, "x", 0x40, 0x80), (0x4F4242, "rel"), (0x4F4248, "x", 0x1D8D850, "{MBAK2}"),
    (0x4F424F, "x", 0x40, 0x80), (0x4F42B9, "x", 0x1D8D810, "{MBAK1}"), (0x4F42C5, "rel"), (0x4F42CD, "x", 0x40, 0x80),
    (0x4F431C, "x", 0x1D8D850, "{MBAK2}"), (0x4F4328, "rel"), (0x4F4330, "x", 0x40, 0x80), (0x4F43BB, "rel"),
    (0x4F43D2, "x", 0x20, 0x40), (0x4F43ED, "x", 0x20, 0x40), (0x4F441B, "rel"), (0x4F4432, "x", 0x20, 0x40),
    (0x4F444D, "x", 0x20, 0x40), (0x4F4479, "rel"), (0x4F448E, "x", 0x20, 0x40), (0x4F44AA, "rel"),
    (0x4F44BF, "x", 0x20, 0x40), (0x4F4528, "rel"), (0x4F452E, "x", 0x1D8D810, "{MBAK1}"), (0x4F4535, "x", 0x40, 0x80),
    (0x4F457A, "rel"), (0x4F4580, "x", 0x1D8D850, "{MBAK2}"), (0x4F4587, "x", 0x40, 0x80), (0x4F4718, "x", 0x40, 0x80),
    (0x4F4724, "rel"), (0x4F472A, "x", 0x1D8D810, "{MBAK1}"), (0x4F477B, "x", 0x1D8D850, "{MBAK2}"), (0x4F4787, "rel"),
    (0x4F478F, "x", 0x40, 0x80), (0x4F4821, "rel"), (0x4F483F, "rel"), (0x4F485D, "rel"),
    (0x4F487B, "rel"), (0x4F4BB5, "rel"), (0x4F4BC1, "rel"), (0x4F4D4D, "rel"),
    (0x4F4D59, "rel"), (0x4F4EC8, "rel"), (0x4F4ED4, "rel"), (0x4F5126, "rel"),
    (0x4F5132, "rel"), (0x4F5181, "rel"), (0x4F518D, "rel"), (0x4F51A7, "rel"),
    (0x4F51B3, "rel"), (0x4F5254, "rel"), (0x4F5260, "rel"), (0x4F53FC, "rel"),
    (0x4F5408, "rel"), (0x4F5A12, "rel"), (0x4F5A7F, "rel"), (0x4F5A9A, "rel"),
    (0x4F5BA1, "rel"), (0x4F5BBC, "rel"), (0x4F39BD, "x", 7, 0xF), (0x4F3BDA, "x", 8, 0x10),
    (0x4F4D20, "x", 7, 0xF), (0x4F4E99, "x", 8, 0x10), (0x4F5227, "x", 7, 0xF), (0x4F53CD, "x", 8, 0x10),
    # ---- 0x495960 battle start: copy savemap magic into the battle table
    (0x49599A, "bdisp"),
    (0x4959A0, "tramp", 11, "lea eax, [ebp + 0x11 + {D}]; mov dword ptr [esp + 0x14], 0x40"),

    # ---- 0x4F5E30 exchange: can these two slots be swapped (quantities stay <= 100)
    (0x4F5E4B, "rel"), (0x4F5E65, "rel"), (0x4F5E7A, "rel"), (0x4F5E95, "x", 0x20, 0x40),
    (0x4F5EA4, "rel"), (0x4F5EC6, "x", 0x20, 0x40), (0x4F5F04, "x", 0x20, 0x40), (0x4F5F26, "x", 0x20, 0x40),
    (0x4F5F4A, "x", 0x20, 0x40), (0x4F5F6F, "x", 0x20, 0x40),

    # ---- 0x4F5FA0 exchange: move a character's whole magic list to another
    (0x4F5FBB, "x", 0x20, 0x40), (0x4F5FC3, "rel"),

    # ---- 0x4F6040 / 0x4F6140 exchange single spell; 0x4F6140 had a 32-bit 'all slots full' mask
    (0x4F6080, "rel"), (0x4F609D, "x", 0x20, 0x40), (0x4F60B5, "x", 0x20, 0x40), (0x4F60C7, "rel"),
    (0x4F60CD, "rel"), (0x4F60E8, "rel"), (0x4F60F6, "rel"), (0x4F61A2, "rel"),
    (0x4F61D3, "x", 0x20, 0x40), (0x4F61EA, "rel"), (0x4F61FE, "x", 0x20, 0x40), (0x4F6233, "x", 0x20, 0x40),
    (0x4F624A, "x", 0x20, 0x40), (0x4F6275, "x", 0x20, 0x40), (0x4F6296, "rel"), (0x4F62A4, "rel"),
    (0x4F62BF, "rel"), (0x4F62C5, "rel"),
    (0x4F61AD, "patch", 6, "call {fm_clear}"),                 # mov edx,eax; xor eax,eax; xor ecx,ecx
    (0x4F61C6, "patch", 9, "bts dword ptr [{FULLMASK}], ecx"),  # mov esi,1; shl esi,cl; or eax,esi
    (0x4F61D8, "tramp", 5, "call {fm_isfull}; jne 0x4F61EA"),   # cmp eax,-1; jne 4F61EA

    # ---- 0x4F6300 exchange: swap two slots between characters
    (0x4F6360, "rel"), (0x4F6366, "rel"), (0x4F6389, "rel"), (0x4F638F, "rel"),
    (0x4F6420, "rel"), (0x4F6438, "x", 0x20, 0x40), (0x4F6450, "rel"), (0x4F6460, "x", 0x20, 0x40),
    (0x4F646B, "rel"), (0x4F647C, "rel"), (0x4F6490, "x", 0x20, 0x40), (0x4F64B4, "rel"),
    (0x4F64D0, "x", 0x20, 0x40), (0x4F64F0, "x", 0x20, 0x40), (0x4F6501, "rel"), (0x4F6508, "rel"),
    (0x4F651E, "x", 0x20, 0x40), (0x4F654C, "rel"), (0x4F6552, "rel"), (0x4F6568, "rel"),
    (0x4F656E, "rel"),

    # ---- magic list row callbacks / small readers (magic menu use list, exchange lists)
    (0x4F6BF9, "rel"), (0x4F7182, "rel"), (0x4F7188, "rel"), (0x4F743F, "rel"), (0x4F7449, "rel"),

    # ---- 0x54E9B0 field / world-map draw point: find the spell's slot or the first empty one
    (0x54EC4F, "rel"), (0x54EC5D, "x", 0x20, 0x40), (0x54EC64, "rel"), (0x54EC73, "x", 0x20, 0x40),
    (0x54EC8C, "rel"), (0x54F1A7, "rel"), (0x54F1DA, "rel"), (0x54F1E1, "rel"),

    # ---- battle table users reached through the battle struct pointer (0x1CFF000 + k*0x1D0)
    (0x4837B1, "bdisp"), (0x4837C3, "x", 0x20, 0x40), (0x4837D2, "bdisp"),   # 0x483790 qty of spell
    (0x4837E0, "hook", "battle_rand_spell"),                                  # random held spell
    (0x483D6E, "x", 0x20, 0x40),                                              # 0x483D60 count loop
    (0x483D85, "hook", "battle_rand_spell40"),                                # selection -> rejoins 0x483DFA
    (0x48B3CD, "bdisp"), (0x48B3E0, "x", 0x20, 0x40),                         # 0x48B310 any spell left
    (0x48CB55, "bdisp"), (0x48CB6B, "x", 0x20, 0x40), (0x48CB7C, "x", 0x20, 0x40),
    (0x48CB92, "bdisp"),                                                       # 0x48CAE0 can draw more
    (0x4954B7, "x", 0x20, 0x40), (0x4954D0, "bdisp"),                         # 0x4954B0 per-entry flags
    # ---- 0x4CB4A0 swap two characters' junction setup (magic, commands, abilities, GFs, stats)
    (0x4CB4A0, "hook", "swap_junctions"),

    # ---- 0x4CAA3B / 0x4CADA7 back up / restore all character structs (menu cancel):
    #      also back up / restore the relocated magic
    (0x4CAA46, "patch", 7, "call {chars_backup}"),     # mov esi,0x1CFE0E8; rep movsd
    (0x4CADB2, "patch", 7, "call {chars_restore}"),    # mov edi,0x1CFE0E8; rep movsd

    # ---- main Magic menu page turn on [ebp+0x42] (byte-register forms, found in play-testing:
    #      the menu still stopped at 8 pages). Previous wraps to the last page, next after it.
    (0x4F2A56, "x", 7, 0xF),          # mov byte ptr [ebp+0x42], 7
    (0x4F2BE4, "x", 8, 0x10),         # cmp al, 8
]
