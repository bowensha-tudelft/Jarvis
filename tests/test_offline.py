"""Offline checks for the pure parts. Run: python tests/test_offline.py (no network)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scripts'))
from jvlib import bib, fmt  # noqa: E402
from jvlib import openalex as oa  # noqa: E402

fails = 0


def t(name, cond):
    global fails
    print(('  ok   ' if cond else '  FAIL ') + name)
    fails += 0 if cond else 1


print('DOI')
t('strips doi.org URL and lowercases', oa.norm_doi('https://doi.org/10.1021/ACS.EST.1') == '10.1021/acs.est.1')
t('strips doi: prefix', oa.norm_doi('doi: 10.1/x') == '10.1/x')
t('title is not a DOI', not oa.looks_like_doi('A title about 10.5 things'))

print('years')
t('range', oa.year_filter('2020-2025') == 'publication_year:2020-2025')
t('open end', oa.year_filter('2022-') == 'publication_year:>2021')
t('open start', oa.year_filter('-2015') == 'publication_year:<2016')
t('single', oa.year_filter('2023') == 'publication_year:2023')
try:
    oa.year_filter('last year')
    t('bad spec refused', False)
except SystemExit:
    t('bad spec refused', True)
t('dataset excluded by default', 'type:!dataset' in oa.build_filters())

print('abstract')
inv = {'High': [0], 'Resolution': [1], 'Image': [2], 'Download': [3], 'MS': [4], 'PowerPoint': [5],
       'Slide': [6], 'Polymers': [7], 'adsorb': [8], 'PFAS.': [9]}
t('rebuilt in order, ACS caption removed', oa.abstract_text(inv) == 'Polymers adsorb PFAS.')

print('merge')
a = [{'doi': 'x', 'title': 'X'}, {'doi': 'y', 'title': 'Y'}]
b = [{'doi': 'z', 'title': 'Z'}, {'doi': 'x', 'title': 'X', 'passage': 'quote'}]
m = fmt.merge(a, b)
t('deduplicated', [p['doi'] for p in m].count('x') == 1 and len(m) == 3)
t('found twice comes first', m[0]['doi'] == 'x')
t('second copy adds its passage', m[0].get('passage') == 'quote')

print('passages')
md = '# Intro\n\nShort.\n\n## Results\n\nHigher ionic strength suppressed removal of short-chain PFAS strongly.\n\n' \
     'Unrelated paragraph about something else entirely, long enough to count.\n'
found, total = fmt.find_passages(md, ['ionic strength', 'short-chain'])
t('one paragraph matches both terms', total == 1 and 'Results' in found[0] and 'ionic strength' in found[0])
t('all words of a phrase must appear', fmt.find_passages(md, ['ionic banana'])[1] == 0)

print('bibtex')
raw = ('@article{Wang_2022, title={A Tunable Porous {\\beta}-Cyclodextrin Polymer}, volume={8}, '
       'url={http://dx.doi.org/10.1021/x}, DOI={10.1021/x}, journal={ACS Cent. Sci.}, '
       'author={Wang, Ri and Lin, Zhi-Wei}, year={2022}, pages={663–669} }')
out = bib.tidy(raw, '10.1021/x')
t('readable key', out.startswith('@article{Wang2022Tunable,'))
t('nested braces kept', '{\\beta}' in out)
t('pages use --', 'pages = {663--669}' in out)
t('doi.org url dropped', 'url =' not in out)
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, 'sub', 'refs.bib')
    t('append adds', bib.append(p, [('10.1021/x', out)]) == (1, 0))
    t('append skips duplicate DOI', bib.append(p, [('https://doi.org/10.1021/X', out)]) == (0, 1))

pre = bib.tidy('@article{F_2025, title={g-xTB}, publisher={American Chemical Society (ACS)}, '
               'author={Froitzheim, Thomas}, year={2025}}', '10.26434/chemrxiv-2025-bjxvt')
t('journal-less preprint becomes @misc ChemRxiv preprint',
  pre.startswith('@misc{') and 'howpublished = {ChemRxiv preprint}' in pre and 'publisher' not in pre)
t('a real article keeps @article', bib.tidy(raw, '10.1021/x').startswith('@article{'))

print('author names')
t('initials dropped', oa.surname_only('S. Grimme') == 'Grimme' and oa.surname_only('Grimme S') == 'Grimme')
t('full name -> surname', oa.surname_only('Stefan Grimme') == 'Grimme')

print('TEI')
from jvlib import tei  # noqa: E402
std = ('<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc><titleStmt><title>T</title></titleStmt>'
       '</fileDesc><profileDesc><abstract><p>Abs text.</p></abstract></profileDesc></teiHeader><text><body>'
       '<div><p>Intro without heading.</p></div><div><head>Results</head><p>We measured 9.0 kcal.</p>'
       '<figure type="table"><head>Table 1</head><table><row><cell>a</cell><cell>b</cell></row></table></figure></div>'
       '</body><back><div type="references"><listBibl><biblStruct/></listBibl></div></back></text></TEI>')
md = tei.to_markdown(std)
t('title, abstract, sections', md.startswith('# T') and '## Abstract\n\nAbs text.' in md and '## Results' in md)
t('untitled section is not filed under the abstract', md.index('## (section without a heading)') < md.index('Intro without'))
t('tables kept as rows', '| a | b |' in md)
t('references dropped', 'biblStruct' not in md and 'listBibl' not in md)
old = '<html><body><tei><text><div><head>Methods</head><p>Old shape paragraph.</p></div></text></tei></body></html>'
t('old GROBID shape (divs directly under <text>)', '## Methods' in tei.to_markdown(old) and 'Old shape' in tei.to_markdown(old))
t('malformed XML still yields text', 'broken' in tei.to_markdown('<TEI><p>broken'))

print('semantic filters')
calls = []
real_get = oa._get
oa._get = lambda path, ttl: calls.append(path) or {'results': [
    {'title': 'A', 'authorships': [{'author': {'display_name': 'Stefan Grimme'}}]},
    {'title': 'B', 'authorships': [{'author': {'display_name': 'Someone Else'}}]}]}
rows = oa.search_semantic('q', oa.build_filters('2025-', None, False, 'chemrxiv', 'S. Grimme'), 5)
q = calls[-1]
t('unsupported filters not sent', 'is_paratext' not in q and 'raw_author_name' not in q)
t('source mapped to primary_location', 'primary_location.source.id' in q and 'locations.source.id:S' not in q.replace('primary_location', ''))
t('author applied afterwards', [r['title'] for r in rows] == ['A'])
oa._get = real_get

print('Crossref fallback')
from jvlib import commands, crossref, net, s2  # noqa: E402
import argparse  # noqa: E402
import io  # noqa: E402
import contextlib  # noqa: E402
saved = (oa.search, crossref.search, s2.enrich)
oa.search = lambda *a, **k: (_ for _ in ()).throw(net.SourceError('openalex', 429, 'daily budget used up'))
crossref.search = lambda q, n, y: [{'doi': '10.1/cr', 'title': 'From Crossref', 'authors': [], 'cited': 3,
                                    'year': 2025, 'from': 'crossref', 'oa_status': '?'}]
s2.enrich = lambda ps: None
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    code = commands.find(argparse.Namespace(query='x', years=None, type=None, oa=False, source=None, author=None,
                                            mode='auto', sort='relevance', n=5, fulltext=False, tldr=False, abstract=False))
out = buf.getvalue()
t('OpenAlex 429 -> Crossref results shown', code == 0 and 'From Crossref' in out and 'Crossref fallback' in out)
t('the 429 is still reported', 'daily budget used up' in out)
oa.search, crossref.search, s2.enrich = saved
t('Crossref drops supporting-information DOIs', not crossref._keep({'DOI': '10.1021/jacs.7b02381.s001', 'type': 'component'}))

print('author manuscripts')
from jvlib import manuscripts as ms  # noqa: E402
t('NSF PAR, OSTI, PMC, university sites allowed',
  all(ms.allowed(u) for u in ('https://par.nsf.gov/servlets/purl/10205501', 'https://www.osti.gov/servlets/purl/1',
                              'https://pmc.ncbi.nlm.nih.gov/articles/PMC1/', 'https://repository.tudelft.nl/x.pdf',
                              'https://dash.harvard.edu/a.pdf', 'https://eprints.whiterose.ac.uk/1/')))
t('shadow libraries, ResearchGate and PubMed abstract pages refused',
  not any(ms.allowed(u) for u in ('https://sci-hub.se/10.1038/x', 'https://www.researchgate.net/publication/1',
                                  'https://pubmed.ncbi.nlm.nih.gov/26689365/', 'https://academia.edu/1')))
title = 'Rapid removal of organic micropollutants from water by a porous beta-cyclodextrin polymer'
other = ('Evaluating the effects of water matrix constituents on micropollutant removal. Introduction. '
         'Porous polymer adsorbents enable rapid removal of organic micropollutants from water [1]; '
         'beta-cyclodextrin polymer networks are porous ...')
t('a paper that only discusses the title words is rejected', not ms.matches(other, title))
t('the paper itself, title at the top, is accepted', ms.matches('# ' + title + '\n\nAuthors ...', title))
t('an abstract page does not look like a full text', not ms.looks_full('Abstract. We report ... Keywords: x'))

print('PMC JATS')
from jvlib import europepmc  # noqa: E402
jats = ('<!DOCTYPE article PUBLIC "x" "y"><article><front><article-meta><title-group><article-title>T</article-title>'
        '</title-group><abstract><p>Abs.</p></abstract></article-meta></front><body><sec><title>Introduction</title>'
        '<p>Intro text.</p><sec><title>Sub</title><p>Deep.</p></sec></sec><sec><p>No title here.</p></sec></body>'
        '<back><ref-list><ref>R1</ref></ref-list></back></article>')
jm = europepmc.jats_to_markdown(jats)
t('JATS: title, abstract, nested sections', jm.startswith('# T') and '## Introduction' in jm and '### Sub' in jm)
t('JATS: untitled section labelled, references dropped', '(section without a heading)' in jm and 'R1' not in jm)

print('issue year')
art = bib.tidy('@article{A_2015, title={Rapid removal}, journal={Nature}, volume={529}, author={Alsbaiee, A.}, '
               'year={2015}}', '10.1038/nature16185', 2016)
t('printed issue year replaces the online year, key included', 'year = {2016}' in art and art.startswith('@article{Alsbaiee2016'))

print('checkbib')
from jvlib import checkbib as cb  # noqa: E402
bibtext = ('@comment{x}\n@article{A1, title={Rapid {removal} of x}, author={Alsbaiee, A. and Smith, B.}, year={2016},\n'
           '  doi={10.1038/nature16185}, pages={190--194}}\n@misc{B2, title = "No braces", year = 2020}\n')
entries = cb.parse_bib(bibtext)
t('entries parsed, @comment skipped', [e[1] for e in entries] == ['A1', 'B2'])
t('nested braces in a field kept', entries[0][2]['title'] == 'Rapid {removal} of x')
t('surname from "Last, First and ..."', cb._surname(entries[0][2]['author']) == 'Alsbaiee')
t('diacritics folded for comparison', cb._fold('Barın') == cb._fold('Barin'))
saved_cr = cb._cr
cb._cr = lambda doi: {'title': ['Rapid removal of x'], 'author': [{'family': 'Alsbaiee'}], 'volume': '529',
                      'page': '190-194', 'issued': {'date-parts': [[2015]]}, 'published-print': {'date-parts': [[2016]]},
                      'type': 'journal-article'}
iss, _ = cb.check_entry('article', 'A1', entries[0][2], {})
t('a correct entry has no issues (print year 2016 accepted)', iss == [])
cb._cr = lambda doi: {'title': ['Nano-Bio Interactions in Cancer'], 'author': [{'family': 'Liu'}], 'type': 'journal-article'}
iss, _ = cb.check_entry('article', 'A1', entries[0][2], {})
t('a DOI pointing to another paper is caught', bool(iss) and iss[0].startswith('DOI points to a different paper'))
cb._cr = lambda doi: {'title': ['Rapid removal of x'], 'author': [{'family': 'Alsbaiee'}], 'type': 'posted-content',
                      'relation': {'is-preprint-of': [{'id': '10.1021/real'}]}, 'issued': {'date-parts': [[2016]]}}
iss, _ = cb.check_entry('article', 'A1', entries[0][2], {})
t('a preprint that was published is reported', any('published version: doi:10.1021/real' in x for x in iss))
cb._cr = lambda doi: None
iss, _ = cb.check_entry('article', 'A1', entries[0][2], {})
t('an unregistered DOI is reported', bool(iss) and 'not registered' in iss[0])
cb._cr = saved_cr

print('expand')
from jvlib import graph  # noqa: E402
saved = (oa.work, graph._citing_pair, oa.by_ids)
seeds = {'a': {'openalex_id': 'W1', 'refs': ['W9', 'W8'], 'cited': 3, 'title': 'A', 'year': 2016, 'authors': ['X Alpha'], 'doi': 'a'},
         'b': {'openalex_id': 'W2', 'refs': ['W9'], 'cited': 2, 'title': 'B', 'year': 2017, 'authors': ['Y Beta'], 'doi': 'b'},
         'c': {'openalex_id': 'W3', 'refs': ['W9', 'W8', 'W1'], 'cited': 2, 'title': 'C', 'year': 2018, 'authors': ['Z Gamma'], 'doi': 'c'}}
oa.work = lambda s: seeds.get(s)
CITES = {'W5': ['W1', 'W2', 'W3'], 'W6': ['W1', 'W2'], 'W3': ['W1']}     # paper -> seeds it cites
def fake_pair(a, b, f):
    rows = [{'id': 'https://openalex.org/' + w, 'referenced_works': ['https://openalex.org/' + x for x in refs],
             'counts_by_year': [{'year': 2026, 'cited_by_count': {'W5': 1, 'W6': 9}.get(w, 0)}]}
            for w, refs in CITES.items() if a in refs and b in refs]
    return rows, len(rows)
graph._citing_pair = fake_pair
oa.by_ids = lambda ids, f=(): [{'openalex_id': i, 'recent_cites': {'W5': 1, 'W6': 9}.get(i, 0)} for i in ids]
_, (later, nl, _), (shared, ns) = graph.expand(['a', 'b', 'c'], n=10)
t('later work: linked to 3 seeds ranks above linked to 2', [p['openalex_id'] for p in later] == ['W5', 'W6'])
t('a seed citing another seed is not listed as a result',
  'W3' not in [p['openalex_id'] for p in later] and 'W1' not in [p['openalex_id'] for p in shared])
t('shared foundations counted', [p['openalex_id'] for p in shared] == ['W9', 'W8'] and ns == 2)
oa.work, graph._citing_pair, oa.by_ids = saved

print('Firecrawl credits in the manuscript search')
from jvlib import web  # noqa: E402
TITLE = 'Rapid removal of organic micropollutants from water by a porous beta-cyclodextrin polymer'
BODY = TITLE + '\n' + ' '.join(['Introduction text. Results text. Discussion text. Conclusions. References.'] * 60)
calls, fc_searches = [], []
def fake_scrape(url, max_pages=web.MAX_PDF_PAGES, meta=False):
    calls.append((url, max_pages))
    md = ('Some other paper entirely\n' + 'x ' * 2000) if 'wrong' in url else BODY
    md = md[:3000] if max_pages == 1 else md
    out = (md, '', min(max_pages, 12), 12)
    return out if meta else out[:2]
saved = (web.scrape, web.tavily_search, web.firecrawl_search, net.key)
web.scrape = fake_scrape
net.key = lambda s: 'k'
web.tavily_search = lambda q, n, domains=None, depth='basic': ('', [
    {'url': 'https://par.nsf.gov/servlets/purl/1-wrong', 'title': TITLE},   # same title in the hit, wrong PDF
    {'url': 'https://par.nsf.gov/servlets/purl/2', 'title': TITLE}] if domains else [])
web.firecrawl_search = lambda q, n=5: fc_searches.append(q) or []
md, url = ms.find(TITLE, [])
for u, mp in calls:
    print('      scrape', u, 'maxPages', mp)
t('right paper found', url == 'https://par.nsf.gov/servlets/purl/2' and md == BODY)
t('only the right paper is scraped whole', [c for c in calls if c[1] != 1] == [('https://par.nsf.gov/servlets/purl/2', web.MAX_PDF_PAGES)])
t('the wrong PDF costs one page', [c for c in calls if 'wrong' in c[0]] == [('https://par.nsf.gov/servlets/purl/1-wrong', 1)])
t('no Firecrawl search when Tavily found candidates', fc_searches == [])
web.scrape, web.tavily_search, web.firecrawl_search, net.key = saved

print('\n=== all passed ===' if not fails else '\n=== %d FAILED ===' % fails)
sys.exit(1 if fails else 0)
