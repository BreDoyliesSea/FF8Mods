import sys,json,os
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from img import *
_j=json.load(open(os.path.join(HERE,'externals.json')))
E={k:int(v,16) for k,v in _j['E'].items()}; C={k:int(v,16) for k,v in _j['C'].items()}
