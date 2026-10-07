# FF8 Unlimited

A gameplay mod for **Final Fantasy VIII (2013 Steam release, English)**, packaged for
[Junction VIII](https://github.com/tsunamods-codes/Junction-VIII), the mod manager for the
original PC version (not the Remastered edition). It has three parts, each an option in
Junction VIII's **Configure** screen:

| Part | Option | Folder |
|---|---|---|
| All Magic Per Character | All Magic Per Character: On / Off | `FF8Unlimited/options/AllMagic` |
| Unlimited GF Abilities | Unlimited GF Abilities: On / Off | `FF8Unlimited/options/GFAbilities` |
| Triple Triad rule select | Card rule: Open ... Elemental, Card rule: Trade | `FF8Unlimited/options/CardRules` |

A fourth folder, `options/PageNumbers`, draws two-digit page numbers ("P.12"). It loads when
the magic or GF part is on. A part that is off loads nothing: the card-rule hook only loads
when at least one rule or the trade rule is changed from "Region default". The parts patch
different bytes, so any combination is safe (`tools/verify_mod.py` checks this).

Releases are on [FF8Mods-releases](https://github.com/BreDoyliesSea/FF8Mods-releases). Version
1.0 shipped the three parts as separate mods; 1.1 combines them.

All patches are Junction VIII "hext" memory patches. They target exactly this executable:

```
FF8_EN.exe  sha1 03230c11328f8a1f9635435096e1659d9bfd002d   (Steam 2013, English)
```

Junction VIII's "4GB" (large-address-aware) copy of that EXE has the same code addresses,
so the patches work with it too. Other languages and the 2000 CD release use different
addresses and are **not** supported.

## Compatibility with other mods

`tools/compat_check.py` compares another mod's hext against FF8 Unlimited. Last run on
**Cronos 0.7** and **FF8 Gameplay Customizer 0.5**:

- Everything else in both mods, including NoMagicDepletion and the Draw options, patches
  different bytes from ours and works alongside FF8 Unlimited.
- Their **Junction value rework** option patches three instructions in the junction-stat code
  that the All Magic part also patches (`0x4963CB`, `0x4966E5`, `0x496788`). Their patch has to
  win, so FF8 Unlimited must sit **below** them in Junction VIII's mod list; `mod.xml` declares
  this (`OrderConstraints`) and Junction VIII warns if the order is wrong.
- Its **JunctionDependOfMinLevelQuantity** setting also reads spell quantities from the old
  32-slot location, which the All Magic part no longer keeps current, so `mod.xml` forbids that
  setting while All Magic is on (`Compatibility`). Cronos uses it by default.

## Installing

1. Install and set up Junction VIII for your Steam copy of FF8.
2. Install **FF8 Unlimited** from **Browse Catalog**, or choose **Import Mod**, then
   **From Folder**, and select the `FF8Unlimited` folder.
3. Activate it, open **Configure** to pick your options, then press **Play**.

If something seems off, use **Play With Debug Log**. Then look for
`Loading hext patches` / `Applying hext patch` lines in `log.txt` in the game folder.

## Memory used

For other mod authors checking compatibility. Each part only writes these while it is on.

| Part | Code | Data / patched code |
|---|---|---|
| All Magic | cave `0x24B6000-0x24B6572` (unused `.data`, made executable) | `0x24B5000-0x24B5B28`, `0x25D5000-0x25D7980` (unused `.data`); about 440 sites in `.text` that read or write magic |
| GF Abilities | cave `0xB68940-0xB68C0E` (padding at the end of `.text`) | `0x400400-0x400860` (PE header tail); 46 sites |
| Card rules | cave `0xB68E00-0xB68E3D` (padding at the end of `.text`) | hook at `0x522652` |
| Page numbers | none | rewrites `0x4C0370-0x4C03D7` in place |

## Card rules (Triple Triad)

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
  as 128 bits per GF. If you later turn this part off, a GF with more than 22 abilities
  keeps them all, but vanilla menus only list the first 22.
- Page numbers past 9 ("P.12") come from the page-number fix described below.

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
pre-mod saves still load** and their magic is migrated. A save made with this part on needs
it on to load its magic correctly, and other tools (e.g. Hyne) won't understand the extra magic.
One cosmetic note: magic slot order is re-sorted by spell across a save/load.

Full details are in `tools/build_magic.py` and the reviewed site list in `tools/magic_sites.py`.

## Page numbers

The menus' "P.n" page header (`0x4C0370`) formats the page number into digit sprites but
only draws the units digit, so page 12 showed "P.2". The game has a two-digit version
(`0x4C02F0`, same arguments). The fix rewrites `0x4C0370` in place: pages 10 and up go to the
two-digit version, and pages 1-9 draw exactly as before. See `tools/build_page_numbers.py`.

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
its magic needs the All Magic option on.

If anything misbehaves, please send `log.txt` (from **Play With Debug Log**) and a short
description.

## Rebuilding / verifying

The hext files and `FF8Unlimited/mod.xml` are generated. To change a part, edit its builder,
not the output.

```bash
python -m venv .venv && .venv/bin/pip install -r tools/requirements.txt
.venv/bin/python tools/build_mod.py
.venv/bin/python tools/verify_mod.py
.venv/bin/python tools/verify_magic.py
.venv/bin/python tools/verify_gf_abilities.py
.venv/bin/python tools/verify_tt_rules.py
.venv/bin/python tools/package_catalog.py
```

`build_mod.py` runs every part's builder (`build_magic.py`, `build_gf_abilities.py`,
`build_tt_rules.py`, `build_page_numbers.py`) and writes `mod.xml`. Each builder reads your
`FF8_EN.exe`, checks the original bytes at every patch site, and refuses to build if anything
differs (`build_magic.py` also refuses if any memory region it claims is not empty in your EXE).
`package_catalog.py` writes the release `.iroj` (Junction VIII's archive format; the catalog cannot
install a plain zip) to `dist/` and the catalog entry to `catalog/`.

The verifiers load your real `FF8_EN.exe`, apply the hext files exactly as Junction VIII's
`HexPatch.cs` would, and run the patched code in the Unicorn CPU emulator. `verify_magic.py`
exercises the rewritten add-magic / can-receive / battle-table / junction-swap routines and the
save pack/unpack (including migrating a pre-mod save). `verify_mod.py` checks the mod.xml
folders, that no two parts write the same bytes, and the page numbers. They look for the EXE in
the default Steam library path; set `FF8_EXE=/path/to/FF8_EN.exe` to point them somewhere else.

`tools/re/` holds the reverse-engineering helpers used to find the magic sites (static
reference scans, function dumps, reachability), kept for reference.
