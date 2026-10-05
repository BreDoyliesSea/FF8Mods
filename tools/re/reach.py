import sys,struct,re,capstone,pickle,bisect,collections
sys.path.insert(0,'.')
from img import *
lo,hi=TEXT
t=img[lo-BASE:hi-BASE]
starts=sorted(set([lo]+[m.end()+lo for m in re.finditer(rb'(?:\xc3|\xc2..)(\x90|\xcc)+',t)]))
def chunk(a):
    return starts[bisect.bisect_right(starts,a)-1]
md2=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_32)
edges=collections.defaultdict(set)
a=lo
while a<hi:
    last=a
    for i in md2.disasm(rd(a,min(0x10000,hi-a)),a):
        last=i.address+i.size
        for tt in re.findall(r'0x([0-9a-f]{6,7})\b',i.op_str):
            v=int(tt,16)
            if lo<=v<hi: edges[chunk(i.address)].add(chunk(v))
    a=last if last>a else a+1
# unaligned dwords inside .text (e.g. jump tables) -> edges from containing chunk
for k in range(0,len(t)-3):
    v=struct.unpack_from('<I',t,k)[0]
    if lo<=v<hi: edges[chunk(lo+k)].add(chunk(v))
roots=set([chunk(0x55ADB7)])
for base,size in ((0xb69000,0x4000),(0xb6d000,0xd1f000),(0x23c1000,0x1000),(0x23c2000,0x68610),(0x239f000,0x21d84)):
    seg=img[base-BASE:base-BASE+size]
    for k in range(0,len(seg)-3):
        v=struct.unpack_from('<I',seg,k)[0]
        if lo<=v<hi: roots.add(chunk(v))
live=set(); st=list(roots)
while st:
    c=st.pop()
    if c in live: continue
    live.add(c); st.extend(edges[c]-live)
deadc=[(s, (starts[k+1] if k+1<len(starts) else hi)-s) for k,s in enumerate(starts) if s not in live]
print('chunks',len(starts),'live',len(live),'dead',len(deadc),'bytes',sum(n for _,n in deadc))
deadc.sort(key=lambda x:-x[1])
print([(hex(s),hex(n)) for s,n in deadc[:25]])
pickle.dump((starts,live,deadc),open('reach.pkl','wb'))
