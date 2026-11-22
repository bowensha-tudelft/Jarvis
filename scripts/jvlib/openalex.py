"""OpenAlex: the core for finding papers and walking citations.

Measured 2026-11 (see references/sources.md):
- `search=` searches FULL TEXT. Sorted by citations it put an unrelated photocatalysis review
  first for a cyclodextrin/PFAS query (989 hits). `title_and_abstract.search` gave 41 relevant
  hits. So keyword search uses the title/abstract filter, and full text is opt-in.
- That filter accepts AND / OR / NOT, parentheses and "quoted phrases".
- Every request costs about $0.001. Without a key, one $0.10/day budget is shared with everyone
  on the same exit IP, i.e. about 100 requests a day for a whole campus. With a key: $1/day.
- Author names are not in titles or abstracts, so a query like "g-xTB Grimme" finds 1 paper while
  `raw_author_name.search:Grimme` + "g-xTB" finds the right one. Initials hurt: "S. Grimme" 2 hits,
  "Grimme" 60, so only surnames are passed.
- OpenAlex also serves cached full texts (see fulltext()): $0.01 each, about 100 a day on a free key.
"""
import re
import urllib.parse

from . import net

BASE = 'https://api.openalex.org'
SELECT = ('id,doi,title,publication_year,authorships,primary_location,cited_by_count,'
          'type,open_access,best_oa_location,abstract_inverted_index,has_content,fwci,is_retracted,counts_by_year')
TTL_SEARCH = 3 * 86400
TTL_WORK = 30 * 86400
SORTS = {'relevance': 'relevance_score:desc', 'cited': 'cited_by_count:desc',
         'recent': 'publication_date:desc',
         # 'impact' (citations in the last two years) cannot be sorted on by OpenAlex: fetch by
         # relevance or citations, then sort_impact() reorders.
         'impact': 'relevance_score:desc'}
THIS_YEAR = __import__('datetime').date.today().year
# Data sets and "code supporting the publication" records rank high on keyword matches
# and are never what a literature search wants.
DEFAULT_EXCLUDE = ['type:!dataset', 'is_paratext:false']
# Preprint servers, for --source. `locations.source.id` also matches journal papers whose preprint
# is on the server (OpenAlex merges the two into one work).
SOURCES = {'chemrxiv': 'S4393918830', 'arxiv': 'S4306400194'}
CONTENT = 'https://content.openalex.org/works/'
TTL_TEXT = 90 * 86400


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
    # 429 has two causes. Per-second limits (semantic search: 1/s, everything: 30/s) clear in a
    # second, so retry twice with back-off. Only then ask /rate-limit (free) whether the daily
    # budget is really gone: telling the model "budget gone, stop" on a per-second limit made it
    # give up searching for nothing.
    try:
        return net.request('openalex', BASE + path, headers=_headers(), ttl=ttl, retries=2)
    except net.SourceError as e:
        if e.status != 429:
            raise
        if not net.key('openalex'):
            raise net.SourceError('openalex', 429, 'rate-limited (HTTP 429). No key is configured, so the '
                                  'daily budget is shared with everyone on this network and is probably used up. '
                                  'Do not retry OpenAlex this turn; suggest adding a key.')
        try:
            rl = net.request('openalex', BASE + '/rate-limit', headers=_headers())['rate_limit']
            left = rl.get('daily_remaining_usd', 0) + rl.get('prepaid_remaining_usd', 0)
        except (net.SourceError, KeyError, TypeError):
            rl, left = {}, None
        if left is not None and left < 0.01:
            raise net.SourceError('openalex', 429, 'daily budget used up (resets at %s UTC). Do not retry '
                                  'OpenAlex this turn.' % str(rl.get('resets_at', '?'))[:16])
        raise net.SourceError('openalex', 429, 'per-second rate limit (daily budget left: $%s). Wait a '
                              'few seconds and run the command again.' % ('?' if left is None else '%.2f' % left))


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


def surname_only(name):
    """'S. Grimme' / 'Grimme S' / 'Stefan Grimme' -> 'Grimme'. Initials cut the hits from 60 to 2."""
    words = [w for w in re.split(r'[\s,]+', name.replace('.', ' ')) if len(w) > 1]
    return words[-1] if words else name.strip()


def build_filters(years=None, type_=None, oa=False, source=None, author=None):
    f = list(DEFAULT_EXCLUDE)
    if source:
        f.append('locations.source.id:' + SOURCES[source])
    if author:
        f.append('raw_author_name.search:' + surname_only(author))
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


def recent_cites(w):
    """Citations received this year and last year: how much the paper is being used now. A 2025
    paper with 60 such citations is a current reference point; a 2025 paper with 2 is just new."""
    return sum(c.get('cited_by_count', 0) for c in w.get('counts_by_year') or [] if c.get('year', 0) >= THIS_YEAR - 1)


def sort_impact(papers):
    papers.sort(key=lambda p: (-(p.get('recent_cites') or 0), -(p.get('fwci') or 0)))
    return papers


