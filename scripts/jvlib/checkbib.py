"""`checkbib`: check every entry of a .bib file against the registries.

Checking references was where Jarvis helped most in testing: a web-search-only run missed a DOI that
resolved to an unrelated paper (the title, authors and journal were right), then reused that DOI in
its own reading list. Per entry this checks:
- the DOI exists and points to the paper the entry describes (title as one phrase, first author);
- year, volume and first page against Crossref (printed-issue or online year both accepted);
- a preprint that has since been published (Crossref `is-preprint-of`), or a journal article
  with the same title;
- retraction (OpenAlex `is_retracted`);
- no DOI: the closest Crossref record, suggested only when the title matches.
"""
import re
import unicodedata
import urllib.parse

from . import crossref, net
from . import openalex as oa
from .bib import _split_fields
from .manuscripts import similarity

TTL = 30 * 86400


def parse_bib(text):
    """[(type, key, fields)] from BibTeX text; @comment/@string/@preamble skipped."""
    out, i = [], 0
    for m in re.finditer(r'@(\w+)\s*\{', text):
        if m.start() < i:
            continue
        kind = m.group(1).lower()
        depth, j = 1, m.end()
        while j < len(text) and depth:
            depth += {'{': 1, '}': -1}.get(text[j], 0)
            j += 1
        i = j
        if kind in ('comment', 'string', 'preamble'):
            continue
        body = text[m.end():j - 1]
        key, _, rest = body.partition(',')
        out.append((kind, key.strip(), _split_fields(rest)))
    return out


def _clean(s):
    return re.sub(r'[{}\\]', '', s or '').strip()


def _fold(s):
    """Lower case without diacritics, so 'Barın' in one source matches 'Barin' in another."""
    s = unicodedata.normalize('NFKD', s.replace('ı', 'i')).encode('ascii', 'ignore').decode()
    return ' '.join(re.findall(r'[a-z]+', s.lower()))


def _surname(author_field):
    first = _clean(author_field).split(' and ')[0].strip()
    if ',' in first:
        return first.split(',')[0].strip()
    return first.split()[-1] if first else ''


def _cr(doi):
    try:
        return net.request('crossref', 'https://api.crossref.org/works/' + urllib.parse.quote(doi, safe='/'),
                           ttl=TTL, retries=1)['message']
    except net.SourceError as e:
        return None if e.status == 404 else e


def _years(it):
    ys = set()
    for k in ('published-print', 'published-online', 'issued'):
        dp = ((it.get(k) or {}).get('date-parts') or [[None]])[0][0]
        if dp:
            ys.add(int(dp))
    return ys


def check_entry(kind, key, f, retracted):
    issues, notes = [], []
    title = _clean(f.get('title'))
    doi = oa.norm_doi(_clean(f.get('doi')) or (re.search(r'10\.\d{4,9}/\S+', f.get('url', '')) or [''])[0])
    if not doi:
        if not title:
            return ['no DOI and no title'], notes
        try:
            best = crossref.match('%s %s %s' % (title, _surname(f.get('author', '')), _clean(f.get('year'))), 3)
        except net.SourceError as e:
            return ['no DOI; Crossref lookup failed (%s)' % e], notes
        hit = next((c for c in best if similarity(title, c['title']) >= 0.9 or similarity(c['title'], title) >= 0.9), None)
        if hit:
            issues.append('no DOI; Crossref has it as doi:%s (%s, %s)' % (hit['doi'], hit['venue'], hit['year']))
        else:
            issues.append('no DOI, and no Crossref record matches the title' +
                          ('; closest: "%s" doi:%s' % (best[0]['title'][:90], best[0]['doi']) if best else ''))
        return issues, notes
    it = _cr(doi)
    if isinstance(it, net.SourceError):
        return ['Crossref lookup failed (%s)' % it], notes
    if it is None:
        return ['DOI %s is not registered: the reference may not exist' % doi], notes
    cr_title = _clean((it.get('title') or [''])[0])
    if title and max(similarity(title, cr_title), similarity(cr_title, title)) < 0.85:
        issues.append('DOI points to a different paper: "%s" (%s)' % (cr_title[:110], ((it.get('container-title') or ['?'])[0])))
        return issues, notes          # nothing else is comparable
    fam = ((it.get('author') or [{}])[0]).get('family', '')
    if fam and f.get('author') and _fold(fam) not in _fold(_clean(f['author'])):
        issues.append('first author is %s, not %s' % (fam, _surname(f['author'])))
    y = re.sub(r'\D', '', f.get('year', ''))
    ys = _years(it)
    if y and ys and int(y) not in ys:
        issues.append('year %s; registry has %s' % (y, '/'.join(map(str, sorted(ys)))))
    vol = (it.get('volume') or '').strip()
    if vol and f.get('volume') and _clean(f['volume']) != vol:
        issues.append('volume %s; registry has %s' % (_clean(f['volume']), vol))
    page = (it.get('page') or it.get('article-number') or '').split('-')[0].strip()
    bpage = re.split(r'[-–]+', _clean(f.get('pages', '')))[0].strip()
    if page and bpage and bpage != page:
        issues.append('first page %s; registry has %s' % (bpage, page))
    pre = [r.get('id') for r in (it.get('relation') or {}).get('is-preprint-of', [])]
    if pre:
        issues.append('preprint; published version: doi:%s' % pre[0])
    elif it.get('type') == 'posted-content':
        try:
            later = [c for c in crossref.match(cr_title, 5) if c['type'] == 'journal-article'
                     and max(similarity(cr_title, c['title']), similarity(c['title'], cr_title)) >= 0.9]
        except net.SourceError:
            later = []
        if later:
            issues.append('preprint; a journal article with the same title exists: doi:%s (%s, %s)' % (
                later[0]['doi'], later[0]['venue'], later[0]['year']))
        else:
            notes.append('preprint, no journal version found')
    if retracted.get(doi):
        issues.insert(0, 'RETRACTED (OpenAlex)')
    return issues, notes


def check_file(path):
    text = open(path, encoding='utf-8').read()
    entries = parse_bib(text)
    dois = [oa.norm_doi(_clean(f.get('doi'))) for _, _, f in entries if f.get('doi')]
    retracted = {}
    try:
        retracted = {d: p['retracted'] for d, p in oa.by_dois(dois).items()}
    except net.SourceError:
        pass
    return [(key, kind) + check_entry(kind, key, f, retracted) for kind, key, f in entries]
