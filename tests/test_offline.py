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
                                            mode='auto', sort='relevance', n=5, fulltext=False, no_tldr=True, abstract=False))
out = buf.getvalue()
t('OpenAlex 429 -> Crossref results shown', code == 0 and 'From Crossref' in out and 'Crossref fallback' in out)
t('the 429 is still reported', 'daily budget used up' in out)
oa.search, crossref.search, s2.enrich = saved
t('Crossref drops supporting-information DOIs', not crossref._keep({'DOI': '10.1021/jacs.7b02381.s001', 'type': 'component'}))

print('\n=== all passed ===' if not fails else '\n=== %d FAILED ===' % fails)
sys.exit(1 if fails else 0)
