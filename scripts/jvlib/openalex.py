"""OpenAlex: the core for finding papers and walking citations.

Measured 2026-11 (see references/sources.md):
- `search=` searches FULL TEXT. Sorted by citations it put an unrelated photocatalysis review
  first for a cyclodextrin/PFAS query (989 hits). `title_and_abstract.search` gave 41 relevant
  hits. So keyword search uses the title/abstract filter, and full text is opt-in.
- That filter accepts AND / OR / NOT, parentheses and "quoted phrases".
- Every request costs about $0.001. Without a key, one $0.10/day budget is shared with everyone
  on the same exit IP, i.e. about 100 requests a day for a whole campus. With a key: $1/day.
"""
import re
import urllib.parse

from . import net

BASE = 'https://api.openalex.org'
SELECT = ('id,doi,title,publication_year,authorships,primary_location,cited_by_count,'
          'type,open_access,best_oa_location,abstract_inverted_index')
TTL_SEARCH = 3 * 86400
TTL_WORK = 30 * 86400
SORTS = {'relevance': 'relevance_score:desc', 'cited': 'cited_by_count:desc',
         'recent': 'publication_date:desc'}
# Data sets and "code supporting the publication" records rank high on keyword matches
# and are never what a literature search wants.
DEFAULT_EXCLUDE = ['type:!dataset', 'is_paratext:false']


def norm_doi(s):
    s = (s or '').strip()
    s = re.sub(r'^(https?://(dx\.)?doi\.org/|doi:\s*)', '', s, flags=re.I)
    return s.lower()


def looks_like_doi(s):
    return bool(re.match(r'^10\.\d{4,9}/\S+$', norm_doi(s)))


def _headers():
    k = net.key('openalex')
    return {'Authorization': 'Bearer ' + k} if k else {}


def _get(path, ttl):
    try:
        return net.request('openalex', BASE + path, headers=_headers(), ttl=ttl)
    except net.SourceError as e:
        if e.status == 429:
            raise net.SourceError('openalex', 429, 'rate-limited (HTTP 429): the daily budget is used up. '
                                  'Do not retry OpenAlex this turn. '
                                  + ('' if net.key('openalex') else 'No key is configured, so the budget is shared with the whole network. '))
        raise


def year_filter(spec):
    """'2020-2025' | '2020-' | '-2015' | '2023' -> an OpenAlex filter string."""
    spec = (spec or '').replace(' ', '')
    if not spec:
        return None
    m = re.fullmatch(r'(\d{4})?-(\d{4})?', spec)
    if m:
        a, b = m.groups()
        if a and b:
            return 'publication_year:%s-%s' % (a, b)
        if a:
            return 'publication_year:>%d' % (int(a) - 1)
        if b:
            return 'publication_year:<%d' % (int(b) + 1)
    if re.fullmatch(r'\d{4}', spec):
        return 'publication_year:' + spec
    raise SystemExit('Bad --years "%s". Use 2020-2025, 2020-, -2015 or 2023.' % spec)


def build_filters(years=None, type_=None, oa=False):
    f = list(DEFAULT_EXCLUDE)
    y = year_filter(years)
    if y:
        f.append(y)
    if type_:
        f.append('type:' + type_)
    if oa:
        f.append('is_oa:true')
    return f


def _clean_query(q):
    # A comma separates filters in OpenAlex syntax, so it must not appear inside one.
    return ' '.join(q.replace(',', ' ').split())


def search(query, filters, sort='relevance', n=10, fulltext=False):
    field = 'fulltext.search' if fulltext else 'title_and_abstract.search'
    f = ['%s:%s' % (field, _clean_query(query))] + filters
    qs = 'filter=%s&per_page=%d&sort=%s&select=%s' % (
        urllib.parse.quote(','.join(f), safe=':,|!<>-'), min(n, 100), SORTS[sort], SELECT)
    d = _get('/works?' + qs, TTL_SEARCH)
    return [normalize(w) for w in d.get('results', [])], d.get('meta', {}).get('count')


def search_semantic(query, filters, n=10):
    """OpenAlex's own semantic mode. Capped at about 50 results; it cannot be sorted."""
    qs = 'search.semantic=%s&filter=%s&per_page=%d&select=%s' % (
        urllib.parse.quote(query), urllib.parse.quote(','.join(filters), safe=':,|!<>-'), min(n, 50), SELECT)
    d = _get('/works?' + qs, TTL_SEARCH)
    return [normalize(w) for w in d.get('results', [])]


