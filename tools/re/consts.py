import sys,re
f=sys.argv[1]
L=[l.rstrip() for l in open('fdump/%s.asm'%f) if not l.rstrip().endswith('nop')]
for i,l in enumerate(L):
    if re.search(r', (0x20|0x1f|0x40|0x3f|0x3e|0x1e)$', l) or re.search(r'push (0x20|0x40)$',l) or 'MAGIC' in l or re.search(r'char\d\+0x5[01]',l):
        print(l)
