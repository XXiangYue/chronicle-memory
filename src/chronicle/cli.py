"""Project-specific entry points; inference credentials come from the environment."""
import argparse, json, uuid
from pathlib import Path
from .common import ROOT
def output(v): print(json.dumps(v,ensure_ascii=False,indent=2))
def main():
    p=argparse.ArgumentParser(prog='chronicle')
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('results',help='Read the measured summary without API calls')
    ing=sub.add_parser('ingest');ing.add_argument('--db',type=Path,required=True);ing.add_argument('--namespace',required=True);ing.add_argument('--sources',type=Path,required=True);ing.add_argument('--extract',action='store_true')
    q=sub.add_parser('query');q.add_argument('--db',type=Path,required=True);q.add_argument('--namespace',required=True);q.add_argument('--question',required=True);q.add_argument('--known-at',required=True);q.add_argument('--as-of',required=True);q.add_argument('--arm',choices=['M0','M1','M2'],default='M2');q.add_argument('--language',choices=['zh','en'],default='en')
    d=sub.add_parser('delete');d.add_argument('--db',type=Path,required=True);d.add_argument('--namespace',required=True);d.add_argument('--source-id',required=True)
    e=sub.add_parser('evaluate-public');e.add_argument('--out',type=Path,required=True);e.add_argument('--limit',type=int);e.add_argument('--workers',type=int,default=4)
    e=sub.add_parser('evaluate-custom');e.add_argument('--out',type=Path,required=True);e.add_argument('--split',choices=['dev','test'],default='test')
    a=p.parse_args()
    if a.command=='results':
        output(json.loads((ROOT/'results/measured_summary.json').read_text()));return
    if a.command=='evaluate-public':
        from .public_memory_eval import evaluate_public
        output(evaluate_public(a.out,limit=a.limit,workers=a.workers));return
    if a.command=='evaluate-custom':
        from .memory_eval import evaluate_custom
        output(evaluate_custom(a.out,split=a.split));return
    from .memory import Memory, answer
    from .model import Model
    m=Memory(a.db,a.namespace)
    if a.command=='ingest':
        m.ingest(json.loads(a.sources.read_text()));output(m.extract(Model()) if a.extract else {'ingested':True});return
    if a.command=='delete':m.delete(a.source_id);output({'logical_tombstone':a.source_id});return
    evidence,info=m.context(a.question,a.arm,a.known_at,a.as_of,a.language)
    result,meta,_=answer(Model(),a.question,evidence,label='demo:memory',known_at=a.known_at,as_of=a.as_of)
    output({'answer':result,'evidence':evidence,'context':info,'usage':meta['usage']})
if __name__=='__main__':main()
