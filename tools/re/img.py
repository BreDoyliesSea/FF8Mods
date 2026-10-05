import struct, pefile, capstone, os
HERE=os.path.dirname(os.path.abspath(__file__))
EXE=os.environ.get('FF8_EXE', os.path.expanduser('~/.local/share/Steam/steamapps/common/FINAL FANTASY VIII/FF8_EN.exe'))
_pe=pefile.PE(EXE, fast_load=True)
_raw=open(EXE,'rb').read()
BASE=0x400000
# build flat image
size=max(s.VirtualAddress+max(s.Misc_VirtualSize,s.SizeOfRawData) for s in _pe.sections)
img=bytearray(size)
img[0:0x1000]=_raw[0:0x1000]
for s in _pe.sections:
    img[s.VirtualAddress:s.VirtualAddress+s.SizeOfRawData]=_raw[s.PointerToRawData:s.PointerToRawData+s.SizeOfRawData]
img=bytes(img)
def u8(a): return img[a-BASE]
def u16(a): return struct.unpack_from('<H',img,a-BASE)[0]
def u32(a): return struct.unpack_from('<I',img,a-BASE)[0]
def s32(a): return struct.unpack_from('<i',img,a-BASE)[0]
def rd(a,n): return img[a-BASE:a-BASE+n]
def rc(base,off):
    a=base+off
    op=u8(a)
    if op in (0xE8,0xE9): return (a+5+s32(a+1))&0xffffffff
    if u16(a)==0x15FF: return u32(u32(a+2))  # call [imm]
    raise ValueError('not a call at %x: %s'%(a,rd(a,6).hex()))
def av(base,off): return u32(base+off)
md=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_32); md.detail=False
def dis(a,n=40,stop_ret=False):
    out=[]
    for i in md.disasm(rd(a,n*15),a):
        out.append('%08x: %-24s %s %s'%(i.address,i.bytes.hex(),i.mnemonic,i.op_str))
        if len(out)>=n or (stop_ret and i.mnemonic=='ret'): break
    return '\n'.join(out)
def disf(a,maxn=3000):
    """disassemble until ret followed by int3/nop padding or new prologue"""
    out=[]
    for i in md.disasm(rd(a,maxn*15),a):
        out.append(i)
        if i.mnemonic in('ret','jmp') and len(out)>3:
            nxt=i.address+i.size
            b=img[nxt-BASE]
            if b in (0xCC,0x90) or rd(nxt,3)==b'\x55\x8b\xec' or rd(nxt,1) in (b'\x83',b'\x81',b'\x53',b'\x56',b'\x57',b'\x8b',b'\x6a',b'\x51') and False:
                break
        if len(out)>=maxn: break
    return out
def fmt(ins): return '\n'.join('%08x: %-20s %s %s'%(i.address,i.bytes.hex(),i.mnemonic,i.op_str) for i in ins)
TEXT=(0x401000,0x401000+0x768000)
def find(pat, start=TEXT[0], end=TEXT[1]):
    res=[];s=img.find(pat,start-BASE,end-BASE)
    while s!=-1 and s<end-BASE:
        res.append(s+BASE); s=img.find(pat,s+1,end-BASE)
    return res
def xrefs_call(target):
    """find E8 calls to target in .text"""
    res=[]
    t=img[TEXT[0]-BASE:TEXT[1]-BASE]
    i=t.find(b'\xe8')
    while i!=-1:
        a=TEXT[0]+i
        if i+5<=len(t) and ((a+5+struct.unpack_from('<i',t,i+1)[0])&0xffffffff)==target: res.append(a)
        i=t.find(b'\xe8',i+1)
    return res
def xrefs_imm(val):
    return find(struct.pack('<I',val))
