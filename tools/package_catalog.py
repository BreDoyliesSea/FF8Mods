#!/usr/bin/env python3
"""Package the three mods for a GitHub release and write their Junction VIII catalog entries.

Writes:
  dist/<Folder>-<version>.zip     mod.xml + hext/ (+ options/) at the zip root, which Junction VIII
                                  extracts straight into its library (AppCore/Install.cs)
  catalog/<Folder>/mod.xml        entry for tsunamods-codes/Junction-VIII-Catalogs (mods/<Folder>/)

Run the builders first; this only packages what is in the mod folders.
"""
import math
import os
import re
import zipfile
from xml.sax.saxutils import escape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RELEASES = "https://github.com/BreDoyliesSea/FF8Mods-releases"
AUTHOR = "BreDoyliesSea"
COMPAT = "Steam"  # Steam 2013 English FF8_EN.exe only

MODS = [
    {
        "folder": "TripleTriadRuleSelect",
        "tags": ["triple triad", "cards", "rules", "minigame", "hext"],
        "description": """
Pick the Triple Triad rules yourself, in Junction VIII's mod configuration.

    &#8226; Open, Same, Plus, Random, Sudden Death, Same Wall, Elemental: each one Region default, Always on or Always off.
    &#8226; Trade rule: Region default, One, Diff, Direct, All, or None (no cards change hands).
    &#8226; Applies to every card game in every region. "Region default" keeps the game's own rule spreading and abolishing.

Requires the Steam 2013 English release (FF8_EN.exe). Not for the Remastered edition, other languages or the 2000 release.
  """,
    },
    {
        "folder": "UnlimitedGFAbilities",
        "tags": ["gf", "guardian force", "abilities", "menu", "gameplay", "hext"],
        "description": """
Removes the 22-ability limit per GF.

    &#8226; Teach a GF any number of abilities with items, without forgetting old ones with Amnesia Greens first.
    &#8226; The GF menu Learn list, the item teach/forget list and the junction menu's GF ability popup get as many pages as they need (Left/Right).
    &#8226; Saves stay in the vanilla format.

Requires the Steam 2013 English release (FF8_EN.exe). Not for the Remastered edition, other languages or the 2000 release.
  """,
    },
    {
        "folder": "AllMagicPerCharacter",
        "tags": ["magic", "spells", "junction", "draw", "gameplay", "hext"],
        "description": """
Each character can hold every spell in the game at once, up to 100 each.

    &#8226; Magic storage goes from 32 slots to 64 per character.
    &#8226; Every magic list pages through all of them: magic menu, draw, refine, junction and auto-junction, item and exchange screens.
    &#8226; Draw, cast, junction bonuses, party swaps and battle use all 64 slots.
    &#8226; The extra magic is kept inside your normal save, and existing saves are converted when loaded. A save made with the mod needs the mod to load its magic correctly.

Requires the Steam 2013 English release (FF8_EN.exe). Not for the Remastered edition, other languages or the 2000 release.
  """,
    },
]


def tag(xml, name):
    m = re.search(r"<%s>(.*?)</%s>" % (name, name), xml, re.S)
    if not m:
        raise SystemExit("mod.xml has no <%s>" % name)
    return m.group(1).strip()


def package(folder):
    src = os.path.join(ROOT, folder)
    xml = open(os.path.join(src, "mod.xml"), encoding="utf-8").read()
    version = tag(xml, "Version")
    os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
    out = os.path.join(ROOT, "dist", "%s-%s.zip" % (folder, version))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, dirnames, filenames in os.walk(src):
            dirnames.sort()
            for f in sorted(filenames):
                full = os.path.join(dirpath, f)
                z.write(full, os.path.relpath(full, src).replace(os.sep, "/"))
    return xml, version, out


def entry(mod, xml, version, zip_path):
    name = os.path.basename(zip_path)
    link = "iroj://Url/%s/releases/download/v%s/%s" % (RELEASES.replace("://", "$"), version, name)
    size_kib = max(1, math.ceil(os.path.getsize(zip_path) / 1024))  # JV8 reads DownloadSize as KiB
    tags = "\n".join("    <string>%s</string>" % escape(t) for t in mod["tags"])
    return """<?xml version="1.0"?>
<Mod>
  <ID>{id}</ID>
  <Name>{name}</Name>
  <Author>{author}</Author>
  <Category>{category}</Category>
  <Description>{description}</Description>
  <LatestVersion>
    <Link>{link}</Link>
    <Version>{version}</Version>
    <ReleaseDate>{date}</ReleaseDate>
    <CompatibleGameVersions>{compat}</CompatibleGameVersions>
    <PreviewImage />
    <ReleaseNotes>
Version {version}:
  &#8226; {notes}
    </ReleaseNotes>
    <DownloadSize>{size}</DownloadSize>
  </LatestVersion>
  <Link>{releases}</Link>
  <DonationLink />
  <Tags>
{tags}
  </Tags>
  <GameLanguage>{lang}</GameLanguage>
</Mod>
""".format(id=tag(xml, "ID"), name=tag(xml, "Name"), author=AUTHOR, category=tag(xml, "Category"),
           description=mod["description"], link=link, version=version, date=tag(xml, "ReleaseDate"),
           compat=COMPAT, notes=tag(xml, "ReleaseNotes"), size=size_kib, releases=RELEASES, tags=tags,
           lang=tag(xml, "GameLanguage"))


def main():
    for mod in MODS:
        xml, version, zip_path = package(mod["folder"])
        out_dir = os.path.join(ROOT, "catalog", mod["folder"])
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "mod.xml"), "w", encoding="utf-8", newline="\n") as f:
            f.write(entry(mod, xml, version, zip_path))
        print("packaged %s (%d bytes), catalog/%s/mod.xml" % (os.path.relpath(zip_path, ROOT),
                                                              os.path.getsize(zip_path), mod["folder"]))


if __name__ == "__main__":
    main()