def by_dois(dois, filters=()):
    """Look up many DOIs at once. Returns {doi: paper}; DOIs OpenAlex lacks are absent."""
    out = {}
    dois = [norm_doi(d) for d in dois if d]
    for i in range(0, len(dois), 50):
        chunk = dois[i:i + 50]
        f = ['doi:' + '|'.join(chunk)] + list(filters)
        d = _get('/works?filter=%s&per_page=50&select=%s' % (
            urllib.parse.quote(','.join(f), safe=':,|!<>-/'), SELECT), TTL_WORK)
        for w in d.get('results', []):
            p = normalize(w)
            if p['doi']:
                out[p['doi']] = p
    return out


def work(ident):
    """A DOI, a doi.org URL, an OpenAlex id (W123...) or a title -> one full record."""
    sel = SELECT + ',referenced_works,related_works,topics,biblio'
    ident = ident.strip()
    if looks_like_doi(ident):
        path = '/works/doi:' + urllib.parse.quote(norm_doi(ident), safe='/')
    elif re.fullmatch(r'(https://openalex\.org/)?W\d+', ident, flags=re.I):
        path = '/works/' + ident.rsplit('/', 1)[-1].upper()
    else:
        d = _get('/works?filter=title.search:%s&per_page=1&select=id' % urllib.parse.quote(_clean_query(ident)), TTL_WORK)
        if not d.get('results'):
            return None
        path = '/works/' + d['results'][0]['id'].rsplit('/', 1)[-1]
    try:
        w = _get(path + '?select=' + sel, TTL_WORK)
    except net.SourceError as e:
        if e.status == 404:
            return None
        raise
    p = normalize(w)
    p['refs'] = [short_id(u) for u in w.get('referenced_works') or []]
    p['related'] = [short_id(u) for u in w.get('related_works') or []]
    p['topics'] = [t.get('display_name') for t in (w.get('topics') or [])[:3]]
    b = w.get('biblio') or {}
    p['biblio'] = {k: b.get(k) for k in ('volume', 'issue', 'first_page', 'last_page') if b.get(k)}
    return p


def citations(seed, direction, filters, sort='cited', n=15):
    """Snowballing from one full record (from `work`). Returns (papers, total)."""
    if direction == 'citers':
        f = ['cites:' + seed['openalex_id']] + filters
        d = _get('/works?filter=%s&per_page=%d&sort=%s&select=%s' % (
            urllib.parse.quote(','.join(f), safe=':,|!<>-'), min(n, 100), SORTS[sort], SELECT), TTL_SEARCH)
        return [normalize(w) for w in d.get('results', [])], d.get('meta', {}).get('count')
    ids = seed['refs'] if direction == 'refs' else seed['related']
    if not ids:
        return [], 0
    papers = []
    for i in range(0, len(ids), 50):
        f = ['openalex_id:' + '|'.join(ids[i:i + 50])] + filters
        d = _get('/works?filter=%s&per_page=50&select=%s' % (
            urllib.parse.quote(','.join(f), safe=':,|!<>-'), SELECT), TTL_WORK)
        papers += [normalize(w) for w in d.get('results', [])]
    if direction == 'refs':
        # Most-cited references first: the foundational papers come out on top.
        key = (lambda p: p['year'] or 0) if sort == 'recent' else (lambda p: p['cited'])
        papers.sort(key=key, reverse=True)
    else:
        # Keep OpenAlex's relatedness order; sorting by citations would swap "related" for "famous".
        order = {x: i for i, x in enumerate(ids)}
        papers.sort(key=lambda p: order.get(p['openalex_id'], 0))
    return papers[:n], len(ids)


def short_id(u):
    return (u or '').rsplit('/', 1)[-1]


def abstract_text(inv):
    if not inv:
        return ''
    pos = {}
    for word, idxs in inv.items():
        for i in idxs:
            pos[i] = word
    text = ' '.join(pos[i] for i in sorted(pos))
    # ACS abstracts arrive with the graphical-abstract caption glued to the front.
    return re.sub(r'^(High Resolution Image )?Download (MS )?PowerPoint Slide\s*', '', text)


def normalize(w):
    loc = w.get('primary_location') or {}
    src = loc.get('source') or {}
    oa = w.get('open_access') or {}
    best = w.get('best_oa_location') or {}
    auths = [((a.get('author') or {}).get('display_name') or '?') for a in w.get('authorships') or []]
    return {
        'doi': norm_doi(w.get('doi')),
        'openalex_id': short_id(w.get('id')),
        'title': ' '.join((w.get('title') or '?').split()),
        'year': w.get('publication_year'),
        'authors': auths,
        'venue': src.get('display_name') or '',
        'type': w.get('type') or '',
        'cited': w.get('cited_by_count') or 0,
        'oa_status': oa.get('oa_status') or 'closed',
        'abstract': abstract_text(w.get('abstract_inverted_index')),
        'oa_urls': [u for u in (best.get('pdf_url'), best.get('landing_page_url'), oa.get('oa_url')) if u],
    }
