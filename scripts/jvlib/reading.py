"""`read`: the full text of a paper, from the cheapest reliable source that has it.

Order: OpenAlex's own parse of the PDF ($0.01, 0.5 s, sections already split, no publisher
blocking), then every free copy OpenAlex knows, published version first, through Firecrawl
(1 credit each). Which version was read is always printed: a preprint's wording and numbers
can differ from the published paper, and the user may quote it in a manuscript.
"""
import os
import re

from . import fmt, net, s2, web
from . import openalex as oa
from .commands import _not_found, notes_out

TEXTS_DIR = os.path.join(net.HOME, 'texts')
VERSION_NOTE = {
    'publishedVersion': 'published version',
    'acceptedVersion': 'accepted manuscript (peer-reviewed, before copy-editing: page layout and small edits may differ)',
    'submittedVersion': 'PREPRINT (submitted version, not peer-reviewed): wording and numbers may differ from the '
                        'published paper. Say so when quoting it',
}


def _slug(s):
    return re.sub(r'[^A-Za-z0-9._-]+', '_', s)[:120]


def _version_note(v):
    return VERSION_NOTE.get(v, 'version unknown')


def _from_openalex(p, notes):
    if not p.get('has_text'):
        return None
    try:
        md = oa.fulltext(p['openalex_id'])
    except net.SourceError as e:
        notes.append('OpenAlex full text failed (%s)' % e)
        return None
    if md and len(md) >= 1500:
        return md
    notes.append('OpenAlex full text too short (%d characters), trying the web copies' % len(md or ''))
    return None


def _from_web(copies, notes):
    for c in copies:
        try:
            md, _ = web.scrape(c['url'])
        except net.SourceError as e:
            notes.append('%s -> %s' % (c['url'], e))
            continue
        if len(md) >= 1500:
            return md, c
        notes.append('%s -> only %d characters' % (c['url'], len(md)))
    return None, None


def read(a):
    target = a.target.strip()
    notes = []
    p = None
    if re.match(r'^https?://', target) and 'doi.org/' not in target:
        copies = [{'url': target, 'version': 'unknown', 'source': ''}]
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
        if not copies and not p['has_text']:
            print('No open-access copy is known for: %s' % label)
            print('OA status: %s. Use the abstract (`paper %s`), or ask the user for the PDF and read it locally.'
                  % (p['oa_status'], p['doi'] or p['openalex_id']))
            return 1

    md = None if a.web or not p else _from_openalex(p, notes)
    if md:
        best = p['copies'][0] if p['copies'] else {'version': 'unknown', 'source': ''}
        used = 'OpenAlex full text (its parse of the %s%s)' % (best['version'], ', ' + best['source'] if best['source'] else '')
        version = best['version']
    else:
        md, c = _from_web(copies, notes)
        if not md:
            notes_out(notes)
            print('Could not read a full text for: %s' % label)
            return 1
        used, version = c['url'], c['version']

    os.makedirs(TEXTS_DIR, exist_ok=True)
    path = os.path.join(TEXTS_DIR, slug + '.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('<!-- source: %s | version: %s -->\n%s\n' % (used, version, md))
    print('read: %s' % label)
    print('Source: %s | %d characters | saved to %s' % (used, len(md), path))
    print('Version: ' + _version_note(version))
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
