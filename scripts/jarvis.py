#!/usr/bin/env python3
"""Jarvis: literature search for research scoping and evidence checking.

  find   "<query>"   papers (OpenAlex keyword + semantic search); --sort impact for current importance
  cite   <doi>       snowball: --dir citers | refs | related
  paper  <doi|title> ...   full record and abstract
  verify "<citation as remembered>"   the records that really exist (Crossref fuzzy match)
  expand <doi> <doi> ...   papers linked to several seed papers through the citation graph
  checkbib <file.bib>      check every entry: DOI points to the paper, year/volume/pages, preprint
                           since published, retraction
  read   <doi|url>   full text (PMC, OpenAlex, free copies, author manuscripts); --find "terms" for passages
  web    "<query>"   web search (Tavily and/or Firecrawl)
  bib    <doi> ...   BibTeX from doi.org; --out refs.bib appends without duplicates
  status [--check]   which keys are set; --check pings each source

Run any command with -h for its options.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jvlib import commands, misc, net, reading  # noqa: E402


def build():
    ap = argparse.ArgumentParser(prog='jarvis', description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--fresh', action='store_true', help='ignore cached results')
    sub = ap.add_subparsers(dest='cmd', required=True)

    def filters(p):
        p.add_argument('--years', help='2020-2025, 2020-, -2015 or 2023')
        p.add_argument('--type', help='OpenAlex work type, e.g. review, article, preprint')
        p.add_argument('--author', help='author surname, e.g. Grimme (never put names in the query)')
        p.add_argument('-n', type=int, default=10, help='how many to show (default 10)')
        p.add_argument('--abstract', action='store_true', help='print abstracts (900 chars each)')
        p.add_argument('--tldr', action='store_true', help='add Semantic Scholar TLDRs (often rate-limited)')

    p = sub.add_parser('find', help='find papers')
    p.add_argument('query', help='keywords; AND / OR / NOT, () and "phrases" work in keyword mode')
    p.add_argument('--mode', choices=['auto', 'keyword', 'semantic'], default='auto',
                   help='auto = keyword and semantic merged (default)')
    p.add_argument('--sort', choices=['relevance', 'cited', 'recent', 'impact'], default='relevance',
                   help='impact = citations in the last two years, then FWCI')
    p.add_argument('--oa', action='store_true', help='open-access papers only')
    p.add_argument('--fulltext', action='store_true', help='keyword search in full texts too (noisy)')
    p.add_argument('--source', choices=sorted(['chemrxiv', 'arxiv']),
                   help='only works with a copy on this preprint server')
    filters(p)
    p.set_defaults(fn=commands.find)

    p = sub.add_parser('cite', help='snowball from one paper')
    p.add_argument('id', help='DOI, OpenAlex id or title')
    p.add_argument('--dir', choices=['citers', 'refs', 'related'], default='citers')
    p.add_argument('--sort', choices=['cited', 'recent', 'impact'], default='cited')
    filters(p)
    p.set_defaults(fn=commands.cite)

    p = sub.add_parser('paper', help='full record and abstract')
    p.add_argument('ids', nargs='+', help='DOIs, OpenAlex ids or titles')
    p.set_defaults(fn=commands.paper)

    p = sub.add_parser('expand', help='papers linked to several seeds through citations')
    p.add_argument('ids', nargs='+', help='2-8 seed DOIs (or OpenAlex ids / titles); 3-6 work best')
    p.add_argument('--min-links', type=int, default=2)
    p.add_argument('--years', help='limit the later-work list, e.g. 2023-')
    p.add_argument('--type', help='OpenAlex work type')
    p.add_argument('-n', type=int, default=25)
    p.add_argument('--abstract', action='store_true')
    p.add_argument('--tldr', action='store_true')
    p.set_defaults(fn=commands.expand)

    p = sub.add_parser('checkbib', help='check every entry of a .bib file')
    p.add_argument('file')
    p.add_argument('--problems-only', action='store_true')
    p.set_defaults(fn=commands.checkbib)

    p = sub.add_parser('verify', help='check a citation as remembered against Crossref')
    p.add_argument('citation', help='whatever is remembered: authors, year, words of the title, journal')
    p.add_argument('-n', type=int, default=5)
    p.set_defaults(fn=commands.verify)

    p = sub.add_parser('read', help='read an open-access full text')
    p.add_argument('target', help='DOI, title or URL')
    p.add_argument('--find', action='append', help='terms to locate; repeat or separate with ";"')
    p.add_argument('-k', type=int, default=8, help='passages to show with --find (default 8)')
    p.add_argument('--max', type=int, default=12000, help='characters to print without --find')
    p.add_argument('--web', action='store_true', help='skip PMC and OpenAlex full texts, read the web copies')
    p.add_argument('--no-search', action='store_true', help='do not search the web for an author manuscript')
    p.set_defaults(fn=reading.read)

    p = sub.add_parser('web', help='web search')
    p.add_argument('query')
    p.add_argument('--engine', choices=['auto', 'tavily', 'firecrawl', 'both'], default='auto')
    p.add_argument('--domains', help='comma-separated, e.g. echa.europa.eu,epa.gov')
    p.add_argument('--deep', action='store_true', help='Tavily advanced depth (costs 2 credits)')
    p.add_argument('-n', type=int, default=6)
    p.set_defaults(fn=misc.web_search)

    p = sub.add_parser('bib', help='BibTeX for DOIs')
    p.add_argument('dois', nargs='+')
    p.add_argument('--out', help='.bib file to append to (duplicates skipped)')
    p.set_defaults(fn=misc.bibtex)

    p = sub.add_parser('status', help='keys, cache, and a live check')
    p.add_argument('--check', action='store_true')
    p.set_defaults(fn=misc.status)
    return ap


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8')    # Windows consoles default to cp1252
        except (AttributeError, ValueError):
            pass
    a = build().parse_args(argv)
    net.FRESH = a.fresh
    if hasattr(a, 'n'):
        a.n = max(1, min(a.n, 50))
    try:
        return a.fn(a)
    except net.SourceError as e:
        print('Error: %s' % e)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    sys.exit(main())
