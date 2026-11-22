"""`read`: the full text of a paper, from the cheapest reliable source that has it.

Order, cheapest and most reliable first:
1. PubMed Central via Europe PMC: free, no budget, sections already split (JATS).
2. OpenAlex's own parse of the PDF: $0.01, 0.5 s, sections split.
3. Every free copy OpenAlex knows, published version first, through Firecrawl (1 credit each).
4. A public author manuscript found by web search (manuscripts.py): NSF PAR, OSTI, university
   repositories. OpenAlex listed 8 of 10 such manuscripts as "closed, no free copy".
Which version was read is always printed: a preprint's or manuscript's wording and numbers can
differ from the published paper, and the user may quote it in a manuscript of their own.
"""
import os
import re

from . import europepmc, fmt, manuscripts, net, s2, web
from . import openalex as oa
from .commands import _not_found, notes_out

TEXTS_DIR = os.path.join(net.HOME, 'texts')
VERSION_NOTE = {
    'publishedVersion': 'published version',
    'acceptedVersion': 'accepted manuscript (peer-reviewed, before copy-editing: page layout and small edits may differ)',
    'submittedVersion': 'PREPRINT (submitted version, not peer-reviewed): wording and numbers may differ from the '
                        'published paper. Say so when quoting it',
    'pmc': 'PubMed Central copy (published version or the accepted author manuscript)',
    # Not always a manuscript: two NSF PAR files read in testing carried the publisher's layout
    # ("Cite This", "Published:"), i.e. the published version itself.
    'manuscript': 'COPY FROM A PUBLIC REPOSITORY found by web search: either the accepted manuscript or the '
                  "publisher's version (look for the journal header, \"Cite This\" or \"Published:\" at the top). "
                  'Say which it is when quoting it',
}


def _slug(s):
    return re.sub(r'[^A-Za-z0-9._-]+', '_', s)[:120]


def _long_enough(md):
    return md and len(md) >= 1500


def _from_pmc(p, notes):
    info = europepmc.lookup([p['doi']]).get(p['doi']) if p.get('doi') else None
    if not info or not info['pmcid'] or not info['in_pmc']:
        return None
    md = europepmc.fulltext(info['pmcid'])
    if _long_enough(md):
        return md, 'PubMed Central %s (via Europe PMC)' % info['pmcid'], 'pmc'
    notes.append('PMC %s gave no usable full text' % info['pmcid'])
    return None


def _from_openalex(p, notes):
    if not p.get('has_text'):
        return None
    try:
        md = oa.fulltext(p['openalex_id'])
    except net.SourceError as e:
        notes.append('OpenAlex full text failed (%s)' % e)
        return None
    if _long_enough(md):
        best = p['copies'][0] if p['copies'] else {'version': 'unknown', 'source': ''}
        return md, 'OpenAlex full text (its parse of the %s%s)' % (
            best['version'], ', ' + best['source'] if best['source'] else ''), best['version']
    notes.append('OpenAlex full text too short (%d characters)' % len(md or ''))
    return None


def _from_copies(copies, notes):
    for c in copies:
        try:
            md, _ = web.scrape(c['url'])
        except net.SourceError as e:
            notes.append('%s -> %s' % (c['url'], e))
            continue
        if _long_enough(md):
            return md, c['url'], c['version']
        notes.append('%s -> only %d characters' % (c['url'], len(md)))
    return None


def read(a):
    target = a.target.strip()
    notes = []
    if re.match(r'^https?://', target) and 'doi.org/' not in target:
        got = _from_copies([{'url': target, 'version': 'unknown', 'source': ''}], notes)
        label, slug = target, _slug(re.sub(r'^https?://', '', target))
    else:
        p = oa.work(target)
        if not p:
            return _not_found(target)
        n = s2.enrich([p])
        if n:
            notes.append(n)
        copies = list(p['copies'])
        known = {c['url'] for c in copies}
        copies += [{'url': u, 'version': 'unknown', 'source': 'Semantic Scholar'} for u in p['oa_urls'] if u not in known]
        label = '%s (%s) doi:%s' % (p['title'], p['year'], p['doi'])
        slug = _slug(p['doi'] or p['openalex_id'])
        got = None
        if not a.web:
            got = _from_pmc(p, notes) or _from_openalex(p, notes)
        got = got or _from_copies(copies, notes)
        if not got and not a.no_search:
            md, url = manuscripts.find(p['title'], notes)
            if md:
                got = md, url, 'manuscript'
        if not got:
            notes_out(notes)
            print('No readable full text for: %s' % label)
            print('OA status: %s. Use the abstract (`paper %s`), or ask the user for the PDF and read it locally.'
                  % (p['oa_status'], p['doi'] or p['openalex_id']))
            return 1
    if not got:
        notes_out(notes)
        print('Could not read: %s' % label)
        return 1
    md, used, version = got

    os.makedirs(TEXTS_DIR, exist_ok=True)
    path = os.path.join(TEXTS_DIR, slug + '.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('<!-- source: %s | version: %s -->\n%s\n' % (used, version, md))
    print('read: %s' % label)
    print('Source: %s | %d characters | saved to %s' % (used, len(md), path))
    print('Version: ' + VERSION_NOTE.get(version, 'version unknown'))
    if not re.search(r'(?im)^#+\s*.*(introduction|conclusion|results|discussion|methods|experimental)', md):
        print('Warning: no Introduction/Results/Conclusion heading found. This may be a landing page '
              'or abstract only, not the full text.')
    notes_out(notes)
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
