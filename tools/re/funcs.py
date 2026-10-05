import sys,pickle,bisect,collections
sys.path.insert(0,'.')
from img import *
res=pickle.load(open('charrefs.pkl','rb'))
starts,live,deadc=pickle.load(open('reach.pkl','rb'))
CH=0x1cfe0e8;S=0x98
def chunk(a): return starts[bisect.bisect_right(starts,a)-1]
g=collections.defaultdict(list)
for a,m,o,v,k in res: g[chunk(a)].append((a,m,o,(v-CH)%S,(v-CH)//S))
out=[]
for c in sorted(g):
    offs=sorted(set(x[3] for x in g[c]))
    mag=[x for x in g[c] if 0x10<=x[3]<0x50 or x[3]==0x50]
    out.append((c,len(g[c]),len(mag),offs))
pickle.dump(g,open('funcs.pkl','wb'))
nm=0
for c,n,m,offs in out:
    if any(0x10<=o<=0x50 for o in offs) or 0 in offs:
        nm+=1
        print(hex(c),'refs',n,'magic',m,'offs',[hex(o) for o in offs], 'DEAD' if c not in live else '')
print('functions',nm)
