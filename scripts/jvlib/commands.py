"""The six commands. Each prints compact text for the model and returns an exit code.

One source failing never sinks a command that has other sources: the failure becomes a
`Note:` line and the rest is printed. Only when nothing at all came back is the exit code 1.
"""
import os
import re

from . import bib, fmt, net, s2, web
from . import openalex as oa

TEXTS_DIR = os.path.join(net.HOME, 'texts')
NEXT = ('Next: `paper <doi>` for the abstract, `cite <doi>` to snowball, '
        '`read <doi> --find "<terms>"` to check the full text, `bib <doi> ...` for BibTeX.')


def _notes(notes):
    for n in notes:
        print('Note: ' + n)


def _semantic(query, filters, n, notes):
    """Firecrawl's paper index first (keeps constraints, carries a matching passage), looked up in
    OpenAlex so the record has venue and citations. OpenAlex's own semantic mode if that is empty."""
    try:
        hits = web.paper_index(query, k=max(n * 2, 10))
        if hits:
            found = oa.by_dois([h['doi'] for h in hits], filters)
            rows = []
            for h in hits:
                p = found.get(oa.norm_doi(h['doi']))
                if p:
                    p['passage'] = h['passage']
                    rows.append(p)
            if rows:
                left = len(hits) - len(rows)
                return rows, 'paper index %d hits%s' % (
                    len(hits), ', %d dropped by filters or missing in OpenAlex' % left if left else '')
    except net.SourceError as e:
        notes.append('Firecrawl paper index failed (%s); used OpenAlex semantic search instead' % e)
    try:
        rows = oa.search_semantic(query, filters, n)
        return rows, 'OpenAlex semantic %d hits (capped near 50, not exhaustive)' % len(rows)
    except net.SourceError as e:
        notes.append(str(e))
        return [], 'semantic failed'


def find(a):
    filters = oa.build_filters(a.years, a.type, a.oa)
    notes, lists, parts = [], [], []
    if a.mode in ('auto', 'keyword'):
        try:
            rows, total = oa.search(a.query, filters, a.sort, a.n, fulltext=a.fulltext)
            lists.append(rows)
            parts.append('keyword (%s) %s total' % ('full text' if a.fulltext else 'title+abstract', total))
        except net.SourceError as e:
            notes.append(str(e))
    if a.mode in ('auto', 'semantic'):
        rows, desc = _semantic(a.query, filters, a.n, notes)
        lists.append(rows)
        parts.append(desc)
    merged = fmt.merge(*lists)
    if a.sort == 'cited':
        merged.sort(key=lambda p: -p['cited'])
    elif a.sort == 'recent':
        merged.sort(key=lambda p: -(p['year'] or 0))
    merged = merged[:a.n]
    if not merged:
        _notes(notes)
        print('No papers found for: %s' % a.query)
        return 1 if notes else 0
    if not a.no_tldr:
        n = s2.enrich(merged)
        if n:
            notes.append(n)
    print('find "%s" | %s | showing %d, sort=%s%s' % (
        a.query, '; '.join(parts), len(merged), a.sort,
        ' | found by both keyword and semantic search are listed first' if a.mode == 'auto' and a.sort == 'relevance' else ''))
    _notes(notes)
    print()
    print(fmt.papers(merged, 900 if a.abstract else 0))
    print('\n' + NEXT)
    return 0


def cite(a):
    seed = oa.work(a.id)
    if not seed:
        print('Not found in OpenAlex: %s. Find it first with `find`, then use its DOI.' % a.id)
        return 1
    filters = oa.build_filters(a.years, a.type, False)
    rows, total = oa.citations(seed, a.dir, filters, a.sort, a.n)
    label = {'citers': 'papers citing it', 'refs': 'its references', 'related': 'related papers'}[a.dir]
    print('cite: %s (%s) -> %s: %s in total, showing %d' % (
        seed['title'], seed['year'], label, total if total is not None else '?', len(rows)))
    if a.dir == 'related':
        print('(related = OpenAlex\'s relatedness order, not citations)')
    if not rows:
        return 0
    note = None if a.no_tldr else s2.enrich(rows)
    if note:
        print('Note: ' + note)
    print()
    print(fmt.papers(rows, 900 if a.abstract else 0))
    return 0


