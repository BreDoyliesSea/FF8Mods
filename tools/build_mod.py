#!/usr/bin/env python3
"""Build the combined "FF8 Unlimited" Junction VIII mod: every part's hext plus mod.xml.

    FF8Unlimited/
      mod.xml
      options/AllMagic/      All Magic Per Character      (tools/build_magic.py)
      options/GFAbilities/   Unlimited GF Abilities        (tools/build_gf_abilities.py)
      options/PageNumbers/   two-digit "P.12" page header  (tools/build_page_numbers.py)
      options/CardRules/     Triple Triad rule select      (tools/build_tt_rules.py)

Each part only loads when its option is on, so a part that is switched off puts nothing in
the game. The card-rule hook loads only when at least one rule or the trade rule is changed
from "Region default", and the page-number fix loads when the magic or GF part is on.
"""
import os
import shutil
import sys
from xml.sax.saxutils import escape as e

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_gf_abilities  # noqa: E402
import build_magic  # noqa: E402
import build_page_numbers  # noqa: E402
import build_tt_rules  # noqa: E402

MOD = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "FF8Unlimited"))
ID = "6ed51118-e60c-4087-8626-e9e9b6acd886"
NAME = "FF8 Unlimited"
VERSION = "1.3"
RELEASE_DATE = "2026-10-07"
RELEASE_NOTES = ("1.3: released as a Junction VIII .iroj archive, so installing from the "
                 "catalog works. 1.2: works alongside Cronos and FF8 Gameplay Customizer: load order and their "
                 "Junction value rework option are checked by Junction VIII. "
                 "1.1: combines Triple Triad Rule Select, Unlimited GF Abilities and All Magic Per "
                 "Character into one mod with options. Page numbers past 9 show two digits.")
LINK = "https://github.com/BreDoyliesSea/FF8Mods-releases"

DESCRIPTION = (
    "Lifts FF8's list limits and lets you pick the Triple Triad rules. Each part is an option "
    "and can be switched off. All Magic: every character holds every spell at once (64 slots "
    "instead of 32), up to 100 each, and every magic screen pages through them. Unlimited GF "
    "Abilities: no 22-ability limit per GF; teach any number with items. Card rules: force each "
    "Triple Triad rule and the trade rule on or off in every region. Requires the Steam 2013 "
    "English FF8_EN.exe.")

ON_OFF = [
    ("AllMagic", "All Magic Per Character",
     "Every character can hold all spells, up to 100 each. The extra magic is stored in your "
     "save. Keep this on for saves made with it, or their magic will not load correctly."),
    ("GFAbilities", "Unlimited GF Abilities",
     "No 22-ability limit per GF. GF ability lists get as many pages as they need."),
]


# Other catalog mods that patch the same code (checked with tools/compat_check.py).
# Their "Junction value rework" options replace three instructions that the All Magic part also
# patches (0x4963CB, 0x4966E5, 0x496788); whichever loads last wins, and only their whole
# instruction is safe, so FF8 Unlimited must load first: below them in the list (JV8 applies
# hext bottom to top). Their JunctionDependOfMinLevelQuantity (value 2) also reads spell
# quantities from the old 32-slot location, which the All Magic part no longer keeps current,
# so that value is forbidden while All Magic is on.
OTHER_MODS = [
    ("260dd8f3-537a-4d34-b3d5-956cda71eac9", "Cronos"),
    ("260dd8f3-537a-4d34-b3d5-956cda71eaca", "FF8 Gameplay Customizer"),
]


def compatibility():
    o = ["  <OrderConstraints>"]
    o += ["    <After>%s</After>" % mid for mid, _ in OTHER_MODS]
    o += ["  </OrderConstraints>", "  <Compatibility>"]
    for mid, name in OTHER_MODS:
        o += ["    <Setting>", "      <MyID>AllMagic</MyID>", "      <MyValue>1</MyValue>",
              "      <ModID>%s</ModID>" % mid, "      <TheirID>JunctionRework</TheirID>",
              "      <Forbid>2</Forbid>", "    </Setting>"]
    o += ["  </Compatibility>"]
    return o


