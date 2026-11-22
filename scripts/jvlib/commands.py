"""Finding papers: find, cite, paper, verify. Each prints compact text and returns an exit code.

One source failing never sinks a command that has other sources: the failure becomes a
`Note:` line and the rest is printed. Only when nothing at all came back is the exit code 1.
"""
from . import crossref, europepmc, fmt, net, s2, web
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
    if a.sort == 'impact':
        oa.sort_impact(merged)
    if a.tldr:
        n = s2.enrich(merged)
        if n:
            notes.append(n)
    if a.abstract:
        fill_abstracts(merged)
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


def fill_abstracts(papers):
    """OpenAlex has no abstract for most Elsevier papers, and a truncated one for some Springer,
    Elsevier and Wiley papers; Europe PMC usually has the whole abstract (5 of 5 tried)."""
    todo = [p for p in papers if p.get('doi') and len(p.get('abstract') or '') < 1500]
    if todo:
        got = europepmc.lookup([p['doi'] for p in todo])
        for p in todo:
            ab = got.get(p['doi'], {}).get('abstract') or ''
            if len(ab) > 1.2 * len(p.get('abstract') or ''):
                p['abstract'] = ab
                p['abstract_from'] = 'Europe PMC'


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
    note = s2.enrich(rows) if a.tldr else None
    if note:
        print('Note: ' + note)
    print()
    if a.abstract:
        fill_abstracts(rows)
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
        fill_abstracts([p])
        issue = crossref.print_year(p['doi']) if p['doi'] else None
        year = '%s (online %s)' % (issue, p['year']) if issue and issue != p['year'] else str(p['year'])
        print(p['title'])
        names = p['authors']
        print('Authors: ' + ', '.join(names[:12]) + (' ... (%d authors)' % len(names) if len(names) > 12 else ''))
        bib_ = ', '.join('%s %s' % (k, v) for k, v in p.get('biblio', {}).items())
        print('Venue: %s, %s%s | type: %s' % (p['venue'] or '?', year, (' | ' + bib_) if bib_ else '', p['type']))
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
        src = ' (from %s)' % p['abstract_from'] if p.get('abstract_from') else ''
        print('Abstract%s: %s' % (src, p['abstract'] or '(no abstract in OpenAlex or Europe PMC)'))
    return code


def expand(a):
    """Papers linked to several seeds through the citation graph (graph.py)."""
    from . import graph
    filters = oa.build_filters(a.years, a.type, False)
    try:
        seeds, (later, n_later, truncated), (shared, n_shared) = graph.expand(a.ids, filters, a.n, a.min_links)
    except LookupError as e:
        return _not_found(str(e))
    print('expand: %d seeds (papers linked to at least %d of them)' % (len(seeds), a.min_links))
    for i, w in enumerate(seeds):
        print('  %s  %s (%s) doi:%s | cited by %d, references %d' % (
            graph.LABELS[i], w['title'][:80], w['year'], w['doi'], w['cited'], len(w['refs'])))
    if len(a.ids) > graph.MAX_SEEDS:
        print('Note: only the first %d seeds were used.' % graph.MAX_SEEDS)
    if truncated:
        print('Note: a seed pair is cited together by more than 200 papers; only the 200 most cited of those were read.')
    if a.tldr:
        s2.enrich(later + shared)
    for title, rows, total in (('LATER WORK citing several seeds', later, n_later),
                               ('SHARED FOUNDATIONS cited by several seeds', shared, n_shared)):
        print('\n== %s: %d found, showing %d (most links first, then citations in the last two years)\n' % (
            title, total, len(rows)))
        for i, p in enumerate(rows, 1):
            print(fmt.paper(p, i, 900 if a.abstract else 0))
            print('    ' + graph.link_line(p, seeds))
    if len(seeds) < 3:
        print('\nNote: with 2 seeds every link count is 2; 3 to 6 seeds rank far better.')
    return 0


def checkbib(a):
    from . import checkbib as cb
    rows = cb.check_file(a.file)
    bad = [r for r in rows if r[2]]
    print('checkbib %s: %d entries, %d with problems\n' % (a.file, len(rows), len(bad)))
    for key, kind, issues, notes in rows:
        if issues:
            print('%s (@%s)' % (key, kind))
            for x in issues:
                print('   - ' + x)
        elif not a.problems_only:
            print('%s: ok%s' % (key, ' (' + '; '.join(notes) + ')' if notes else ''))
    return 1 if bad else 0


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