def paper(a):
    code = 0
    for i, ident in enumerate(a.ids):
        p = oa.work(ident)
        if not p:
            print('Not found in OpenAlex: %s' % ident)
            code = 1
            continue
        note = s2.enrich([p])
        if i:
            print('\n' + '=' * 60)
        print(p['title'])
        names = p['authors']
        print('Authors: ' + ', '.join(names[:12]) + (' ... (%d authors)' % len(names) if len(names) > 12 else ''))
        bib_ = ', '.join('%s %s' % (k, v) for k, v in p.get('biblio', {}).items())
        print('Venue: %s, %s%s | type: %s' % (p['venue'] or '?', p['year'], (' | ' + bib_) if bib_ else '', p['type']))
        print('doi:%s | openalex:%s' % (p['doi'] or '-', p['openalex_id']))
        infl = ' (influential %s)' % p['influential'] if p.get('influential') is not None else ''
        print('Cited by %d%s | references %d | topics: %s' % (p['cited'], infl, len(p['refs']), '; '.join(p['topics']) or '-'))
        print('Open access: %s%s' % (p['oa_status'], (' -> ' + ' , '.join(dict.fromkeys(p['oa_urls']))) if p['oa_urls'] else ''))
        if note:
            print('Note: ' + note)
        if p.get('tldr'):
            print('TLDR: ' + p['tldr'])
        print('Abstract: ' + (p['abstract'] or '(OpenAlex has no abstract for this paper)'))
    return code


def _slug(s):
    return re.sub(r'[^A-Za-z0-9._-]+', '_', s)[:120]


