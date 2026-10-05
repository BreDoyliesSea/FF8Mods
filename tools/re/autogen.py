import re,sys
def auto(f, lo=0, hi=1<<32, xmov=True, exclude=()):
    L=[l.rstrip() for l in open('fdump/%s.asm'%f) if not l.rstrip().endswith('nop')]
    out=[]
    for l in L:
        a=int(l[:8],16); t=l[10:]
        if not(lo<=a<hi) or a in exclude: continue
        if 'MAGIC' in l: out.append('(0x%X, "rel")'%a)
        elif re.search(r'cmp e.., 0x20$',t): out.append('(0x%X, "x", 0x20, 0x40)'%a)
        elif xmov and re.search(r'mov (e..|dword ptr \[esp \+ 0x[0-9a-f]+\]), 0x20$',t): out.append('(0x%X, "x", 0x20, 0x40)'%a)
    return out
def emit(title, entries, extra=''):
    body='\n    # ---- %s\n'%title
    for k in range(0,len(entries),4): body+='    '+', '.join(entries[k:k+4])+',\n'
    body+=extra
    p=__import__('os').path.join(__import__('os').path.dirname(__import__('os').path.abspath(__file__)),'..','magic_sites.py'); s=open(p).read()
    s=s.rstrip().rstrip(']')+body+']\n'
    open(p,'w').write(s)
    print(title, len(entries))