def search(query, filters, sort='relevance', n=10, fulltext=False):
    field = 'fulltext.search' if fulltext else 'title_and_abstract.search'
    f = ['%s:%s' % (field, _clean_query(query))] + filters
    qs = 'filter=%s&per_page=%d&sort=%s&select=%s' % (
        urllib.parse.quote(','.join(f), safe=':,|!<>-'), min(n, 100), SORTS[sort], SELECT)
    d = _get('/works?' + qs, TTL_SEARCH)
    return [normalize(w) for w in d.get('results', [])], d.get('meta', {}).get('count')


# Semantic search accepts only these filters (its HTTP 400 lists them). `is_paratext`, author names
# and `locations.source.id` are not among them.
SEMANTIC_FILTERS = {'type', 'publication_year', 'is_oa', 'open_access.is_oa', 'primary_location.source.id',
                    'has_abstract', 'has_fulltext', 'language', 'is_retracted', 'primary_location.license'}


def search_semantic(query, filters, n=10):
    """OpenAlex's own semantic mode. Capped at about 50 results; it cannot be sorted; 1 call/s.
    Unsupported filters are translated or applied afterwards, never silently dropped."""
    f, author = [], None
    for x in filters:
        k, _, v = x.partition(':')
        if k in SEMANTIC_FILTERS:
            f.append(x)
        elif k == 'locations.source.id':
            f.append('primary_location.source.id:' + v)     # preprint-only works; merged ones are missed
        elif k == 'raw_author_name.search':
            author = v.lower()
    qs = 'search.semantic=%s&per_page=%d&select=%s' % (urllib.parse.quote(query), min(n * (3 if author else 1), 50), SELECT)
    if f:
        qs += '&filter=' + urllib.parse.quote(','.join(f), safe=':,|!<>-')
    d = _get('/works?' + qs, TTL_SEARCH)
    rows = [normalize(w) for w in d.get('results', [])]
    if author:
        rows = [p for p in rows if any(author in a.lower() for a in p['authors'])]
    return rows[:n]


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
    sel = SELECT + ',referenced_works,related_works,topics,biblio,locations'
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
    p['copies'] = oa_copies(w)
    return p


VERSION_RANK = {'publishedVersion': 0, 'acceptedVersion': 1, 'submittedVersion': 2}


def oa_copies(w):
    """Every free copy OpenAlex knows of, published version first: [{url, version, source}].
    Measured: 17 of 50 open-access PFAS papers had more than one, 30 had a repository copy."""
    out, seen = [], set()
    locs = sorted((l for l in w.get('locations') or [] if l.get('is_oa')),
                  key=lambda l: VERSION_RANK.get(l.get('version'), 3))
    for l in locs:
        for u in (l.get('pdf_url'), l.get('landing_page_url')):
            if u and u not in seen:
                seen.add(u)
                out.append({'url': u, 'version': l.get('version') or 'unknown',
                            'source': (l.get('source') or {}).get('display_name') or ''})
    return out


def fulltext(openalex_id):
    """OpenAlex's own parse of the PDF (GROBID TEI XML), as Markdown. None if it has none.
    $0.01 per download, so it is cached for 90 days."""
    from . import tei
    try:
        xml = net.request('openalex', CONTENT + openalex_id + '.grobid-xml', headers=_headers(),
                          ttl=TTL_TEXT, raw=True, timeout=90)
    except net.SourceError as e:
        if e.status == 404:
            return None
        raise
    return tei.to_markdown(xml) or None


def by_ids(ids, filters=()):
    """Full records for OpenAlex ids (50 per request), in the order given."""
    out = {}
    for i in range(0, len(ids), 50):
        f = ['openalex_id:' + '|'.join(ids[i:i + 50])] + list(filters)
        d = _get('/works?filter=%s&per_page=50&select=%s' % (urllib.parse.quote(','.join(f), safe=':,|!<>-'), SELECT), TTL_WORK)
        for w in d.get('results', []):
            out[short_id(w['id'])] = normalize(w)
    return [out[i] for i in ids if i in out]


def citations(seed, direction, filters, sort='cited', n=15):
    """Snowballing from one full record (from `work`). Returns (papers, total)."""
    if direction == 'citers':
        f = ['cites:' + seed['openalex_id']] + filters
        per = min(n * 3, 100) if sort == 'impact' else min(n, 100)
        d = _get('/works?filter=%s&per_page=%d&sort=%s&select=%s' % (
            urllib.parse.quote(','.join(f), safe=':,|!<>-'), per,
            SORTS['cited' if sort == 'impact' else sort], SELECT), TTL_SEARCH)
        rows = [normalize(w) for w in d.get('results', [])]
        if sort == 'impact':
            rows = sort_impact(rows)[:n]
        return rows, d.get('meta', {}).get('count')
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
        if sort == 'impact':
            sort_impact(papers)
        else:
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
        'has_text': bool((w.get('has_content') or {}).get('grobid_xml')),
        'fwci': w.get('fwci'),
        'recent_cites': recent_cites(w),
        'retracted': bool(w.get('is_retracted')),
        'oa_urls': [u for u in (best.get('pdf_url'), best.get('landing_page_url'), oa.get('oa_url')) if u],
    }
