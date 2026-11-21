#!/usr/bin/env python3
"""Jarvis: literature search for research scoping and evidence checking.

  find   "<query>"   papers (OpenAlex keyword + Firecrawl paper index, with S2 TLDRs)
  cite   <doi>       snowball: --dir citers | refs | related
  paper  <doi|title> ...   full record and abstract
  read   <doi|url>   open-access full text via Firecrawl; --find "terms" for matching passages
  web    "<query>"   web search (Tavily and/or Firecrawl)
  bib    <doi> ...   BibTeX from doi.org; --out refs.bib appends without duplicates
  status [--check]   which keys are set; --check pings each source

Run any command with -h for its options.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jvlib import commands, net  # noqa: E402


def build():
    ap = argparse.ArgumentParser(prog='jarvis', description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--fresh', action='store_true', help='ignore cached results')
    sub = ap.add_subparsers(dest='cmd', required=True)

    def filters(p):
        p.add_argument('--years', help='2020-2025, 2020-, -2015 or 2023')
        p.add_argument('--type', help='OpenAlex work type, e.g. review, article, preprint')
        p.add_argument('-n', type=int, default=10, help='how many to show (default 10)')
        p.add_argument('--abstract', action='store_true', help='print abstracts (900 chars each)')
        p.add_argument('--no-tldr', action='store_true', help='skip the Semantic Scholar TLDR lookup')

    p = sub.add_parser('find', help='find papers')
    p.add_argument('query', help='keywords; AND / OR / NOT, () and "phrases" work in keyword mode')
    p.add_argument('--mode', choices=['auto', 'keyword', 'semantic'], default='auto',
                   help='auto = keyword and semantic merged (default)')
    p.add_argument('--sort', choices=['relevance', 'cited', 'recent'], default='relevance')
    p.add_argument('--oa', action='store_true', help='open-access papers only')
    p.add_argument('--fulltext', action='store_true', help='keyword search in full texts too (noisy)')
    filters(p)
    p.set_defaults(fn=commands.find)

    p = sub.add_parser('cite', help='snowball from one paper')
    p.add_argument('id', help='DOI, OpenAlex id or title')
    p.add_argument('--dir', choices=['citers', 'refs', 'related'], default='citers')
    p.add_argument('--sort', choices=['cited', 'recent'], default='cited')
    filters(p)
    p.set_defaults(fn=commands.cite)

    p = sub.add_parser('paper', help='full record and abstract')
    p.add_argument('ids', nargs='+', help='DOIs, OpenAlex ids or titles')
    p.set_defaults(fn=commands.paper)

    p = sub.add_parser('read', help='read an open-access full text')
    p.add_argument('target', help='DOI, title or URL')
    p.add_argument('--find', action='append', help='terms to locate; repeat or separate with ";"')
    p.add_argument('-k', type=int, default=8, help='passages to show with --find (default 8)')
    p.add_argument('--max', type=int, default=12000, help='characters to print without --find')
    p.set_defaults(fn=commands.read)

    p = sub.add_parser('web', help='web search')
    p.add_argument('query')
    p.add_argument('--engine', choices=['auto', 'tavily', 'firecrawl', 'both'], default='auto')
    p.add_argument('--domains', help='comma-separated, e.g. echa.europa.eu,epa.gov')
    p.add_argument('--deep', action='store_true', help='Tavily advanced depth (costs 2 credits)')
    p.add_argument('-n', type=int, default=6)
    p.set_defaults(fn=commands.web_search)

    p = sub.add_parser('bib', help='BibTeX for DOIs')
    p.add_argument('dois', nargs='+')
    p.add_argument('--out', help='.bib file to append to (duplicates skipped)')
    p.set_defaults(fn=commands.bibtex)

    p = sub.add_parser('status', help='keys, cache, and a live check')
    p.add_argument('--check', action='store_true')
    p.set_defaults(fn=commands.status)
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
