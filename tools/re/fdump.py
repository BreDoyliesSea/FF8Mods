import sys,pickle,bisect,re
sys.path.insert(0,'.')
from img import *
g=pickle.load(open('funcs.pkl','rb'))
starts,live,deadc=pickle.load(open('reach.pkl','rb'))
CH=0x1cfe0e8;S=0x98
lines=open('text.asm').read().split('\n')
idx={}
for n,l in enumerate(lines):
    if l[:8].strip(): idx[l[:8]]=n
def end_of(c):
    k=bisect.bisect_right(starts,c); return starts[k] if k<len(starts) else TEXT[1]
for c in sorted(g):
    e=end_of(c)
    n=idx.get('%08x'%c)
    if n is None: continue
    out=[]
    refs={a:(off,ci) for a,m,o,off,ci in g[c]}
    while n<len(lines):
        l=lines[n]
        a=int(l[:8],16)
        if a>=e: break
        if l.endswith(': nop') or l.endswith(': int3'): n+=1; continue
        tag=''
        if a in refs:
            off,ci=refs[a]; tag='   <<< char%d+0x%x'%(ci,off)
            if 0x10<=off<0x50: tag+=' MAGIC slot %d%s'%((off-0x10)//2,' qty' if off&1 else '')
        out.append(l+tag); n+=1
    open('fdump/%08x.asm'%c,'w').write('\n'.join(out)+'\n')
print('ok')
