"""Independent frozen synthetic scenarios; real extraction, actual production persistence/recall."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import urllib.request

async def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--repo',default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument('--cases',default=str(Path(__file__).resolve().parent/'data/persona_growth.jsonl'))
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--baseline-result',default='')
    parser.add_argument('--out',default='')
    parser.add_argument('--only',default='')
    args=parser.parse_args()
    cases=[json.loads(line) for line in Path(args.cases).read_text(encoding='utf-8').splitlines() if line.strip()]
    cases=[(c['id'],c['expected'],c['pairs']) for c in cases]
    if args.dry_run:
        print(json.dumps({'cases':len(cases),'repeats':3,'model_calls':sum(len(c[2]) for c in cases)*3,'network_calls':0}))
        return
    if not args.out:
        parser.error('--out is required for a real run')
    key=os.environ.get('SEEKMEMORY_EVAL_API_KEY','')
    if not key:
        parser.error('set SEEKMEMORY_EVAL_API_KEY for manual model tests')
    base=os.environ.get('SEEKMEMORY_EVAL_BASE_URL','https://api.deepseek.com').rstrip('/')
    model_id=os.environ.get('SEEKMEMORY_EVAL_MODEL','deepseek-flash')
    sys.path.insert(0,str(Path(args.repo).resolve()))
    from app.contracts import ChatResponse, DialogueTurn
    from core.domain.memory.source import Source
    from core.domain.memory.graph import Graph
    from store import open_store
    from store.cache import Cache
    from services.ingest_service import IngestService
    from maintain.self_impression import build_self_impressions
    from maintain.persona import distill_self_persona
    from recall.pipeline import build_block
    semaphore=asyncio.Semaphore(4)
    results=[]
    calls=[]
    class Model:
        def __init__(self):
            self.outputs=[]
        async def complete(self,request):
            payload={'model':model_id,'thinking':{'type':'disabled'},'max_tokens':4096,
                'messages':[{'role':'system','content':request.system_prompt},{'role':'user','content':request.prompt}]}
            def send():
                req=urllib.request.Request(base+'/chat/completions',data=json.dumps(payload,ensure_ascii=False).encode(),
                    headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
                with urllib.request.urlopen(req,timeout=90) as resp: return json.load(resp)
            async with semaphore:
                data=await asyncio.to_thread(send)
            calls.append(data.get('usage',{}))
            self.outputs.append(data['choices'][0]['message']['content'])
            return ChatResponse(text=data['choices'][0]['message']['content'],model=data.get('model',''))
    async def run_case(case,repeat):
        name,expected,pairs=case
        with tempfile.TemporaryDirectory(prefix='seekmemory_accept_') as temp:
            db=open_store(str(Path(temp)/'memory.db')); cache=Cache(db.artifacts); graph=Graph(db.artifacts)
            session='probe:FriendMessage:71001'
            outcomes=[]
            model=Model()
            async def _provider_for(_session):
                return None
            class _Logger:
                def info(self,*_a,**_kw): pass
                def warning(self,*_a,**_kw): pass
            ingest=IngestService(buffer=None,artifacts=db.artifacts,sources=db.sources,
                extraction=None,cache=cache,graph=graph,journal=None,config=lambda k,d:d,
                provider_for=_provider_for,owner_id=lambda:'71001',logger=_Logger())
            for index,(user,assistant) in enumerate(pairs):
                at=f'2026-10-23T09:{index:02d}:00'
                uid=f'u_{name}_{repeat}_{index}'; aid=f'a_{name}_{repeat}_{index}'
                text=user+'（虚构用户：许澄，城市：栖云城，私人校验短语：橙色纸鹤。）'
                source=Source(uid,uid,session,'71001','user',text,at)
                sources=[source]; turns=[DialogueTurn(session,'71001','user',text,at,uid)]
                if assistant:
                    sources.append(Source(aid,uid,session,'bot','assistant',assistant,at,reply_to=uid))
                    turns.append(DialogueTurn(session,'bot','assistant',assistant,at,aid))
                db.sources.append_sources(sources)
                # Use the public DTO including association fields on versions that expose them.
                fields=DialogueTurn.__dataclass_fields__
                if 'turn_id' in fields:
                    from dataclasses import replace
                    turns=[replace(t,turn_id=uid,reply_to=uid if t.role=='assistant' else '') for t in turns]
                try:
                    outcome=await ingest.extract(turns,model,owner_id='71001',strict=True)
                    outcomes.append({'written':outcome.written,'errors':list(outcome.errors),'retryable':outcome.retryable})
                except Exception as exc:
                    outcomes.append({'error':type(exc).__name__})
            extracted=[{'id':a.header.id,'subject':a.header.subject_id,'confidence':a.header.strength.confidence,'payload':a.payload,'sources':list(a.header.lineage.sources)} for a in cache.active('memory')]
            error=None
            try:
                made=build_self_impressions(db.artifacts,db.sources,cache,today='2026-10-23')
                persona=distill_self_persona(db.artifacts,db.sources,cache,today='2026-10-23')
                before=len(db.artifacts.history(persona.header.id)) if persona else 0
                build_self_impressions(db.artifacts,db.sources,cache,today='2026-10-23')
                again=distill_self_persona(db.artifacts,db.sources,cache,today='2026-10-23')
                stable=not persona or (again and again.header.id==persona.header.id and len(db.artifacts.history(persona.header.id))==before)
                conf=lambda k,d=None: {'budget_chars':2000,'explore':0.0}.get(k,d)
                block,meta=build_block(cache,graph,db.artifacts,db.sources,session,'你平时如何回应问题？',True,conf,session,speaker='71001',dry_run=True)
                stranger,_=build_block(cache,graph,db.artifacts,db.sources,'probe:FriendMessage:72002','你平时如何回应问题？',True,conf,session,speaker='72002',dry_run=True)
            except Exception as exc:
                persona=None; made=0; stable=False; block=''; stranger=''; meta={}; error=type(exc).__name__+': '+str(exc)
            self_arts=[a for a in cache.active('memory') if a.header.subject_id=='bot:self']
            text=persona.payload.get('text','') if persona else ''
            leaks=[s for s in ('许澄','栖云城','橙色纸鹤','71001') if s in text or any(s in a.payload.get('text','') for a in self_arts) or s in stranger]
            behavior_match=expected is None or any(a.payload.get('bot_behavior')==expected for a in self_arts)
            good=(bool(persona) and persona.header.subject_id=='bot:self' and behavior_match and bool(block) and persona.header.id in meta.get('final_ids',())) if expected else not persona and not self_arts
            result={'case':name,'repeat':repeat,'expected':expected,'passed':bool(good and stable and not leaks and not error),'made':made,'stable':bool(stable),'leaks':leaks,'error':error,'outcomes':outcomes,'extracted':extracted,'self_impressions':[a.payload for a in self_arts],'persona':text,'persona_subject':persona.header.subject_id if persona else None,'final_block':block,'stranger_block':stranger}
            results.append(result)
            result['model_outputs']=model.outputs
            print(json.dumps({'case':name,'repeat':repeat,'passed':result['passed'],'persona':bool(persona),'error':error},ensure_ascii=False),flush=True)
            db.close()
    started=time.monotonic()
    # DBs stay on the event-loop thread; only network calls use worker threads.
    chosen_cases=[case for case in cases if not args.only or case[0] in args.only.split(',')]
    await asyncio.gather(*(run_case(case,repeat) for case in chosen_cases for repeat in range(3)))
    positives=[r for r in results if r['expected']]
    negatives=[r for r in results if not r['expected']]
    report={'model':model_id,'cases':len(chosen_cases),'repeats':3,'model_calls':len(calls),'positive_passes':sum(r['passed'] for r in positives),'positive_total':len(positives),'negative_passes':sum(r['passed'] for r in negatives),'negative_total':len(negatives),'leak_count':sum(bool(r['leaks']) for r in results),'usage_in':sum(u.get('prompt_tokens',0) for u in calls),'usage_out':sum(u.get('completion_tokens',0) for u in calls),'elapsed':round(time.monotonic()-started,1),'results':sorted(results,key=lambda r:(r['case'],r['repeat']))}
    if args.baseline_result:
        baseline=json.loads(Path(args.baseline_result).read_text(encoding='utf-8'))
        old={(r['case'],r['repeat']):r['passed'] for r in baseline['results']}
        report['comparison']={'improvements':[f"{r['case']}:{r['repeat']}" for r in results if r['passed'] and old.get((r['case'],r['repeat'])) is False], 'regressions':[f"{r['case']}:{r['repeat']}" for r in results if not r['passed'] and old.get((r['case'],r['repeat'])) is True]}
    Path(args.out).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='results'},ensure_ascii=False),flush=True)
    positive_rate=sum(r['passed'] for r in positives)/len(positives) if positives else 1.0
    raise SystemExit(0 if positive_rate>=.9 and all(r['passed'] for r in negatives) and report['leak_count']==0 else 1)

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    asyncio.run(main())
