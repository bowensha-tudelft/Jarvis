"""Author manuscripts that OpenAlex does not know about, found by web search.

Measured 2026-11: a writer limited to web search read 10 papers in full from public author
manuscripts (mostly NSF PAR, the US National Science Foundation's public-access repository).
OpenAlex listed 8 of those 10 as closed with no free copy at all, Alsbaiee et al. 2016 (Nature)
among them. So when OpenAlex and Europe PMC have nothing, `read` searches the web for the title
and accepts only public repositories: funder and government archives, PMC, university and
institutional repositories, preprint servers. Shadow libraries and social sites with uploads of
uncertain permission are refused.
"""
import difflib
import re
from urllib.parse import urlparse

from . import net, web

# pubmed.ncbi.nlm.nih.gov is NOT here: its pages are abstracts with page furniture, and one was
# accepted as a "manuscript" in testing (22k characters, title matched, no full text). PMC is.
ALLOW = re.compile(
    r'(^|\.)(par\.nsf\.gov|osti\.gov|europepmc\.org|pmc\.ncbi\.nlm\.nih\.gov|arxiv\.org|chemrxiv\.org|biorxiv\.org|'
    r'hal\.science|hal\.[a-z.]+|zenodo\.org|figshare\.com|escholarship\.org|core\.ac\.uk|'
    r'[a-z0-9-]+\.edu|[a-z0-9-]+\.ac\.[a-z]{2}|[a-z0-9-]+\.edu\.[a-z]{2})$'
    r'|repositor|eprints|dspace|scholarworks|research-?portal|^pure\.|digitalcommons|scholarship|^opus\.|^publications\.',
    re.I)
DENY = re.compile(r'sci-hub|scihub|libgen|z-lib|zlibrary|annas-archive|researchgate\.net|academia\.edu|scribd', re.I)


def allowed(url):
    host = urlparse(url).netloc.lower().split(':')[0]
    return bool(host) and not DENY.search(host) and bool(ALLOW.search(host))


def _norm(s):
    return ' '.join(re.findall(r'[a-z0-9]+', (s or '').lower()))


def similarity(a, b):
    """Share of title a found as one contiguous run in b (0..1)."""
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    m = difflib.SequenceMatcher(None, a, b, autojunk=False).find_longest_match(0, len(a), 0, len(b))
    return m.size / len(a)


def matches(md, title):
    """The text must carry the paper's title as one phrase near its top. Counting the title's words
    anywhere was not enough: a 2020 Water Research manuscript whose introduction discusses Alsbaiee
    2016 contained every word of that title and was accepted as Alsbaiee 2016."""
    return similarity(title, md[:2500]) >= 0.85


FULLTEXT_MARKS = ('introduction', 'results', 'discussion', 'conclusion', 'methods', 'experimental',
                  'references', 'acknowledg', 'supporting information')


def looks_full(md):
    """A full text names several of its sections; an abstract page or a landing page does not."""
    low = md.lower()
    return sum(m in low for m in FULLTEXT_MARKS) >= 3


# The public-access archives where funders put accepted manuscripts. A general web search rarely
# ranks them; the web-only writer found Alsbaiee 2016 at par.nsf.gov/servlets/purl/10017464.
ARCHIVES = ['par.nsf.gov', 'osti.gov']


def find(title, notes, tries=6):
    """-> (markdown, url) for a public manuscript of the paper, or (None, None)."""
    cands = []
    t = title[:200]
    # Tavily restricted to the archives returns their PDF links directly (par.nsf.gov/servlets/purl/N);
    # Firecrawl's `site:` search mostly returned unrelated OSTI record pages. Wrong papers in the
    # candidates are harmless: matches() rejects any text whose title is not this paper's.
    searches = []
    if net.key('tavily'):
        searches.append(lambda: web.tavily_search(t, 8, ARCHIVES)[1])
    searches += [lambda: web.firecrawl_search('"%s" pdf' % t, 8)]
    if net.key('tavily'):
        searches.append(lambda: web.tavily_search('"%s" pdf' % t, 8)[1])
    for search in searches:
        try:
            cands += [(r['url'], r.get('title') or '') for r in search() if r.get('url')]
        except net.SourceError as e:
            notes.append('manuscript search: %s' % e)
    # Try the results whose own title looks like this paper first: scraping is 1 credit per try, and
    # in testing the right PDF sat behind six wrong ones and was never reached.
    cands.sort(key=lambda c: -similarity(title, c[1]))
    seen, urls = set(), []
    for u, _ in cands:
        # NSF PAR and OSTI record pages (/biblio/N) are metadata; the manuscript PDF is /servlets/purl/N.
        m = re.match(r'(https?://(?:www\.)?(?:par\.nsf\.gov|osti\.gov))/biblio/(\d+)', u)
        for v in ([m.group(1) + '/servlets/purl/' + m.group(2)] if m else []) + [u]:
            if v not in seen and allowed(v):
                seen.add(v)
                urls.append(v)
    if not urls:
        notes.append('no public manuscript found by web search (only repositories, archives and university sites are accepted)')
        return None, None
    for u in urls[:tries]:
        try:
            md, _ = web.scrape(u)
        except net.SourceError as e:
            notes.append('%s -> %s' % (u, e))
            continue
        if len(md) >= 3000 and matches(md, title) and looks_full(md):
            return md, u
        notes.append('%s -> not this paper, or not a full text' % u)
    return None, None
