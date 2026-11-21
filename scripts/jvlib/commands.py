"""Finding papers: find, cite, paper, verify. Each prints compact text and returns an exit code.

One source failing never sinks a command that has other sources: the failure becomes a
`Note:` line and the rest is printed. Only when nothing at all came back is the exit code 1.
"""
from . import crossref, fmt, net, s2, web
from . import openalex as oa

NEXT = ('Next: `paper <doi>` for the abstract, `cite <doi>` to snowball, '
        '`read <doi> --find "<terms>"` to check the full text, `bib <doi> ...` for BibTeX.')


def notes_out(notes):
    for n in notes:
        print('Note: ' + n)


def _semantic(query, filters, n, notes):
    """Firecrawl's paper index (keeps constraints, carries a matching passage) merged with OpenAlex's
    semantic search. Both run: the index has no ChemRxiv and thin chemistry-journal coverage (for the
    2025 g-xTB preprint it returned 8 hits, none of them the paper), OpenAlex has the rest."""
    lists, parts = [], []
    try:
        hits = web.paper_index(query, k=max(n * 2, 10))
        if hits:
            found = oa.by_dois([h['doi'] for h in hits], filters)
            rows = []
            for h in hits:
                p = found.get(oa.norm_doi(h['doi']))
                if p:
                    p['passage'] = h['passage']
                    rows.append(p)
            lists.append(rows)
            parts.append('paper index %d hits (%d after filters)' % (len(hits), len(rows)))
    except net.SourceError as e:
        notes.append('Firecrawl paper index failed (%s)' % e)
    try:
        rows = oa.search_semantic(query, filters, n)
        lists.append(rows)
        parts.append('OpenAlex semantic %d' % len(rows))
    except net.SourceError as e:
        notes.append(str(e))
    return fmt.merge(*lists), ', '.join(parts) or 'semantic failed'


def find(a):
    filters = oa.build_filters(a.years, a.type, a.oa, a.source, a.author)
    notes, lists, parts = [], [], []
    oa_down = False
    if a.mode in ('auto', 'keyword'):
        try:
            rows, total = oa.search(a.query, filters, a.sort, a.n, fulltext=a.fulltext)
            lists.append(rows)
            parts.append('keyword (%s) %s total' % ('full text' if a.fulltext else 'title+abstract', total))
        except net.SourceError as e:
            notes.append(str(e))
            oa_down = e.status == 429
    if a.mode in ('auto', 'semantic') and not oa_down:
        rows, desc = _semantic(a.query, filters, a.n, notes)
        lists.append(rows)
        parts.append(desc)
    if oa_down:
        try:
            rows = crossref.search(a.query, a.n, a.years)
            lists.append(rows)
            parts.append('Crossref fallback %d (no abstracts; --type/--author/--source/--oa not applied)' % len(rows))
        except net.SourceError as e:
            notes.append(str(e))
    merged = fmt.merge(*lists)
    if a.sort == 'cited':
        merged.sort(key=lambda p: -p['cited'])
    elif a.sort == 'recent':
        merged.sort(key=lambda p: -(p['year'] or 0))
    merged = merged[:a.n]
    if not merged:
        notes_out(notes)
        print('No papers found for: %s' % a.query)
        print('Try: fewer words, a synonym or the spelled-out term, the abbreviation with and without '
              'its hyphen ("g-xTB" vs "gxTB"), author names via --author, or `verify` for a remembered citation.')
        return 1 if notes else 0
    if not a.no_tldr:
        n = s2.enrich(merged)
        if n:
            notes.append(n)
    flt = ', '.join(x for x in (a.author and 'author=' + oa.surname_only(a.author), a.source and 'source=' + a.source) if x)
    print('find "%s"%s | %s | showing %d, sort=%s%s' % (
        a.query, ' [%s]' % flt if flt else '', '; '.join(parts), len(merged), a.sort,
        ' | found by more than one search listed first' if a.mode == 'auto' and a.sort == 'relevance' else ''))
    notes_out(notes)
    print()
    print(fmt.papers(merged, 900 if a.abstract else 0))
    print('\n' + NEXT)
    return 0


