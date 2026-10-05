import re, json, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from img import *
src=open(os.environ.get('FFNX_DATA_CPP','FFNx/src/ff8_data.cpp')).read()
start=src.index('void ff8_find_externals()')
body=src[start:]
lines=body.split('\n')
E={'start':0x55ADB7}
C={}
flags={'JP_VERSION':False,'NV_VERSION':True,'FF8_US_VERSION':True,'FF8_SP_VERSION':False,'FF8_FR_VERSION':False,'FF8_DE_VERSION':False,'FF8_IT_VERSION':False,'steam_edition':True,'remastered_edition':False}
def cexpr(e):
    e=re.sub(r'\b(ff8_externals|common_externals)\.(\w+)',lambda m:("E" if m.group(1)[0]=='f' else "C")+"['"+m.group(2)+"']",e)
    # strip casts like (uint8_t *) or (int(*)(int, int)) or (WNDPROC)
    for _ in range(3):
        e=re.sub(r'\(\s*(const\s+)?[A-Za-z_][\w:]*\s*(\*\s*)*\)(?=\s*[\w(])','',e)
        e=re.sub(r'\(\s*[A-Za-z_][\w:]*\s*\(\s*\*\s*\)\s*\([^()]*\)\s*\)(?=\s*[\w(])','',e)
    e=re.sub(r'\b(uint32_t|DWORD|int|uint8_t)\s*\(','(',e)
    e=re.sub(r'(\w+)\s*\?\s*([^:()]+?)\s*:\s*','\\2 if \\1 else ',e) # crude ternary
    e=re.sub(r"([EC]\['\w+'\])\[([^\]]+)\]\.func",r"u32(\1+8*(\2)+4)",e)
    e=re.sub(r"([EC]\['\w+'\])\[([^\]]+)\]",r"u32(\1+4*(\2))",e)
    e=e.replace('get_relative_call','rc').replace('get_absolute_value','av')
    e=e.replace('&&',' and ').replace('||',' or ').replace('!','not ')
    return e
stack=[]  # (cond, braces depth)
depth=0
pending=None; skip=False
active=[True]
i=0; ok=0; fail=0
cond_stack=[]
txt=body
# simple approach: walk lines tracking if blocks
blk=[]  # list of (active_bool, depth_at_open)
cur_active=True
pending_cond=None
for ln in lines[1:]:
    s=ln.strip()
    if s.startswith('//') or not s: continue
    m=re.match(r'(else\s+)?if\s*\((.*)\)\s*$',s)
    if m:
        cond=m.group(2)
        try: val=eval(re.sub(r'\b[A-Z_]+_VERSION\b|\bsteam_edition\b|\bremastered_edition\b',lambda x:str(flags.get(x.group(0),False)),cexpr(cond)),{'E':E,'C':C})
        except Exception: val=False
        if m.group(1): val = val and not blk_last_taken
        pending_cond=bool(val); continue
    if s=='else':
        pending_cond=not blk_last_taken; continue
    if s=='{':
        par=all(b[0] for b in blk)
        blk.append((pending_cond if pending_cond is not None else True,))
        pending_cond=None; continue
    if s.startswith('}'):
        if not blk: break
        blk_last_taken=blk.pop()[0]; continue
    act=all(b[0] for b in blk)
    if pending_cond is not None:
        # single statement if
        act=act and pending_cond; blk_last_taken=pending_cond; pending_cond=None
    if not act: continue
    m=re.match(r'(ff8_externals|common_externals)\.(\w+)\s*=\s*(.*);$',s)
    if not m: continue
    tgt=E if m.group(1)[0]=='f' else C
    try:
        v=eval(cexpr(m.group(3)),{'E':E,'C':C,'rc':rc,'av':av,'u32':u32})
        if isinstance(v,int): tgt[m.group(2)]=v&0xffffffff; ok+=1
    except Exception as ex:
        fail+=1
print('ok',ok,'fail',fail, file=sys.stderr)
json.dump({'E':{k:hex(v) for k,v in E.items()},'C':{k:hex(v) for k,v in C.items()}},open(os.path.join(HERE,'externals.json'),'w'),indent=0)
