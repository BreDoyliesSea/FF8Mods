import sys,pickle,bisect,capstone,re
sys.path.insert(0,'.')
from img import *
from capstone import x86_const as X
md2=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_32); md2.detail=True
g=pickle.load(open('funcs.pkl','rb'))
starts,live,deadc=pickle.load(open('reach.pkl','rb'))
CH=0x1cfe0e8;S=0x98
def end_of(c):
    k=bisect.bisect_right(starts,c); return starts[k] if k<len(starts) else TEXT[1]
REGN={X.X86_REG_EAX:'eax',X.X86_REG_EBX:'ebx',X.X86_REG_ECX:'ecx',X.X86_REG_EDX:'edx',X.X86_REG_ESI:'esi',X.X86_REG_EDI:'edi',X.X86_REG_EBP:'ebp'}
def full(r):
    n=md2.reg_name(r)
    for k,v in {'al':'eax','ah':'eax','ax':'eax','bl':'ebx','bh':'ebx','bx':'ebx','cl':'ecx','ch':'ecx','cx':'ecx','dl':'edx','dh':'edx','dx':'edx','si':'esi','di':'edi','bp':'ebp'}.items():
        if n==k: return v
    return n
for c in sorted(g):
    refs=[x for x in g[c] if x[3]==0]
    if not refs: continue
    e=end_of(c)
    ins=list(md2.disasm(rd(c,e-c),c))
    report=[]
    for a,m,o,off,ci in refs:
        k=next(i for i,x in enumerate(ins) if x.address==a)
        i0=ins[k]
        if i0.mnemonic not in('lea','mov') or i0.operands[0].type!=X.X86_OP_REG:
            continue
        t={full(i0.operands[0].reg)}
        for x in ins[k+1:k+120]:
            if not t: break
            # uses
            for op in x.operands:
                if op.type==X.X86_OP_MEM and op.mem.base and full(op.mem.base) in t:
                    d=op.mem.disp
                    if 0x10<=d<0x50 or (op.mem.index and d<0x50):
                        report.append('  %08x %s %s   [via %s from %08x]'%(x.address,x.mnemonic,x.op_str,full(op.mem.base),a))
            if x.mnemonic=='push' and x.operands[0].type==X.X86_OP_REG and full(x.operands[0].reg) in t:
                report.append('  %08x push %s (char ptr passed)   [from %08x]'%(x.address,x.op_str,a))
            if x.mnemonic=='mov' and x.operands[0].type==X.X86_OP_MEM and x.operands[1].type==X.X86_OP_REG and full(x.operands[1].reg) in t:
                report.append('  %08x %s %s (char ptr stored)   [from %08x]'%(x.address,x.mnemonic,x.op_str,a))
            if x.mnemonic in('add','sub','lea') and x.operands[0].type==X.X86_OP_REG and full(x.operands[0].reg) in t and x.mnemonic!='lea':
                report.append('  %08x %s %s (ptr arith)   [from %08x]'%(x.address,x.mnemonic,x.op_str,a))
            # propagate mov reg,reg
            if x.mnemonic=='mov' and len(x.operands)==2 and x.operands[0].type==X.X86_OP_REG and x.operands[1].type==X.X86_OP_REG and full(x.operands[1].reg) in t:
                t.add(full(x.operands[0].reg)); continue
            # kill on write
            if x.operands and x.operands[0].type==X.X86_OP_REG and x.mnemonic not in('cmp','test','push') and full(x.operands[0].reg) in t and x.mnemonic not in('add','sub'):
                t.discard(full(x.operands[0].reg))
            if x.mnemonic in('ret','jmp'): break
    if report:
        print('== %08x'%c); print('\n'.join(sorted(set(report))))
