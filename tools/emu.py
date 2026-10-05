"""Small Unicorn harness for running FF8_EN.exe functions against a patched image."""
import struct

import unicorn as uc
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX,
                               UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP, UC_X86_REG_ESP,
                               UC_X86_REG_EIP)

REGS = dict(eax=UC_X86_REG_EAX, ebx=UC_X86_REG_EBX, ecx=UC_X86_REG_ECX, edx=UC_X86_REG_EDX,
            esi=UC_X86_REG_ESI, edi=UC_X86_REG_EDI, ebp=UC_X86_REG_EBP, esp=UC_X86_REG_ESP)
STACK_TOP = 0x10F00000
SENTINEL = 0x0FFF0000
SCRATCH = 0x11000000


class Emu:
    def __init__(self, img):
        self.mu = mu = uc.Uc(uc.UC_ARCH_X86, uc.UC_MODE_32)
        size = (len(img.mem) + 0xFFF) & ~0xFFF
        mu.mem_map(img.BASE, size)
        mu.mem_write(img.BASE, bytes(img.mem))
        mu.mem_map(STACK_TOP - 0x100000, 0x100000)
        mu.mem_map(SENTINEL, 0x1000)
        mu.mem_map(SCRATCH, 0x10000)
        self.stubs = {}
        self.stops = set()
        self.writes = []
        self.watch = None
        self.trace_calls = []
        mu.hook_add(uc.UC_HOOK_CODE, self._code)
        mu.hook_add(uc.UC_HOOK_MEM_WRITE, self._write)
        self.stopped_at = None

    # --- memory helpers
    def w8(self, a, v): self.mu.mem_write(a, bytes([v & 0xFF]))
    def w32(self, a, v): self.mu.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))
    def wb(self, a, b): self.mu.mem_write(a, bytes(b))
    def r8(self, a): return self.mu.mem_read(a, 1)[0]
    def r32(self, a): return struct.unpack("<I", self.mu.mem_read(a, 4))[0]
    def rb(self, a, n): return bytes(self.mu.mem_read(a, n))
    def reg(self, r): return self.mu.reg_read(REGS[r])
    def setreg(self, r, v): self.mu.reg_write(REGS[r], v & 0xFFFFFFFF)

    def stub(self, addr, ret=0, argbytes=0):
        """Make the function at addr return immediately with eax=ret."""
        self.stubs[addr] = (ret, argbytes)

    def _code(self, mu, addr, size, _):
        if addr == SENTINEL or addr in self.stops:
            self.stopped_at = addr
            mu.emu_stop()
            return
        if addr in self.stubs:
            ret, n = self.stubs[addr]
            esp = mu.reg_read(UC_X86_REG_ESP)
            ra = struct.unpack("<I", mu.mem_read(esp, 4))[0]
            self.trace_calls.append(addr)
            mu.reg_write(UC_X86_REG_EAX, ret(self) if callable(ret) else ret)
            mu.reg_write(UC_X86_REG_ESP, esp + 4 + n)
            mu.reg_write(UC_X86_REG_EIP, ra)

    def _write(self, mu, access, addr, size, value, _):
        if self.watch is not None:
            lo, hi = self.watch
            if lo <= addr < hi:
                self.writes.append((addr, size))

    def call(self, func, *args, regs=None, max_insns=2_000_000):
        """cdecl call; returns eax. Fails unless the function returns to us with esp intact."""
        esp = STACK_TOP - 0x1000
        for a in reversed(args):
            esp -= 4
            self.w32(esp, a)
        esp -= 4
        self.w32(esp, SENTINEL)
        self.setreg("esp", esp)
        for k, v in (regs or {}).items():
            self.setreg(k, v)
        self.stopped_at = None
        self.mu.emu_start(func, 0, count=max_insns)
        if self.stopped_at != SENTINEL:
            raise AssertionError("function %08X did not return (stopped at %s, eip=%08X)" % (
                func, self.stopped_at, self.mu.reg_read(UC_X86_REG_EIP)))
        assert self.reg("esp") == esp + 4, "esp not restored by %08X" % func
        return self.reg("eax")

    def run_until(self, start, stops, regs=None, esp=None, max_insns=200_000):
        """Run from `start` (e.g. a cave jumped to mid-function) until one of `stops`."""
        self.stops = set(stops)
        if esp is None:
            esp = STACK_TOP - 0x2000
        self.setreg("esp", esp)
        for k, v in (regs or {}).items():
            self.setreg(k, v)
        self.stopped_at = None
        self.mu.emu_start(start, 0, count=max_insns)
        self.stops = set()
        return self.stopped_at


def page_header_sprites(e, page, x=100):
    """Run the "P.n" page header (0x4C0370) for a 0-based page; return the (sprite, x) it draws."""
    calls = []

    def draw(em):          # 0x4B7210(ctx, prim, sprite, x, y, colour) -> next prim
        esp = em.reg("esp")
        a = [em.r32(esp + 4 + 4 * i) for i in range(4)]
        calls.append((a[2] & 0xFF, a[3]))
        return a[1]
    e.stub(0x4B7210, ret=draw)
    try:
        e.call(0x4C0370, 0, SCRATCH, x, 0x38, 0, page)
    finally:
        del e.stubs[0x4B7210]
    return calls


# sprites: 0x32 = "P.", 0x28 + d = digit d
PAGE_HEADER_EXPECT = {
    1: [(0x32, 100), (0x2A, 109)],                    # "P.2", vanilla layout
    8: [(0x32, 100), (0x31, 109)],                    # "P.9"
    11: [(0x32, 100), (0x29, 109), (0x2A, 115)],      # "P.12"
    15: [(0x32, 100), (0x29, 109), (0x2E, 115)],      # "P.16"
}
