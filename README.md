# Jarvis

A [Claude Code](https://claude.com/claude-code) skill for literature research: scoping a topic and
finding evidence for claims while writing a paper. It combines four sources behind one script, so
the agent runs one command where it would otherwise juggle four tools:

- **OpenAlex** finds papers (title + abstract search) and walks citations
- **Firecrawl** adds semantic search over its paper index (with the matching passage from the full
  text), reads open-access full texts, and searches the web
- **Semantic Scholar** adds a one-line TLDR and influential-citation counts to every result
- **Tavily** searches the web alongside Firecrawl
- **doi.org** produces BibTeX

Python 3.8+ standard library only. Nothing to install.

## Install

```
git clone https://github.com/bowensha-tudelft/Jarvis.git ~/.claude/skills/jarvis
```

Claude Code picks it up automatically. Ask things like "scope the literature on X" or
"find evidence for this sentence", or type `/jarvis`.

## API keys

All optional except Tavily, but strongly recommended. Without an OpenAlex key, everyone behind
your network's IP shares one small daily budget. Put the keys in `~/.jarvis/config.json`, outside the skill folder,
so they are never committed:

```json
{
  "openalex_api_key": "",
  "s2_api_key": "",
  "tavily_api_key": "",
  "firecrawl_api_key": ""
}
```

Environment variables `OPENALEX_API_KEY`, `S2_API_KEY`, `TAVILY_API_KEY` and `FIRECRAWL_API_KEY`
override the file. Check with:

```
python ~/.claude/skills/jarvis/scripts/jarvis.py status --check
```

## Use without Claude

```
python scripts/jarvis.py find "cyclodextrin polymer PFAS adsorption" --years 2020-
python scripts/jarvis.py cite 10.1021/acscentsci.2c00478 --dir refs
python scripts/jarvis.py read 10.1021/acscentsci.2c00478 --find "ionic strength; short-chain"
python scripts/jarvis.py bib 10.1021/acscentsci.2c00478 --out refs.bib
```

`SKILL.md` documents every command and the two workflows. `references/sources.md` records how each
source was measured to behave and why they are combined this way.

## License

MIT
