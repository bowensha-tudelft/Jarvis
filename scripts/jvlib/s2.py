"""Semantic Scholar: enrichment only, never discovery.

Measured: anonymous /paper/search returned HTTP 429 eight times out of eight, so it is not
used. The batch endpoint answers one POST for up to 500 papers and works without a key,
which makes it cheap to add a one-sentence TLDR and the influential-citation count to a
whole result list. It answers 429 at random, with or without a key and at 0.5 s or 3 s spacing
(measured 2026-11), so it is retried with jittered back-off and a failure only drops the TLDRs. Citation contexts and intents came back empty for 0/25 papers, so they
are not requested.
"""
from . import net

URL = 'https://api.semanticscholar.org/graph/v1/paper/batch?fields=tldr,influentialCitationCount,openAccessPdf'
TTL = 14 * 86400


def enrich(papers):
    """Adds 'tldr', 'influential' and S2's open-access PDF to papers in place.
    Returns None, or a one-line note when the enrichment failed (results are still usable)."""
    todo = [p for p in papers if p.get('doi') and 'tldr' not in p]
    if not todo:
        return None
    k = net.key('s2')
    headers = {'x-api-key': k} if k else {}
    try:
        rows = []
        for i in range(0, len(todo), 500):
            chunk = todo[i:i + 500]
            try:
                rows += net.request('s2', URL, method='POST', headers=headers, ttl=TTL, retries=5,
                                    body={'ids': ['DOI:' + p['doi'] for p in chunk]})
            except net.SourceError as e:
                # A batch in which S2 knows none of the papers is answered with HTTP 400
                # "No valid paper ids given" (e.g. a single ChemRxiv preprint), not with nulls.
                if e.status == 400 and 'No valid paper ids' in str(e):
                    rows += [None] * len(chunk)
                else:
                    raise
    except net.SourceError as e:
        return 'Semantic Scholar enrichment skipped (%s)' % e
    for p, r in zip(todo, rows):
        if not r:
            p['tldr'] = ''
            continue
        p['tldr'] = ((r.get('tldr') or {}).get('text') or '').strip()
        p['influential'] = r.get('influentialCitationCount')
        pdf = (r.get('openAccessPdf') or {}).get('url')
        if pdf and pdf not in p.setdefault('oa_urls', []):
            p['oa_urls'].append(pdf)
    return None
