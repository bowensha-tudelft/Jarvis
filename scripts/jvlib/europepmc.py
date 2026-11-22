"""Europe PMC: abstracts OpenAlex lacks, and free full texts from PubMed Central.

Measured 2026-11: OpenAlex has no abstract for most Elsevier papers (Water Research, J. Hazard.
Mater., Chemosphere), and a writer who used Jarvis dropped 4 papers for it. Europe PMC had the
abstract for all 5 papers tried (4 of them Elsevier or Nature). PMC full texts, author manuscripts
included (e.g. a Science paper as PMC8902460), come as JATS XML, free and with no daily budget, so
`read` tries them before OpenAlex's $0.01 copy. Coverage is life-science and environmental journals;
many chemistry journals are absent.
"""
import re
import urllib.parse
import xml.etree.ElementTree as ET

from . import net

REST = 'https://www.ebi.ac.uk/europepmc/webservices/rest/'
TTL = 30 * 86400
TTL_TEXT = 90 * 86400


def lookup(dois):
    """{doi: {'abstract', 'pmcid', 'in_pmc'}} for the DOIs Europe PMC knows. Never raises."""
    out = {}
    dois = [d.lower() for d in dois if d]
    for i in range(0, len(dois), 25):
        chunk = dois[i:i + 25]
        q = ' OR '.join('DOI:"%s"' % d for d in chunk)
        try:
            d = net.request('europepmc', REST + 'search?' + urllib.parse.urlencode(
                {'query': q, 'resultType': 'core', 'format': 'json', 'pageSize': 100}), ttl=TTL, retries=2, timeout=60)
        except net.SourceError:
            continue
        for r in (d.get('resultList') or {}).get('result') or []:
            doi = (r.get('doi') or '').lower()
            if doi in chunk and doi not in out:
                out[doi] = {'abstract': _clean(r.get('abstractText') or ''),
                            'pmcid': r.get('pmcid') or '',
                            'in_pmc': r.get('inEPMC') == 'Y' or r.get('inPMC') == 'Y'}
    return out


def _clean(s):
    return ' '.join(re.sub(r'<[^>]+>', ' ', s).split())


def fulltext(pmcid):
    """PMC full text as Markdown, or None."""
    try:
        xml = net.request('europepmc', REST + pmcid + '/fullTextXML', ttl=TTL_TEXT, raw=True, timeout=90, retries=1)
    except net.SourceError:
        return None
    return jats_to_markdown(xml) or None


def _local(tag):
    return tag.rsplit('}', 1)[-1] if isinstance(tag, str) else ''


def _text(el):
    return ' '.join(''.join(el.itertext()).split())


def jats_to_markdown(xml):
    """JATS article -> Markdown: title, abstract, sections with headings, figure/table captions.
    The reference list is dropped (long, and useless for finding a passage)."""
    xml = re.sub(r'<!DOCTYPE[^>]*>', '', xml, count=1)
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return ' '.join(re.sub(r'<[^>]+>', ' ', xml).split())
    out = []
    t = next((e for e in root.iter() if _local(e.tag) == 'article-title'), None)
    if t is not None:
        out.append('# ' + _text(t))
    for ab in (e for e in root.iter() if _local(e.tag) == 'abstract'):
        text = '\n\n'.join(_text(p) for p in ab.iter() if _local(p.tag) == 'p' and _text(p)) or _text(ab)
        if text:
            out.append('## Abstract\n\n' + text)
        break
    body = next((e for e in root.iter() if _local(e.tag) == 'body'), None)
    if body is not None:
        _walk(body, out, 2)
    return '\n\n'.join(out).strip()


def _walk(el, out, depth):
    for c in el:
        name = _local(c.tag)
        if name == 'sec':
            title = next((x for x in c if _local(x.tag) == 'title'), None)
            out.append('#' * min(depth, 6) + ' ' + (_text(title) if title is not None and _text(title) else '(section without a heading)'))
            _walk(c, out, depth + 1)
        elif name == 'p' and _text(c):
            out.append(_text(c))
        elif name in ('fig', 'table-wrap'):
            label = ' '.join(_text(x) for x in c if _local(x.tag) in ('label', 'caption'))
            if label:
                out.append('**%s** %s' % ('Table' if name == 'table-wrap' else 'Figure', label))
        elif name in ('list', 'disp-quote', 'boxed-text'):
            _walk(c, out, depth)
