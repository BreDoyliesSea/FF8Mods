import sys
f=sys.argv[1]; B=int(sys.argv[2]); A=int(sys.argv[3]); lo=int(sys.argv[4],16) if len(sys.argv)>4 else 0; hi=int(sys.argv[5],16) if len(sys.argv)>5 else 1<<32
L=[l.rstrip() for l in open('fdump/%s.asm'%f) if not l.rstrip().endswith('nop')]
keep=set()
for i,l in enumerate(L):
    a=int(l[:8],16)
    if 'MAGIC' in l and lo<=a<hi:
        for j in range(max(0,i-B),min(len(L),i+A+1)): keep.add(j)
prev=-2
for i in sorted(keep):
    if i!=prev+1: print('   ...')
    print(L[i]); prev=i
