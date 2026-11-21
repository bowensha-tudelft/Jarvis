"""BibTeX from doi.org content negotiation (free, no key), tidied and appended without duplicates."""
import os
import re
import unicodedata

from . import net
from .openalex import norm_doi

TTL = 365 * 86400


def fetch(doi):
    doi = norm_doi(doi)
    try:
        text = net.request('doi.org', 'https://doi.org/' + doi, headers={'Accept': 'application/x-bibtex'},
                           ttl=TTL, raw=True, retries=1)
    except net.SourceError as e:
        if e.status == 404:
            raise net.SourceError('doi.org', 404, 'DOI not found: ' + doi)
        raise
    text = text.strip()
    if not text.startswith('@'):
        raise net.SourceError('doi.org', 200, 'no BibTeX for ' + doi)
    return tidy(text, doi)


def _ascii(s):
    return unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()


def tidy(text, doi):
    """One field per line, and a readable key: Surname2021FirstWord."""
    m = re.match(r'@(\w+)\{([^,]*),\s*(.*)\}\s*$', text, flags=re.S)
    if not m:
        return text
    kind, _, body = m.groups()
    fields = _split_fields(body)
    author = fields.get('author', '')
    surname = re.sub(r'[^A-Za-z]', '', _ascii(author.split(' and ')[0].split(',')[0])) or 'Anon'
    year = re.sub(r'\D', '', fields.get('year', '')) or 'nd'
    words = [w for w in re.findall(r'[A-Za-z]+', _ascii(fields.get('title', ''))) if len(w) > 3]
    key = '%s%s%s' % (surname, year, words[0].capitalize() if words else '')
    fields['doi'] = doi
    if 'pages' in fields:
        fields['pages'] = re.sub(r'\s*[‐-―-]+\s*', '--', fields['pages'])
    lines = ['@%s{%s,' % (kind, key)]
    for k, v in fields.items():
        if k == 'url' and 'doi.org' in v:
            continue        # the doi field already says this
        lines.append('  %s = {%s},' % (k, v))
    lines[-1] = lines[-1].rstrip(',')
    return '\n'.join(lines) + '\n}'


def _split_fields(body):
    """Parse `name={value}` / `name=value` pairs, braces nested."""
    fields, i, n = {}, 0, len(body)
    while i < n:
        m = re.compile(r'\s*,?\s*(\w+)\s*=\s*').match(body, i)
        if not m:
            break
        name, i = m.group(1).lower(), m.end()
        if i < n and body[i] == '{':
            depth, j = 0, i
            while j < n:
                depth += {'{': 1, '}': -1}.get(body[j], 0)
                if depth == 0:
                    break
                j += 1
            fields[name], i = body[i + 1:j], j + 1
        else:
            m2 = re.compile(r'[^,]*').match(body, i)
            fields[name], i = m2.group(0).strip().strip('"'), m2.end()
    return fields


def dois_in(path):
    try:
        with open(path, encoding='utf-8') as f:
            return {norm_doi(d) for d in re.findall(r'doi\s*=\s*[{"]([^}"]+)', f.read(), flags=re.I)}
    except FileNotFoundError:
        return set()


def append(path, entries):
    """entries: [(doi, bibtex)]. Skips DOIs already in the file. Returns (added, skipped)."""
    have = dois_in(path)
    new = [(d, b) for d, b in entries if norm_doi(d) not in have]
    if new:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        had_content = os.path.exists(path) and os.path.getsize(path) > 0
        with open(path, 'a', encoding='utf-8') as f:
            if had_content:
                f.write('\n')
            f.write('\n\n'.join(b for _, b in new) + '\n')
    return len(new), len(entries) - len(new)
