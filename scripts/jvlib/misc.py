"""web, bib and status."""
import os

from . import bib, crossref, fmt, net, s2, web
from . import openalex as oa
from .commands import notes_out
from .reading import TEXTS_DIR


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
    notes_out(notes)
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


def _check_s2():
    # enrich() reports failure as a returned note rather than raising, because inside `find` a
    # failed TLDR lookup must not sink the results. Here a failure must be a failure.
    p = {'doi': '10.1039/d0cs00620c'}
    note = s2.enrich([p])
    if note:
        raise net.SourceError('s2', 0, note)
    return 'TLDR: ' + (p.get('tldr') or '(none)')[:80]


def _summary(r):
    s = r if isinstance(r, str) else ' '.join(str(r).split())
    return s[:220]


def status(a):
    print('Config: %s' % net.CONFIG_PATH)
    for s in ('openalex', 's2', 'tavily', 'firecrawl'):
        k = net.key(s)
        print('  %-10s %s' % (s, 'key set (...%s)' % k[-4:] if k else 'no key'))
    print('  %-10s free, no key' % 'crossref')
    n, size = net.cache_size()
    print('Cache: %s (%d files, %.1f MB). Saved full texts: %s' % (net.CACHE_DIR, n, size / 1e6, TEXTS_DIR))
    if not a.check:
        return 0
    # A cached answer would say a key works after it has been revoked: always ask the services.
    net.FRESH = True
    print('\nChecking each source (one small live request each):')
    checks = [
        ('openalex', lambda: oa._get('/rate-limit' if net.key('openalex') else '/works?filter=doi:10.1039/d0cs00620c&select=id', 0)),
        ('s2', _check_s2),
        ('firecrawl', lambda: net.request('firecrawl', web.FC + '/team/credit-usage', headers=web._fc_headers())
         if net.key('firecrawl') else web.paper_index('cyclodextrin', 1)),
        ('tavily', lambda: web.tavily_search('OpenAlex API', 1)),
        ('crossref', lambda: crossref.match('Grimme GFN2-xTB tight-binding 2019', 1)[0]['title']),
    ]
    code = 0
    for name, fn in checks:
        try:
            print('  %-10s ok %s' % (name, _summary(fn())))
        except (net.SourceError, IndexError) as e:
            print('  %-10s FAILED %s' % (name, e))
            code = 1
    return code
