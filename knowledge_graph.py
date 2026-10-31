"""Graphify integration over existing notes; never invokes another LLM."""
import hashlib
import importlib.metadata
import re
import unicodedata

MAX_NOTES = 100

def normalize(value):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', value).strip()).casefold()

def identifier(kind, value):
    return kind + '_' + hashlib.sha256(value.encode()).hexdigest()[:24]

def build_graph(notes):
    if not isinstance(notes, list) or len(notes) > MAX_NOTES:
        raise ValueError('Build a graph from at most 100 notes at a time.')
    from graphify.build import build_from_json
    from graphify.validate import assert_valid
    nodes, edges, seen, members = [], [], set(), {}
    def node(n):
        if n['id'] not in seen:
            seen.add(n['id']); nodes.append(n)
    for note in notes:
        if not isinstance(note, dict) or not isinstance(note.get('id'), str) or not isinstance(note.get('title'), str):
            raise ValueError('Every note needs an ID and title.')
        note_id = note['id'][:150]
        nid = identifier('note', note_id)
        file = 'notes/' + nid + '.md'
        node({'id':nid,'label':note['title'][:256],'type':'note','file_type':'document','source_file':file,'source_location':None,'note_id':note_id,'url':str(note.get('url',''))[:2000],'_origin':'semantic'})
        for field, limit, kind in [('tags',20,'topic'),('concepts',12,'concept'),('framework',8,'strategy')]:
            values = note.get(field, [])
            if not isinstance(values, list): raise ValueError('Invalid note field: '+field)
            for index, value in enumerate(values[:limit]):
                if not isinstance(value, str) or not value.strip(): continue
                # Do not merge long explanations by truncated labels.
                value = value.strip()[:4000]
                uid = identifier(kind, normalize(value))
                node({'id':uid,'label':value[:256],'detail':value,'type':kind,'file_type':'concept','source_file':'concepts/'+uid+'.md','source_location':None,'_origin':'semantic'})
                edges.append({'source':nid,'target':uid,'relation':'contains_'+kind,'confidence':'EXTRACTED','evidence_scope':'saved_note_structure','source_note_id':note_id,'source_field':field,'source_index':index})
                if kind in ('topic','concept'): members.setdefault(uid,set()).add(nid)
    linked = set()
    for uid, ids in sorted(members.items()):
        ids = sorted(ids)
        for i, left in enumerate(ids):
            for right in ids[i+1:]:
                if len(linked) >= 500: break
                if (left,right) in linked: continue
                linked.add((left,right))
                edges.append({'source':left,'target':right,'relation':'potentially_related','confidence':'INFERRED','via':uid,'evidence_scope':'shared_exact_topic_or_concept','explanation':'Both saved notes contain the same normalized topic or concept. This does not establish causality or agreement.'})
    extraction={'nodes':nodes,'edges':edges}
    assert_valid(extraction)
    graph=build_from_json(extraction,directed=True,dedup=False)
    output_nodes=[{'id':str(k),**v} for k,v in graph.nodes(data=True)]
    output_edges=[{'source':str(a),'target':str(b),**data} for a,b,data in graph.edges(data=True)]
    return {'schema_version':'postwise-graph-1','engine':'Graphify','graphify_version':importlib.metadata.version('graphifyy'),'nodes':output_nodes,'edges':output_edges,'note_count':len(notes),'notice':'EXTRACTED means explicitly present in a saved note, not independently verified in the original post. Related-note links are inferred from exact shared topics/concepts; synonyms are not merged automatically.'}

def query_graph(graph, query='', start=None, end=None):
    import networkx as nx
    nodes=graph.get('nodes',[]); edges=graph.get('edges',[])
    if not isinstance(nodes,list) or not isinstance(edges,list) or len(nodes)>5000 or len(edges)>10000:
        raise ValueError('Invalid or oversized graph.')
    by_id={n['id']:n for n in nodes if isinstance(n,dict) and isinstance(n.get('id'),str)}
    if start is not None or end is not None:
        if start not in by_id or end not in by_id: raise ValueError('Choose two graph nodes.')
        g=nx.Graph();g.add_nodes_from(by_id)
        for edge in edges:
            if edge.get('source') in by_id and edge.get('target') in by_id: g.add_edge(edge['source'],edge['target'])
        try: path=nx.shortest_path(g,start,end)
        except nx.NetworkXNoPath: return {'nodes':[],'edges':[],'notice':'No connecting path found.'}
        pairs={frozenset((a,b)) for a,b in zip(path,path[1:])}
        return {'nodes':[by_id[k] for k in path],'edges':[e for e in edges if frozenset((e['source'],e['target'])) in pairs],'notice':'An undirected connection path, not proof of a causal relationship.'}
    term=normalize(str(query))
    if len(term)>500: raise ValueError('Search query too long.')
    selected={k for k,v in by_id.items() if term in normalize(str(v.get('label',''))+' '+str(v.get('detail','')))} if term else set(by_id)
    selected=set(sorted(selected)[:50])
    links=[e for e in edges if e.get('source') in selected or e.get('target') in selected][:200]
    ids=selected|{e['source'] for e in links}|{e['target'] for e in links}
    return {'nodes':[by_id[k] for k in sorted(ids) if k in by_id],'edges':links,'notice':'Search matches with their immediate connections. Up to 50 matches and 200 edges.'}
