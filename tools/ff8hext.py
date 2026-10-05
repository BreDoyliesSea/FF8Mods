"""Shared helpers for building and checking the FF8 (Steam 2013, FF8_EN.exe) hext mods.

Hext syntax follows Junction VIII's AppWrapper/HexPatch.cs:
  line 1            title (ignored by the parser)
  # ...             comment
  ADDR = BB BB ...  write bytes at absolute address (hex, no 0x)
  ADDR:LEN          VirtualProtect(ADDR, LEN, PAGE_EXECUTE_READWRITE), no write
"""
import os
import struct

import keystone

EXE_SHA1 = "03230c11328f8a1f9635435096e1659d9bfd002d"  # Steam 2013 FF8_EN.exe
_ks = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_32)


def asm(src, addr):
    """Assemble `src` (intel syntax, ';' or newline separated) as if placed at `addr`."""
    enc, _ = _ks.asm(src, addr)
    return bytes(enc)


def hexbytes(b):
    return " ".join("%02X" % x for x in b)


class Hext:
    def __init__(self, title):
        self.title = title
        self.lines = []
        self.writes = []

    def comment(self, text=""):
        for ln in text.splitlines() or [""]:
            self.lines.append(("# " + ln).rstrip())

    def blank(self):
        self.lines.append("")

    def write(self, addr, data, note=None):
        if note:
            self.comment(note)
        self.writes.append((addr, len(data)))
        # keep lines reasonably short
        for off in range(0, len(data), 16):
            self.lines.append("%08X=%s" % (addr + off, hexbytes(data[off:off + 16])))

    def protect(self, addr, length, note=None):
        if note:
            self.comment(note)
        self.lines.append("%08X:%X" % (addr, length))

    def text(self):
        # HexPatch.cs leaves a page PAGE_READWRITE when it was already RWX before a
        # write, so finish by marking every written range executable again.
        tail = []
        if self.writes:
            tail = ["", "# re-mark written ranges as executable (see ff8hext.py)"]
            tail += ["%08X:%X" % (a, n) for a, n in self.writes]
        return "\n".join([self.title] + self.lines + tail) + "\n"

    def save(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", newline="\r\n") as f:
            f.write(self.text())


def parse_hext(text):
    """Return list of ('w', addr, bytes) / ('p', addr, len), mirroring HexPatch.cs."""
    out = []
    in_ml = False
    offset = 0
    for line in text.splitlines()[1:]:
        t = line.strip()
        if not t:
            continue
        if in_ml:
            if t.endswith("}}"):
                in_ml = False
            continue
        if t.startswith("{{"):
            in_ml = True
            continue
        if t.startswith("#") or t.startswith("{"):
            continue
        if t.startswith("+"):
            offset = int(t[1:], 16)
        elif t.startswith("-"):
            offset = -int(t[1:], 16)
        elif "=" in t and "delay" not in t.lower():
            a, b = t.split("=", 1)
            addr = int(a.strip(), 16) + offset
            if ":" in b:
                v, n = b.split(":")
                data = bytes([int(v, 16)]) * int(n, 16)
            else:
                data = bytes(int(x, 16) for x in b.replace(",", " ").split())
            out.append(("w", addr, data))
        elif ":" in t:
            a, n = t.split(":")
            out.append(("p", int(a, 16) + offset, int(n, 16)))
    return out


class Image:
    """Flat memory image of FF8_EN.exe as mapped by the Windows loader."""

    BASE = 0x400000

    def __init__(self, exe_path):
        import hashlib
        import pefile
        raw = open(exe_path, "rb").read()
        sha = hashlib.sha1(raw).hexdigest()
        if sha != EXE_SHA1:
            raise SystemExit("Unexpected FF8_EN.exe (sha1 %s); these patches target the Steam 2013 English EXE" % sha)
        pe = pefile.PE(data=raw, fast_load=True)
        size = max(s.VirtualAddress + max(s.Misc_VirtualSize, s.SizeOfRawData) for s in pe.sections)
        img = bytearray(size)
        img[0:0x1000] = raw[0:0x1000]
        for s in pe.sections:
            img[s.VirtualAddress:s.VirtualAddress + s.SizeOfRawData] = raw[s.PointerToRawData:s.PointerToRawData + s.SizeOfRawData]
        self.mem = img

    def read(self, addr, n):
        return bytes(self.mem[addr - self.BASE:addr - self.BASE + n])

    def u32(self, addr):
        return struct.unpack("<I", self.read(addr, 4))[0]

    def apply(self, ops):
        for op in ops:
            if op[0] == "w":
                _, addr, data = op
                self.mem[addr - self.BASE:addr - self.BASE + len(data)] = data


def default_exe():
    env = os.environ.get("FF8_EXE")
    if env:
        return env
    return os.path.expanduser("~/.local/share/Steam/steamapps/common/FINAL FANTASY VIII/FF8_EN.exe")