def _not_found(ident):
    """OpenAlex has no match: show Crossref's closest records instead of a bare 'not found'."""
    print('OpenAlex has no record matching: %s' % ident)
    try:
        cands = crossref.match(ident, 3)
    except net.SourceError as e:
        print('Note: Crossref lookup failed too (%s)' % e)
        return 1
    if cands:
        print('Closest records in Crossref (check authors, year and venue before using one):\n')
        print(fmt.papers(cands))
    return 1


def cite(a):
    seed = oa.work(a.id)
    if not seed:
        return _not_found(a.id)
    filters = oa.build_filters(a.years, a.type, False, None, a.author)
    rows, total = oa.citations(seed, a.dir, filters, a.sort, a.n)
    label = {'citers': 'papers citing it', 'refs': 'its references', 'related': 'related papers'}[a.dir]
    print('cite: %s (%s) -> %s: %s in total, showing %d' % (
        seed['title'], seed['year'], label, total if total is not None else '?', len(rows)))
    if a.dir == 'related':
        print('(related = OpenAlex\'s relatedness order, not citations)')
    if not rows:
        return 0
    note = None if a.no_tldr else s2.enrich(rows)
    if note:
        print('Note: ' + note)
    print()
    print(fmt.papers(rows, 900 if a.abstract else 0))
    return 0


def paper(a):
    code = 0
    for i, ident in enumerate(a.ids):
        if i:
            print('\n' + '=' * 60)
        p = oa.work(ident)
        if not p:
            code = _not_found(ident)
            continue
        note = s2.enrich([p])
        print(p['title'])
        names = p['authors']
        print('Authors: ' + ', '.join(names[:12]) + (' ... (%d authors)' % len(names) if len(names) > 12 else ''))
        bib_ = ', '.join('%s %s' % (k, v) for k, v in p.get('biblio', {}).items())
        print('Venue: %s, %s%s | type: %s' % (p['venue'] or '?', p['year'], (' | ' + bib_) if bib_ else '', p['type']))
        print('doi:%s | openalex:%s' % (p['doi'] or '-', p['openalex_id']))
        infl = ' (influential %s)' % p['influential'] if p.get('influential') is not None else ''
        print('Cited by %d%s | references %d | topics: %s' % (p['cited'], infl, len(p['refs']), '; '.join(p['topics']) or '-'))
        copies = ['%s (%s%s)' % (c['url'], c['version'], ', ' + c['source'] if c['source'] else '') for c in p['copies'][:4]]
        print('Open access: %s%s' % (p['oa_status'], ' | OpenAlex holds the full text' if p['has_text'] else ''))
        for c in copies:
            print('  free copy: ' + c)
        if p['type'] == 'preprint':
            print('Preprint: not peer-reviewed. Check whether a journal version exists before citing it as published.')
        if note:
            print('Note: ' + note)
        if p.get('tldr'):
            print('TLDR: ' + p['tldr'])
        print('Abstract: ' + (p['abstract'] or '(OpenAlex has no abstract for this paper)'))
    return code


def verify(a):
    """A citation as the user remembers it -> the records that actually exist."""
    try:
        cands = crossref.match(a.citation, a.n)
    except net.SourceError as e:
        print('Error: %s' % e)
        return 1
    if not cands:
        print('Crossref has nothing resembling: %s' % a.citation)
        return 1
    try:   # one OpenAlex request adds citation counts, OA status and full-text availability
        found = oa.by_dois([c['doi'] for c in cands])
        cands = [found.get(c['doi'], c) for c in cands]
    except net.SourceError as e:
        print('Note: OpenAlex details skipped (%s)' % e)
    print('verify "%s" | closest %d records in Crossref, best match first.' % (a.citation, len(cands)))
    print('A close match is not proof: compare authors, year, venue and title with what the user '
          'remembers, and say which parts differ.\n')
    print(fmt.papers(cands))
    return 0
