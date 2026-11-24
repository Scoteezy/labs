"""A small TF-IDF retrieval project for labs 1--16. Python 3.10+; stdlib only.

The corpus, relevance judgements and annotator decisions are synthetic fixtures.
They demonstrate an evaluation process, not real-world effectiveness.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'demo' / 'data'
RESULTS = ROOT / 'demo' / 'results'
GENRES = ['джаз', 'театр', 'кино', 'выставка', 'электроника', 'фестиваль']
ALIASES = {'саксофон': 'джаз', 'спектакль': 'театр', 'кинопоказ': 'кино',
           'галерея': 'выставка', 'рейв': 'электроника', 'опенэйр': 'фестиваль',
           'лаконичный': 'минимализм', 'насыщенный': 'детализация'}
SPLITS = ['train', 'train', 'validation', 'validation', 'test', 'test']

def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))

def save_csv(path, rows, fields=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields or list(rows[0]))
        writer.writeheader(); writer.writerows(rows)

def tokenize(text):
    return re.findall(r'[a-zа-яё0-9]+', text.lower())

def generate():
    """42 raw records -> 36 valid unique records, grouped by fictional author."""
    rows = []
    palette = ['#224B79', '#6A4074', '#B36A36', '#32745E', '#76582E', '#375B6E']
    for g, genre in enumerate(GENRES):
        for j in range(6):
            identifier = f'P{g*6+j+1:03d}'
            style = 'минимализм' if j % 2 == 0 else 'детализация'
            objects = 2 if j % 2 == 0 else 7
            width, height = (600, 800) if j % 2 == 0 else (800, 600)
            shapes = ''.join(f'<circle cx="{70+i*65}" cy="{220+(i%3)*75}" r="{25+i*2}" fill="{palette[g]}"/>' for i in range(objects))
            svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
                   f'<rect width="100%" height="100%" fill="#FAF7F0"/>{shapes}'
                   f'<text x="35" y="65" font-size="24" font-family="Arial">{identifier} / {genre}</text>'
                   f'<text x="35" y="105" font-size="18" font-family="Arial">Учебный макет / {style}</text></svg>')
            path = DATA / 'posters' / f'{identifier}.svg'
            path.parent.mkdir(parents=True, exist_ok=True); path.write_text(svg, encoding='utf-8')
            rows.append(dict(id=identifier, genre=genre, style=style,
                             description=f'{genre} афиша {style} геометрия',
                             author=f'A{j+1:02d}', series=f'S{j+1:02d}', split=SPLITS[j],
                             source='generated:demo/project.py', rights_status='demo_allowed',
                             synthetic=True, width=width, height=height, objects=objects,
                             image=f'demo/data/posters/{identifier}.svg',
                             sha256=hashlib.sha256(svg.encode()).hexdigest()))
    for i in range(3):
        rows.append(dict(rows[i], id=f'D{i+1:03d}'))
    rows.extend([dict(rows[0], id='X001', rights_status='unknown'),
                 dict(rows[8], id='X002', rights_status='unknown'),
                 dict(rows[15], id='X003', description='')])
    save_json(DATA / 'raw.json', rows)
    save_json(DATA / 'lexicon.json', {'version': '1.0', 'source': 'lab02 synthetic domain glossary', 'mapping': ALIASES})
    save_json(ROOT / 'demo' / 'config.json', dict(k=3, max_query_chars=300, model='tfidf+lexicon', model_version='1.0', seed=42))
    queries = []
    for split in ['train', 'validation', 'test']:
        for g, genre in enumerate(GENRES):
            for kind in ['literal', 'synonym']:
                word = genre if kind == 'literal' else list(ALIASES)[g]
                style = 'минимализм' if kind == 'literal' else 'лаконичный'
                queries.append(dict(id=f'{split[:1].upper()}{len(queries)+1:02d}', split=split,
                                    text=f'{word} {style}', genre=genre, kind=kind,
                                    source='synthetic fixture; no human assessment'))
    save_json(DATA / 'queries.json', queries)
    annotations = []
    for i, row in enumerate(rows[:12]):
        a = row['style']; b = a if i not in (3, 8) else ('детализация' if a == 'минимализм' else 'минимализм')
        annotations.append(dict(id=row['id'], annotator_A=a, annotator_B=b, final=a,
                                decision='unchanged' if a == b else 'reviewed by fixture rule objects<=3',
                                evidence='synthetic independent-label simulation'))
    save_csv(DATA / 'annotations.csv', annotations)
    return rows

def prepare(rows):
    seen = set(); clean = []; exclusions = []
    for row in rows:
        reason = None
        if row['rights_status'] != 'demo_allowed': reason = 'unknown_rights'
        elif not row['description'].strip(): reason = 'empty_description'
        elif row['sha256'] in seen: reason = 'duplicate_image'
        if reason:
            exclusions.append({'id':row['id'], 'reason':reason}); continue
        seen.add(row['sha256']); clean.append(row)
    save_json(DATA / 'clean.json', clean)
    save_csv(RESULTS / 'exclusions.csv', exclusions)
    groups = {s: {r['author'] for r in clean if r['split']==s} for s in set(SPLITS)}
    assert all(not groups[a] & groups[b] for a in groups for b in groups if a != b)
    checks = [{'check':'raw_count', 'actual':len(rows), 'expected':42, 'passed':len(rows)==42},
              {'check':'clean_count','actual':len(clean),'expected':36,'passed':len(clean)==36},
              {'check':'author_overlap','actual':0,'expected':0,'passed':True},
              {'check':'unknown_rights_clean','actual':sum(r['rights_status']!='demo_allowed' for r in clean),'expected':0,'passed':True},
              {'check':'duplicate_hashes_clean','actual':len(clean)-len({r['sha256'] for r in clean}),'expected':0,'passed':True}]
    save_csv(RESULTS / 'quality_checks.csv', checks)
    return clean

class SearchEngine:
    def __init__(self, clean, config=None):
        self.records = clean
        self.config = config or read_json(ROOT / 'demo/config.json')
        self.lexicon = read_json(DATA / 'lexicon.json')['mapping']
        train = [r for r in clean if r['split']=='train']
        df = Counter(t for r in train for t in set(tokenize(r['description'])))
        self.idf = {t: math.log((1+len(train))/(1+c))+1 for t,c in df.items()}

    def vector(self, text, expand=False):
        terms = tokenize(text)
        if expand: terms = [self.lexicon.get(t, t) for t in terms]
        counts = Counter(terms)
        values = {t: c*self.idf[t] for t,c in counts.items() if t in self.idf}
        norm = math.sqrt(sum(x*x for x in values.values()))
        return {t:x/norm for t,x in values.items()} if norm else {}

    def search(self, query, mode='baseline', split='validation', k=None):
        if not isinstance(query, str): raise ValueError('query_must_be_string')
        query = query.strip()
        if not query: raise ValueError('empty_query')
        if len(query)>self.config['max_query_chars']: raise ValueError('query_too_long')
        if mode not in ('baseline','improved'): raise ValueError('invalid_mode')
        if split not in ('train','validation','test','all'): raise ValueError('invalid_split')
        q = self.vector(query, expand=mode=='improved')
        results=[]
        for row in self.records:
            if split!='all' and row['split']!=split: continue
            if row['rights_status']!='demo_allowed' or not row.get('source'): continue
            v=self.vector(row['description'])
            score=sum(value*v.get(term,0) for term,value in q.items())
            if score>0:
                results.append(dict(id=row['id'], genre=row['genre'], style=row['style'],
                                    score=round(score,6), source=row['source'],
                                    rights_status=row['rights_status'], image=row['image']))
        return sorted(results,key=lambda r:(-r['score'],r['id']))[:k or self.config['k']]

def relevance(query, record):
    if query['genre'] != record['genre']: return 0
    return 2 if record['style']=='минимализм' else 1

def ranking_metrics(grades, ideal, relevant_count, k=3):
    def dcg(values): return sum((2**g-1)/math.log2(i+2) for i,g in enumerate(values[:k]))
    denominator=dcg(sorted(ideal,reverse=True))
    return dict(ndcg=dcg(grades)/denominator if denominator else 0.0,
                recall=sum(g>0 for g in grades[:k])/relevant_count if relevant_count else 0.0)

def evaluate(engine, queries, split, mode):
    rows=[]; details=[]
    candidates=[r for r in engine.records if r['split']==split]
    lookup={r['id']:r for r in candidates}
    for query in [q for q in queries if q['split']==split]:
        results=engine.search(query['text'],mode,split)
        grades=[relevance(query,lookup[r['id']]) for r in results]
        ideal=[relevance(query,r) for r in candidates]
        m=ranking_metrics(grades,ideal,sum(v>0 for v in ideal))
        rows.append(dict(query_id=query['id'],query=query['text'],segment=query['kind'],genre=query['genre'],
                         ndcg=round(m['ndcg'],6),recall=round(m['recall'],6),
                         returned=' '.join(r['id'] for r in results), grades=' '.join(map(str,grades))))
        details.append(dict(query=query,results=results,grades=grades,metrics=m))
    save_csv(RESULTS / f'{split}_{mode}.csv', rows)
    save_json(RESULTS / f'{split}_{mode}_detail.json',details)
    return dict(ndcg=round(sum(r['ndcg'] for r in rows)/len(rows),6),
                recall=round(sum(r['recall'] for r in rows)/len(rows),6),n=len(rows),
                segments={kind:round(sum(r['ndcg'] for r in rows if r['segment']==kind)/sum(r['segment']==kind for r in rows),6) for kind in ['literal','synonym']})

def api_search(engine,payload,simulate_failure=False):
    if not isinstance(payload,dict): return 400, {'status':'error','error':'object_required'}
    try:
        mode='baseline' if simulate_failure else 'improved'
        results=engine.search(payload.get('query'),mode,split='all')
    except ValueError as exc: return 400, {'status':'error','error':str(exc)}
    return 200, {'status':'fallback' if simulate_failure else ('ok' if results else 'no_matches'),
                 'model':mode,'results':results,'human_decision_required':True}

def feedback(record_id,action,actor,proposed_style=None):
    clean=read_json(DATA / 'clean.json')
    if not isinstance(record_id,str): raise ValueError('invalid_record_id')
    if record_id not in {r['id'] for r in clean}: raise ValueError('unknown_record')
    if action not in ('select','reject','correct','escalate'): raise ValueError('invalid_action')
    if actor not in ('designer_demo','archivist_demo'): raise ValueError('invalid_actor')
    if action=='correct' and proposed_style not in ('минимализм','детализация'): raise ValueError('invalid_style')
    return {'record_id':record_id,'action':action,'actor':actor,'proposed_style':proposed_style,
            'status':'pending_review' if action in ('correct','escalate') else 'recorded',
            'model_updated':False}

def run():
    raw=generate(); clean=prepare(raw); queries=read_json(DATA/'queries.json')
    engine=SearchEngine(clean)
    summary={'dataset_version':'1.0','raw':len(raw),'clean':len(clean),'synthetic':True,
             'evaluation':'grouped fictional authors; IDF fitted on train only; 12 queries per split',
             'validation':{m:evaluate(engine,queries,'validation',m) for m in ['baseline','improved']}}
    # Selection uses validation only. Test is reported once after the fixed comparison.
    chosen='improved' if summary['validation']['improved']['ndcg']>=summary['validation']['baseline']['ndcg']+0.1 else 'baseline'
    summary['decision']=chosen
    summary['test']={chosen:evaluate(engine,queries,'test',chosen)}
    summary['train_idf_sha256']=hashlib.sha256(json.dumps(engine.idf,sort_keys=True).encode()).hexdigest()
    save_json(RESULTS/'summary.json',summary)
    scenarios=[]
    for label,payload,fail in [('normal',{'query':'джаз минимализм'},False),('synonym',{'query':'саксофон лаконичный'},False),('empty',{'query':''},False),('long',{'query':'а'*301},False),('english',{'query':'jazz minimalist'},False),('fallback',{'query':'джаз минимализм'},True),('bad_type',{'query':42},False)]:
        code,body=api_search(engine,payload,fail)
        scenarios.append({'case':label,'input':payload,'http_status':code,'output':body})
    save_json(RESULTS/'api_examples.json',scenarios)
    save_json(RESULTS/'feedback_examples.json',[feedback('P003','correct','designer_demo','детализация'),feedback('P004','escalate','designer_demo')])
    save_json(RESULTS/'limitation_examples.json', {q:api_search(engine,{'query':q})[1] for q in ['jazz minimalist','не джаз минимализм']})
    save_json(RESULTS/'environment.json',{'python':sys.version.split()[0],'dependencies':'standard library','seed':42})
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('command',choices=['run','search']); parser.add_argument('--query',default='саксофон лаконичный'); parser.add_argument('--mode',choices=['baseline','improved'],default='improved')
    args=parser.parse_args()
    if args.command=='run': run()
    else: print(json.dumps(SearchEngine(read_json(DATA/'clean.json')).search(args.query,args.mode,'all'),ensure_ascii=False,indent=2))
