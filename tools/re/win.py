import sys
f=sys.argv[1]; B=int(sys.argv[2]) if len(sys.argv)>2 else 12; A=int(sys.argv[3]) if len(sys.argv)>3 else 12
L=[l for l in open('fdump/%s.asm'%f) if not l.rstrip().endswith('nop')]
keep=set()
for i,l in enumerate(L):
    if '<<<' in l:
        for j in range(max(0,i-B),min(len(L),i+A+1)): keep.add(j)
prev=-2
for i in sorted(keep):
    if i!=prev+1: print('   ...')
    print(L[i].rstrip()); prev=i
