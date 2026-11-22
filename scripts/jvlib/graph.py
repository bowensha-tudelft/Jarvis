"""`expand`: papers linked to several seed papers at once, through the citation graph.

Keyword and web search find what you can name. A blind review found both a web-search list and a
Jarvis list for one project missing the same recent papers, each of which cites several of the
project's core papers. A paper that cites three of your seeds, or that three of your seeds cite,
is almost certainly relevant, whatever words it uses. Two lists come back:
- later work: papers citing at least two seeds (the frontier built on them);
- shared foundations: papers at least two seeds cite.
Both are ranked by how many seeds they link to, then by citations in the last two years.

Later work is found by asking OpenAlex for papers that cite both seeds of each pair
(`cites:A,cites:B`), not by scanning each seed's citers. The first version scanned the 400 most
cited citers of each seed: for a seed with 1,865 citers it found no later work at all, because the
papers citing several seeds are recent and not yet highly cited.
"""
import itertools
import urllib.parse
from collections import defaultdict

from . import openalex as oa

LABELS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
MAX_SEEDS = 8          # 28 pair queries


def _citing_pair(a, b, filters):
    f = ','.join(['cites:' + a, 'cites:' + b] + list(filters))
    d = oa._get('/works?filter=%s&per_page=200&sort=cited_by_count:desc&select=%s' % (
        urllib.parse.quote(f, safe=':,|!<>-'), oa.SELECT + ',referenced_works'), oa.TTL_SEARCH)
    return d.get('results', []), (d.get('meta') or {}).get('count', 0)


def expand(seed_ids, filters=(), n=25, min_links=2):
    seeds = []
    for s in seed_ids[:MAX_SEEDS]:
        w = oa.work(s)
        if w is None:
            raise LookupError(s)
        seeds.append(w)
    sid = [w['openalex_id'] for w in seeds]
    seed_set = set(sid)

    # later work: union of pairwise intersections; link count from each paper's own references
    later, truncated = {}, False
    for i, j in itertools.combinations(range(len(seeds)), 2):
        rows, total = _citing_pair(sid[i], sid[j], filters)
        truncated |= total > len(rows)
        for w in rows:
            wid = oa.short_id(w['id'])
            if wid in seed_set or wid in later:
                continue
            refs = {oa.short_id(r) for r in w.get('referenced_works') or []}
            p = oa.normalize(w)
            p['links'] = [k for k, s in enumerate(sid) if s in refs]
            if len(p['links']) >= min_links:
                later[wid] = p

    # shared foundations: references the seeds have in common
    cited = defaultdict(set)
    for k, w in enumerate(seeds):
        for rid in w['refs']:
            cited[rid].add(k)
    common = [(rid, s) for rid, s in cited.items() if rid not in seed_set and len(s) >= min_links]
    common.sort(key=lambda x: -len(x[1]))
    keep = dict(common[:max(n * 3, 60)])
    shared = oa.by_ids(list(keep))
    for p in shared:
        p['links'] = sorted(keep[p['openalex_id']])

    def rank(ps):
        return sorted(ps, key=lambda p: (-len(p['links']), -(p.get('recent_cites') or 0), -(p.get('fwci') or 0)))

    return seeds, (rank(later.values())[:n], len(later), truncated), (rank(shared)[:n], len(common))


def link_line(p, seeds):
    return 'links %d of %d seeds: %s' % (len(p['links']), len(seeds),
                                         ', '.join('%s %s %s' % (LABELS[i], (seeds[i]['authors'] or ['?'])[0].split()[-1],
                                                                 seeds[i]['year']) for i in p['links']))
