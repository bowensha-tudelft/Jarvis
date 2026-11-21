"""Firecrawl (paper index, page reading, web search) and Tavily (web search).

Measured 2026-11:
- Firecrawl's paper index (/v2/search/research/papers) covers PubMed / PMC / arXiv / bioRxiv /
  medRxiv. It returns, per hit, the single passage that best matches the query. That passage is
  the most useful thing for checking a claim, so `find` keeps it. It keeps the query's
  constraints where OpenAlex's semantic mode drops them, and it finds papers from this year.
  It has no authors' affiliations, venues or citation counts, so hits are re-looked-up in OpenAlex.
- Firecrawl scrape reads HTML pages and PDF links into Markdown (an MDPI article: 105k chars, 4 s).
- Tavily and Firecrawl web search are different indexes with different hits: peers, not a
  primary and a fallback. Tavily adds a short generated answer.
"""
from . import net

FC = 'https://api.firecrawl.dev/v2'
TTL_SEARCH = 3 * 86400
TTL_PAGE = 30 * 86400


def _fc_headers():
    k = net.key('firecrawl')
    return {'Authorization': 'Bearer ' + k} if k else {}


def _fc_error(e):
    if e.status in (402, 403):
        return net.SourceError('firecrawl', e.status, 'credits used up (HTTP %d)' % e.status)
    return e


def paper_index(query, k=10):
    """[{doi, title, passage, score}] in the index's ranking. DOI-less hits are dropped."""
    import urllib.parse
    try:
        d = net.request('firecrawl', '%s/search/research/papers?query=%s&k=%d' % (
            FC, urllib.parse.quote(query), min(k, 50)), headers=_fc_headers(), ttl=TTL_SEARCH, timeout=60)
    except net.SourceError as e:
        raise _fc_error(e)
    out = []
    for r in d.get('results') or []:
        dois = (r.get('ids') or {}).get('doi') or []
        if dois:
            out.append({'doi': dois[0].lower(), 'title': r.get('title') or '',
                        'passage': ' '.join((r.get('passage') or '').split()), 'score': r.get('score')})
    return out


def scrape(url):
    """-> (markdown, title). Raises SourceError."""
    try:
        d = net.request('firecrawl', FC + '/scrape', method='POST', headers=_fc_headers(),
                        body={'url': url, 'formats': ['markdown'], 'timeout': 60000},
                        ttl=TTL_PAGE, timeout=90, retries=1)
    except net.SourceError as e:
        raise _fc_error(e)
    if not d or d.get('success') is False:
        raise net.SourceError('firecrawl', 200, (d or {}).get('error') or 'scrape failed')
    data = d.get('data') or {}
    return (data.get('markdown') or '').strip(), ((data.get('metadata') or {}).get('title') or '')


def firecrawl_search(query, n=5):
    try:
        d = net.request('firecrawl', FC + '/search', method='POST', headers=_fc_headers(),
                        body={'query': query, 'limit': min(n, 20), 'sources': ['web']}, ttl=TTL_SEARCH)
    except net.SourceError as e:
        raise _fc_error(e)
    return [{'url': r.get('url'), 'title': r.get('title') or '', 'snippet': r.get('description') or '',
             'engine': 'firecrawl'} for r in ((d.get('data') or {}).get('web') or [])]


def tavily_search(query, n=5, domains=None, depth='basic'):
    """-> (answer, results). Needs a key."""
    k = net.key('tavily')
    if not k:
        raise net.SourceError('tavily', 0, 'no Tavily key configured')
    body = {'query': query, 'max_results': min(n, 20), 'search_depth': depth, 'include_answer': True}
    if domains:
        body['include_domains'] = domains
    try:
        d = net.request('tavily', 'https://api.tavily.com/search', method='POST',
                        headers={'Authorization': 'Bearer ' + k}, body=body, ttl=TTL_SEARCH)
    except net.SourceError as e:
        if e.status in (432, 433, 429):
            raise net.SourceError('tavily', e.status, 'quota or rate limit reached (HTTP %d)' % e.status)
        raise
    results = [{'url': r.get('url'), 'title': r.get('title') or '', 'snippet': r.get('content') or '',
                'engine': 'tavily'} for r in d.get('results') or []]
    return (d.get('answer') or '').strip(), results
