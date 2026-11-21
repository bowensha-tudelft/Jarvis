"""Crossref: the DOI registry. Used for two things OpenAlex is bad at.

1. A misremembered citation. "Dichtel 2017 Nature beta-cyclodextrin polymer PFOA" (the paper is in
   JACS): OpenAlex title/abstract search with those words found 0; Crossref's `query.bibliographic`,
   which matches loosely across authors, title, venue and year, ranked the real paper second, behind
   its own supporting-information DOI (`.s001`, type "component"). Those are filtered out.
2. A fallback when OpenAlex's daily budget is gone. Crossref is free, needs no key and has no daily
   budget. It covers every Crossref DOI, ChemRxiv included, but not arXiv (DataCite DOIs).
   It has no abstracts for most papers and its citation counts are Crossref's own (lower).
"""
import re
import urllib.parse

from . import net

URL = 'https://api.crossref.org/works'
TTL = 7 * 86400
SELECT = 'DOI,title,author,container-title,issued,type,is-referenced-by-count,score'


def _norm(it):
    auths = ['%s %s' % (a.get('given', ''), a.get('family', '')) for a in it.get('author') or []]
    year = ((it.get('issued') or {}).get('date-parts') or [[None]])[0][0]
    return {
        'doi': (it.get('DOI') or '').lower(),
        'openalex_id': '',
        'title': ' '.join(((it.get('title') or ['?'])[0]).split()),
        'year': year,
        'authors': [a.strip() for a in auths if a.strip()],
        'venue': ((it.get('container-title') or ['']) or [''])[0] or ('preprint' if it.get('type') == 'posted-content' else ''),
        'type': it.get('type') or '',
        'cited': it.get('is-referenced-by-count') or 0,
        'oa_status': '?',
        'abstract': '',
        'score': it.get('score'),
        'from': 'crossref',
    }


def _keep(it):
    # Supporting information and other parts of a paper get their own DOIs (10.1021/x.s001).
    return it.get('type') not in ('component', 'peer-review') and not re.search(r'\.s\d{3}$', it.get('DOI') or '')


def _get(params, n):
    params = dict(params, rows=min(n * 2, 40), select=SELECT)
    d = net.request('crossref', URL + '?' + urllib.parse.urlencode(params), ttl=TTL, retries=2)
    return [_norm(it) for it in (d.get('message') or {}).get('items') or [] if _keep(it)][:n]


def match(citation, n=5):
    """Free-text citation ('Grimme 2025 g-xTB ChemRxiv') -> best candidates, best first."""
    return _get({'query.bibliographic': citation}, n)


def search(query, n=10, years=None):
    """Keyword search, for when OpenAlex cannot answer."""
    params = {'query': query}
    m = re.fullmatch(r'(\d{4})?-(\d{4})?|(\d{4})', (years or '').replace(' ', ''))
    if m:
        a, b, single = m.groups()
        a, b = (single, single) if single else (a, b)
        f = []
        if a:
            f.append('from-pub-date:%s-01-01' % a)
        if b:
            f.append('until-pub-date:%s-12-31' % b)
        params['filter'] = ','.join(f)
    return _get(params, n)
