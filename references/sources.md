# Sources: what each one is for, measured

Measured 2026-11 against the live APIs, unless marked as carried over from AI en Man (2026-09/10).
Each verb has one core source; the others enrich it or stand in when it fails.

| Verb | Core | Added by the script |
|---|---|---|
| Find papers | OpenAlex keyword (title + abstract) | Firecrawl paper index (semantic), Semantic Scholar TLDR |
| Snowball | OpenAlex `cites:` / `referenced_works` / `related_works` | S2 TLDR |
| Read full text | Firecrawl scrape of the OA copy | OA links from OpenAlex and S2 |
| Web | Tavily and Firecrawl, as peers | — |
| BibTeX | doi.org content negotiation | — |

## OpenAlex

- **`search=` searches full text.** Query "cyclodextrin polymer PFAS adsorption" sorted by citations:
  989 hits, first an unrelated photocatalysis review, then point-of-care diagnostics.
  `filter=title_and_abstract.search:` gave 41 hits, all on topic. So `find` uses the filter;
  `--fulltext` opts back in.
- The title/abstract filter accepts `AND`, `OR`, `NOT`, parentheses and `"phrases"`, and sorts by
  `relevance_score`. A comma would end the filter, so the script replaces commas with spaces.
- Keyword hits include data sets ("Code supporting the publication: ...") ranked near the top, so
  `type:!dataset,is_paratext:false` is always added.
- `search.semantic` returns about 50 results at most and cannot be sorted (with `sort` it returns 0).
- Pricing is per request (`meta.cost_usd` = 0.001). Without a key, one $0.10/day budget is shared
  with everyone on the same exit IP — on a campus network, about 100 requests a day for everyone.
  A free key (openalex.org/settings/api) gives $1/day of its own. The key is sent as
  `Authorization: Bearer`, which keeps it out of URLs and the cache.
- `best_oa_location` / `open_access.oa_url` is Unpaywall's data, so Unpaywall is not called separately.
- ACS abstracts arrive prefixed with "High Resolution Image Download MS PowerPoint Slide"; stripped.

## Semantic Scholar

- `/paper/search` is unusable without a key: 8 requests, 8 × HTTP 429 (AI en Man). It is never a
  search entry point.
- `POST /paper/batch` (up to 500 ids) works without a key: one call enriches a whole result list
  with `tldr`, `influentialCitationCount` and `openAccessPdf`.
- TLDRs are missing for many publisher papers (ACS often has none). Missing means empty, not an error.
- Citation contexts / intents / per-citation `isInfluential`: 0/25, 0/25, 1/25 filled (AI en Man).
  Not used.

## Firecrawl

- Paper index `GET /v2/search/research/papers?query=&k=` (PubMed, PMC, arXiv, bioRxiv, medRxiv) works
  without a key. It keeps the query's constraints where OpenAlex semantic drops them (asked about
  PFAS, OpenAlex semantic returned bisphenol-A papers; AI en Man), and it returns this year's papers.
- Each hit has `passage`, the paragraph that best matches the query, **only when the full text is in
  PMC**: 2 of 12 hits in the test query. The rest have title and abstract only.
- No venue or citation counts, so hits are looked up in OpenAlex by DOI (one request for up to 50).
- `POST /v2/scrape` reads HTML and PDF links into Markdown: an ACS Central Science article via its
  DOI link, 100k characters; an MDPI article, 105k characters in 4 s. A publisher landing page also
  scrapes "successfully", so `read` warns when no Introduction/Results/Conclusion heading is found.
- `POST /v2/search` (web) works without a key at lower limits. `402`/`403` = credits used up.

## Tavily

- Web search with a short generated answer. Needs a key. Its index differs from Firecrawl's, so
  `web` runs both when a Tavily key is set and merges by URL.
- The generated answer is shown as "unverified": it is a summary of the hits, not a source.

## doi.org

- `Accept: application/x-bibtex` returns BibTeX for Crossref and DataCite DOIs, free and keyless.
  The script reformats it one field per line, with keys like `Wang2022Tunable`, and `--` in pages.

## Not used, and why

- **MCP servers for each source**: their tool definitions load into every session (23k tokens of MCP
  tools in this user's context already), and combining them would be left to the model each time.
- **Firecrawl passage reads for paywalled papers**: empty for 0/3 paywalled chemistry papers (AI en Man).
- **Firecrawl `checkPromptInjection`**: rejected by `/v2/scrape` as an unknown key (AI en Man).
