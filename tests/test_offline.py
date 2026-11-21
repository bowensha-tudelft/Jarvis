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

print('\n=== all passed ===' if not fails else '\n=== %d FAILED ===' % fails)
sys.exit(1 if fails else 0)
