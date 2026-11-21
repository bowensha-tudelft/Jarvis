"""GROBID TEI XML (OpenAlex's full-text parse) -> Markdown with section headings.

OpenAlex documents two shapes, from different GROBID versions: the standard `<TEI>` with
`<text><body><div>`, and an older `<html><body><tei>` wrapper whose divs hang directly off
`<text>`. So elements are matched by local name, case-insensitively, wherever they sit.
Reference lists are dropped: they are long and useless for finding a passage.
"""
import re
import xml.etree.ElementTree as ET


def _local(tag):
    return tag.rsplit('}', 1)[-1].lower() if isinstance(tag, str) else ''


def _text(el):
    return ' '.join(''.join(el.itertext()).split())


def _find_all(root, name):
    return [e for e in root.iter() if _local(e.tag) == name]


def to_markdown(xml):
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        # Not well-formed: strip tags rather than lose the text.
        return ' '.join(re.sub(r'<[^>]+>', ' ', xml).split())
    out = []
    header = next(iter(_find_all(root, 'teiheader')), None)
    if header is not None:
        title = next((t for t in _find_all(header, 'title') if _text(t)), None)
        if title is not None:
            out.append('# ' + _text(title))
        for ab in _find_all(header, 'abstract'):
            text = '\n\n'.join(_text(p) for p in _find_all(ab, 'p') if _text(p)) or _text(ab)
            if text:
                out.append('## Abstract\n\n' + text)
    for text_el in _find_all(root, 'text'):
        for part in text_el:
            name = _local(part.tag)
            if name == 'back':
                _divs(part, out, skip_refs=True)
            elif name in ('body', 'div'):
                _divs(part if name == 'body' else text_el, out)
                if name == 'div':
                    break      # old shape: divs directly under <text>, handled in one pass
    return '\n\n'.join(out).strip()


def _divs(container, out, skip_refs=False):
    for div in container:
        tag = _local(div.tag)
        if tag == 'figure':
            _figure(div, out)
            continue
        if tag != 'div':
            continue
        if skip_refs and (div.get('type') == 'references' or _find_all(div, 'listbibl')):
            continue
        # A section GROBID found no heading for would otherwise inherit the previous heading, and
        # a passage from the introduction would be reported as coming from the abstract.
        if not any(_local(c.tag) == 'head' and _text(c) for c in div):
            out.append('## (section without a heading)')
        for child in div:
            name = _local(child.tag)
            if name == 'head' and _text(child):
                out.append('## ' + _text(child))
            elif name == 'p' and _text(child):
                out.append(_text(child))
            elif name == 'formula' and _text(child):
                out.append('$$ ' + _text(child) + ' $$')
            elif name == 'figure':
                _figure(child, out)


def _figure(fig, out):
    head = ' '.join(_text(h) for h in _find_all(fig, 'head'))
    desc = ' '.join(_text(d) for d in _find_all(fig, 'figdesc'))
    rows = []
    for row in _find_all(fig, 'row'):
        cells = [_text(c) for c in row if _local(c.tag) == 'cell']
        if any(cells):
            rows.append('| ' + ' | '.join(cells) + ' |')
    kind = 'Table' if fig.get('type') == 'table' else 'Figure'
    if head or desc or rows:
        out.append('**%s** %s %s' % (kind, head, desc) + ('\n' + '\n'.join(rows) if rows else ''))
