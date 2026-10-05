import sys, collections, capstone, struct
sys.path.insert(0,'.')
from img import *
from capstone import x86_const as X
md2=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_32); md2.detail=True
CH=0x1cfe0e8; N=8; S=0x98
lo,hi=TEXT
res=[]
a=lo
while a<hi:
    last=a
    for i in md2.disasm(rd(a,min(0x10000,hi-a)),a):
        last=i.address+i.size
        for op in i.operands:
            v=None
            if op.type==X.X86_OP_MEM: v=op.mem.disp&0xffffffff; kind='mem'
            elif op.type==X.X86_OP_IMM: v=op.imm&0xffffffff; kind='imm'
            if v is not None and CH-0x10<=v<CH+N*S+0x60:
                res.append((i.address,i.mnemonic,i.op_str,v,kind))
    a=last if last>a else a+1
import pickle; pickle.dump(res,open('charrefs.pkl','wb'))
print(len(res))
c=collections.Counter(((v-CH)%S) for _,_,_,v,_ in res)
for off,n in sorted(c.items()): print(hex(off),n)