def read(a):
    target = a.target.strip()
    notes = []
    if re.match(r'^https?://', target) and 'doi.org/' not in target:
        urls, label, slug = [target], target, _slug(re.sub(r'^https?://', '', target))
    else:
        p = oa.work(target)
        if not p:
            print('Not found in OpenAlex: %s' % target)
            return 1
        n = s2.enrich([p])
        if n:
            notes.append(n)
        urls = list(dict.fromkeys(p['oa_urls']))
        label = '%s (%s) doi:%s' % (p['title'], p['year'], p['doi'])
        slug = _slug(p['doi'] or p['openalex_id'])
        if not urls:
            print('No open-access copy is known for: %s' % label)
            print('OA status: %s. Use the abstract (`paper %s`), or ask the user for the PDF and read it locally.'
                  % (p['oa_status'], p['doi'] or p['openalex_id']))
            return 1
    md, title, used = '', '', None
    for u in urls:
        try:
            md, title = web.scrape(u)
        except net.SourceError as e:
            notes.append('%s -> %s' % (u, e))
            continue
        if len(md) >= 1500:
            used = u
            break
        notes.append('%s -> only %d characters' % (u, len(md)))
    if not used:
        _notes(notes)
        print('Could not read a full text for: %s' % label)
        return 1
    os.makedirs(TEXTS_DIR, exist_ok=True)
    path = os.path.join(TEXTS_DIR, slug + '.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('<!-- source: %s -->\n%s\n' % (used, md))
    print('read: %s' % label)
    print('Source: %s | %d characters | full text saved to %s' % (used, len(md), path))
    if not re.search(r'(?im)^#+\s*.*(introduction|conclusion|results|discussion|methods)', md):
        print('Warning: no Introduction/Results/Conclusion heading found. This may be a landing page '
              'or abstract only, not the full text.')
    _notes(notes)
    print(fmt.BANNER)
    if a.find:
        terms = [t.strip() for f in a.find for t in f.split(';') if t.strip()]
        found, total = fmt.find_passages(md, terms, k=a.k)
        print('%d paragraphs match %s; showing %d.\n' % (total, terms, len(found)))
        print('\n\n'.join(found) if found else '(no paragraph matches; try other words or read the saved file)')
    else:
        print('--- text start ---')
        print(md[:a.max] + ('\n...[cut at %d of %d characters; the full text is in the saved file]' % (a.max, len(md))
                            if len(md) > a.max else ''))
        print('--- text end ---')
    return 0


def web_search(a):
    domains = [d.strip() for d in (a.domains or '').split(',') if d.strip()]
    eng = a.engine
    if eng == 'auto':
        eng = 'both' if net.key('tavily') else 'firecrawl'
    notes, answer, lists = [], '', []
    if eng in ('tavily', 'both'):
        try:
            answer, rows = web.tavily_search(a.query, a.n, domains, 'advanced' if a.deep else 'basic')
            lists.append(rows)
        except net.SourceError as e:
            notes.append(str(e))
    if eng in ('firecrawl', 'both'):
        q = a.query + ''.join(' site:' + d for d in domains[:1])
        try:
            lists.append(web.firecrawl_search(q, a.n))
        except net.SourceError as e:
            notes.append(str(e))
    seen, rows = set(), []
    for i in range(max((len(l) for l in lists), default=0)):
        for l in lists:
            if i < len(l) and l[i]['url'] not in seen:
                seen.add(l[i]['url'])
                rows.append(l[i])
    print('web "%s" | engines: %s | %d results' % (a.query, eng, len(rows)))
    _notes(notes)
    if not rows:
        return 1 if notes else 0
    print(fmt.BANNER)
    if answer:
        print('Tavily generated summary (unverified, check against the sources): ' + answer)
    for i, r in enumerate(rows, 1):
        print('\n[%d] %s (%s)\n    %s\n    %s' % (i, r['title'], r['engine'], r['url'], fmt.clip(r['snippet'], 400)))
    return 0


def bibtex(a):
    entries, code = [], 0
    for d in a.dois:
        try:
            entries.append((oa.norm_doi(d), bib.fetch(d)))
        except net.SourceError as e:
            print('% ' + str(e))
            code = 1
    if a.out:
        added, skipped = bib.append(a.out, entries)
        print('%% %s: added %d, already there %d' % (os.path.abspath(a.out), added, skipped))
    print('\n\n'.join(b for _, b in entries))
    return code


def status(a):
    print('Config: %s' % net.CONFIG_PATH)
    for s in ('openalex', 's2', 'tavily', 'firecrawl'):
        k = net.key(s)
        print('  %-10s %s' % (s, 'key set (...%s)' % k[-4:] if k else 'no key'))
    n, size = net.cache_size()
    print('Cache: %s (%d files, %.1f MB). Saved full texts: %s' % (net.CACHE_DIR, n, size / 1e6, TEXTS_DIR))
    if not a.check:
        return 0
    print('\nChecking each source (one small request each):')
    checks = [
        ('openalex', lambda: oa._get('/rate-limit' if net.key('openalex') else '/works?filter=doi:10.1039/d0cs00620c&select=id', 0)),
        ('s2', lambda: s2.enrich([{'doi': '10.1039/d0cs00620c'}]) or 'ok'),
        ('firecrawl', lambda: net.request('firecrawl', web.FC + '/team/credit-usage', headers=web._fc_headers())
         if net.key('firecrawl') else web.paper_index('cyclodextrin', 1)),
        ('tavily', lambda: web.tavily_search('OpenAlex API', 1)),
    ]
    code = 0
    for name, fn in checks:
        try:
            r = fn()
            print('  %-10s ok %s' % (name, _summary(r)))
        except net.SourceError as e:
            print('  %-10s FAILED %s' % (name, e))
            code = 1
    return code


def _summary(r):
    if isinstance(r, str):
        return '' if r == 'ok' else r[:150]
    s = ' '.join(str(r).split())
    return s[:220]
