# FF8Mods

Gameplay mods for **Final Fantasy VIII (2013 Steam release, English)**, packaged for
[Junction VIII](https://github.com/tsunamods-codes/Junction-VIII), the mod manager for the
original PC version (not the Remastered edition).

| Mod | Folder | Status |
|---|---|---|
| Triple Triad Rule Select | `TripleTriadRuleSelect/` | Done. Logic checked by emulation; not yet play-tested |
| Unlimited GF Abilities | `UnlimitedGFAbilities/` | Done. Logic checked by emulation; not yet play-tested |
| All Magic Per Character | `AllMagicPerCharacter/` | Done. Logic checked by emulation; not yet play-tested |

All three mods can be active at the same time; they patch different addresses.

All patches are Junction VIII "hext" memory patches. They target exactly this executable:

```
FF8_EN.exe  sha1 03230c11328f8a1f9635435096e1659d9bfd002d   (Steam 2013, English)
```

Junction VIII's "4GB" (large-address-aware) copy of that EXE has the same code addresses,
so the patches work with it too. Other languages and the 2000 CD release use different
addresses and are **not** supported.

## Installing a mod

1. Install and set up Junction VIII for your Steam copy of FF8.
2. In Junction VIII choose **Import Mod**, then **From Folder**, and select the mod's
   folder (for example `TripleTriadRuleSelect`).
3. Activate the mod. Open its configuration to pick your settings, then press **Play**.

If something seems off, use **Play With Debug Log**. Then look for
`Loading hext patches` / `Applying hext patch` lines in `log.txt` in the game folder.

## Triple Triad Rule Select

Choose, in Junction VIII's configuration screen, how each card rule behaves in **every**
match in every region:

| Setting | Choices |
|---|---|
| Open, Same, Plus, Random, Sudden Death, Same Wall, Elemental | Region default / Always on / Always off |
| Trade rule | Region default / One / Diff / Direct / All / None (no cards change hands) |

"Region default" leaves that rule exactly as the game decides it, including rule
spreading and abolishing. Same Wall only has an effect while Same is also on.

How it works: field scripts start a match through the `CARDGAME` opcode, which pops the
rule flags into `0x1DCD7A8` and the trade rule into `0x1DCD7AC`. The mod redirects the
next call (at `0x522652`) through a small routine in unused padding at the end of
`.text`. That routine adjusts both values, then jumps on to the original function.
The rule bits are 01 Open, 02 Same, 04 Plus, 08 Random, 10 Sudden Death, 40 Same Wall
and 80 Elemental. Details are in `tools/build_tt_rules.py`.

## Unlimited GF Abilities

Removes the 22-ability limit per GF. A GF can now be taught any number of abilities with
items, without forgetting older ones with Amnesia Greens first. All of its abilities
remain listed and usable.

Each screen that shows a GF's abilities now has as many pages as it needs:

| Screen | How to page |
|---|---|
| GF menu, Learn list | Left / Right, as before. Past page 2 the page number keeps counting, with arrows on both sides |
| Item menu, teaching or forgetting a GF ability | Left / Right, the same way |
| Junction menu, GF ability popup (two columns of 11) | Left / Right show the next / previous 22 abilities. This popup never had a page indicator, so none is shown |

When you open the GF Learn list, it jumps to the page containing the ability the GF
is currently learning.

Notes:
- Your save files keep the vanilla format, since learned abilities were always stored
  as 128 bits per GF. If you later turn the mod off, a GF with more than 22 abilities
  keeps them all, but vanilla menus only list the first 22.
- The game's page header ("P.n") draws a single digit, so from page 10 it showed only the
  last digit. From page 10 it now uses the game's own two-digit header instead. The All Magic
  mod includes the same fix, so either mod alone or both together show "P.12".

How it works: every ability list comes from one function (`0x4ACB70`), which stopped at
22 entries. Teaching an item ability (`0x4FC6C0`) refused once a GF had 22. Both limits
are raised to 127. Callers that keep the list on the stack get their stack frames
enlarged. The three menus keep their original 22-entry buffers, which now act as a
two-page window onto a full list stored in unused space after the EXE's header
(`0x400400`). Pressing past the last page slides the window by one page. The full
details are in `tools/build_gf_abilities.py`.

## All Magic Per Character

Raises each character's magic storage from the vanilla **32 slots to 64**, so a character can
hold **every spell in the game at once (about 56 of them), up to 100 each**. Every screen that
lists magic — the magic menu (use / arrange / sort), draw, refine, the junction magic list and
its auto-junction, and the item/exchange flows — pages through the full list, and all of draw,
cast, junction stat bonuses, party swaps and battle use the full 64 slots.

How it works: each character's 32 magic slots lived inside the savemap at
`savemap + 0x490 + 0x98*char + 0x10` (64 bytes), with no room to grow in place. The magic moves
to a parallel array `NEWMAG = 0x24B5000` (same `0x98` stride, 64 slots), and the in-battle magic
table moves to `BMAG = 0x25D5000`. About 440 code sites that read either array are relocated or
rewritten, including hand-written replacements for add-magic, can-receive, the battle table
copy-back, the battle random-spell pickers, junction swap, and the 64-bit junction /
auto-junction / exchange slot masks. All of this lives in a code cave and two otherwise-unused
`.data` regions (verified empty).

Saves: the extra magic is persisted inside your normal save (no extra files). At save, each
character's 64 slots are packed into a dense per-spell table that fits the now-unused vanilla
32-slot region; at load it is unpacked. A signature byte marks mod saves, so **existing
pre-mod saves still load** and their magic is migrated. A save made with the mod active needs
the mod active to load correctly, and other tools (e.g. Hyne) won't understand the extra magic.
One cosmetic note: magic slot order is re-sorted by spell across a save/load.

Page numbers past 9 ("P.12") use the game's own two-digit page header.

Full details are in `tools/build_magic.py` and the reviewed site list in `tools/magic_sites.py`.

## Testing checklist (in game)

The emulation tests cover the game logic, but not what you see on screen. Please check:

1. **Triple Triad:** set a couple of rules to *Always on* / *Always off*, challenge
   someone, and check the rules listed at the start of the match. Then try a forced trade
   rule.
2. **GF abilities:** pick a GF with a full 22-ability list. Teach it an ability with an
   item (for example a Rosetta Stone, which teaches Ability×4). It should accept the item and
   show a third page in the GF menu. Page left and right through all pages, and select an
   ability to learn on page 3. Re-open the menu and it should land on that page.
3. **Junction:** open the same GF's ability popup in the junction menu and press
   Left/Right.
4. **Battle:** win a battle so the GF finishes learning something, and make sure the next
   ability it picks to learn makes sense.
5. **All Magic Per Character:** draw or refine more than 32 *different* spells onto one
   character and confirm they all stock (past the old 8-page / 32-spell limit), each up to 100.
   Page through the whole magic list, junction a spell from a high slot, then **save, reload,
   and confirm every spell and quantity survived**. Load an older (pre-mod) save and check its
   existing magic is intact. Fight a battle, draw/cast, and confirm the counts carry back out.

To set up items 2-5 quickly, `tools/make_test_save.py` turns an existing Steam save into a
test save in another slot. It gives you Quezacotl (exactly 22 abilities) and Shiva (34 entries,
learning one on page 4), puts 50 spells x100 on Squall, and adds ability-teaching items. Loading
its magic needs the All Magic mod active.

If anything misbehaves, please send `log.txt` (from **Play With Debug Log**) and a short
description.

## Rebuilding / verifying

The hext files are generated. To change a mod, edit the builder, not the output.

```bash
python -m venv .venv && .venv/bin/pip install -r tools/requirements.txt
.venv/bin/python tools/build_tt_rules.py
.venv/bin/python tools/verify_tt_rules.py
.venv/bin/python tools/build_gf_abilities.py
.venv/bin/python tools/verify_gf_abilities.py
.venv/bin/python tools/build_magic.py
.venv/bin/python tools/verify_magic.py
```

Each builder reads your `FF8_EN.exe`, checks the original bytes at every patch site, and
refuses to build if anything differs (`build_magic.py` also refuses if any memory region it
claims is not empty in your EXE).

The verifiers load your real `FF8_EN.exe`, apply the hext files exactly as Junction VIII's
`HexPatch.cs` would, and run the patched code in the Unicorn CPU emulator. `verify_magic.py`
exercises the rewritten add-magic / can-receive / battle-table / junction-swap routines and the
save pack/unpack (including migrating a pre-mod save). They look for the EXE in the default
Steam library path; set `FF8_EXE=/path/to/FF8_EN.exe` to point them somewhere else.