def config_options():
    o = []
    for oid, name, desc in ON_OFF:
        o += ["  <ConfigOption>", "    <Name>%s</Name>" % e(name), "    <ID>%s</ID>" % oid,
              "    <Type>List</Type>", "    <Default>1</Default>",
              "    <Description>%s</Description>" % e(desc),
              '    <Option Value="1" Name="On" />', '    <Option Value="0" Name="Off" />',
              "  </ConfigOption>"]
    for rid, name, _, desc in build_tt_rules.RULE_LIST:
        o += ["  <ConfigOption>", "    <Name>Card rule: %s</Name>" % e(name), "    <ID>Rule%s</ID>" % rid,
              "    <Type>List</Type>", "    <Default>0</Default>",
              "    <Description>%s</Description>" % e(desc),
              '    <Option Value="0" Name="Region default" />', '    <Option Value="1" Name="Always on" />',
              '    <Option Value="2" Name="Always off" />', "  </ConfigOption>"]
    o += ["  <ConfigOption>", "    <Name>Card rule: Trade</Name>", "    <ID>TradeRule</ID>",
          "    <Type>List</Type>", "    <Default>0</Default>",
          "    <Description>Which cards change hands after a match.</Description>",
          '    <Option Value="0" Name="Region default" />']
    o += ['    <Option Value="%d" Name="%s" />' % (val, e(name)) for val, name, _, _ in build_tt_rules.TRADE_LIST]
    o += ["  </ConfigOption>"]
    return o


def folder(path, condition_xml):
    return ['  <ModFolder Folder="%s">' % path.replace("/", "\\"), "    <ActiveWhen>",
            *("      " + c for c in condition_xml), "    </ActiveWhen>", "  </ModFolder>"]


def opt(cond):
    return "<Option>%s</Option>" % cond


def write_modxml(tt_folders):
    rule_ids = ["Rule%s" % rid for rid, _, _, _ in build_tt_rules.RULE_LIST] + ["TradeRule"]
    o = ['<?xml version="1.0" encoding="utf-8"?>', "<ModInfo>",
         "  <ID>%s</ID>" % ID, "  <Name>%s</Name>" % e(NAME), "  <Author>BreDoyliesSea</Author>",
         "  <Version>%s</Version>" % VERSION, "  <Description>%s</Description>" % e(DESCRIPTION),
         "  <ReleaseNotes>%s</ReleaseNotes>" % e(RELEASE_NOTES), "  <ReleaseDate>%s</ReleaseDate>" % RELEASE_DATE,
         "  <Category>Gameplay</Category>", "  <Link>%s</Link>" % LINK, "  <DonationLink />",
         "  <GameLanguage>EN</GameLanguage>", ""]
    # No Bool options: Junction VIII 1.4.1's Configure window throws on a Bool option without
    # <Option> children, so every option is a List with explicit choices and a default.
    o += config_options() + [""] + compatibility() + [""]
    o += folder("options/AllMagic", [opt("AllMagic=1")])
    o += folder("options/GFAbilities", [opt("GFAbilities=1")])
    o += folder("options/PageNumbers", ["<Or>", "  " + opt("AllMagic=1"), "  " + opt("GFAbilities=1"), "</Or>"])
    o += folder("options/CardRules", ["<Or>"] + ["  <Not>%s</Not>" % opt("%s=0" % r) for r in rule_ids] + ["</Or>"])
    for path, cond in tt_folders:
        o += folder("options/CardRules/" + path, [opt(cond)])
    o += ["</ModInfo>"]
    with open(os.path.join(MOD, "mod.xml"), "w", newline="\r\n") as f:
        f.write("\n".join(o) + "\n")


def main():
    exe = sys.argv[1] if len(sys.argv) > 1 else None
    if os.path.isdir(MOD):
        shutil.rmtree(MOD)          # generated output only
    build_magic.build(exe)
    build_gf_abilities.build(exe)
    build_page_numbers.build(exe)
    tt_folders = build_tt_rules.build()
    write_modxml(tt_folders)
    n = sum(len(fs) for _, _, fs in os.walk(MOD))
    print("built %s (%d files)" % (MOD, n))


if __name__ == "__main__":
    main()
