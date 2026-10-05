#!/usr/bin/env python3
"""Package the mod for a GitHub release and write their Junction VIII catalog entries.

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
        "folder": "FF8Unlimited",
        "tags": ["magic", "gf", "guardian force", "abilities", "triple triad", "cards", "rules",
                 "junction", "gameplay", "hext"],
        "description": """
Lifts FF8's list limits and lets you pick the Triple Triad rules. Each part is an option in Configure and can be switched off on its own.

    &#9670; All Magic Per Character &#9670;
        &#8226; Every character holds every spell at once (64 slots instead of 32), up to 100 each.
        &#8226; Every magic screen pages through them: magic menu, draw, refine, junction and auto-junction, item and exchange screens.
        &#8226; The extra magic is kept in your normal save; older saves are converted when loaded. Saves made with it need it on to load their magic.

    &#9670; Unlimited GF Abilities &#9670;
        &#8226; No 22-ability limit per GF: teach any number of abilities with items, no Amnesia Greens needed.
        &#8226; The GF menu Learn list, the item teach/forget list and the junction GF ability popup page through all of them.
        &#8226; Saves stay in the vanilla format.

    &#9670; Card rules &#9670;
        &#8226; Open, Same, Plus, Random, Sudden Death, Same Wall, Elemental: Region default, Always on or Always off.
        &#8226; Trade rule: Region default, One, Diff, Direct, All or None. Applies to every match in every region.

Page numbers past 9 show both digits (P.12).

Requires the Steam 2013 English release (FF8_EN.exe). Not for the Remastered edition, other languages or the 2000 release.

Dev note - memory this mod uses (only while that part is on):
    &#8226; All Magic: code cave 0x24B6000-0x24B6572 and data 0x24B5000-0x24B5B28, 0x25D5000-0x25D7980 (unused .data); about 440 patched sites.
    &#8226; GF Abilities: code cave 0xB68940-0xB68C0E (end of .text) and data 0x400400-0x400860 (PE header tail).
    &#8226; Card rules: code cave 0xB68E00-0xB68E3D (end of .text); hook at 0x522652.
    &#8226; Page numbers: rewrites 0x4C0370-0x4C03D7 in place.
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
