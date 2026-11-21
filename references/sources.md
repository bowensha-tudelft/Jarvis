# Sources: what each one is for, measured

Measured 2026-11 against the live APIs, unless marked as carried over from AI en Man (2026-09/10).
Each verb has one core source; the others enrich it or stand in when it fails.

| Verb | Core | Added by the script |
|---|---|---|
| Find papers | OpenAlex keyword (title + abstract) | Firecrawl paper index + OpenAlex semantic, S2 TLDR; Crossref if OpenAlex's budget is gone |
| Check a remembered citation | Crossref `query.bibliographic` | OpenAlex details by DOI |
| Snowball | OpenAlex `cites:` / `referenced_works` / `related_works` | S2 TLDR |
| Read full text | OpenAlex's cached copy (GROBID TEI) | Firecrawl scrape of every free copy, published version first |
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
- **Coverage of preprints and new papers.** Five samples of 40 DOIs each, all 40/40 in OpenAlex:
  ChemRxiv newest (posted the day before), ChemRxiv random, ChemRxiv 30–45 days old, arXiv
  physics.chem-ph newest, arXiv physics.chem-ph 2023. Crossref lists 59,272 ChemRxiv DOIs (versions
  counted separately); 57,081 OpenAlex works have a ChemRxiv copy, 32,186 of them merged with the
  later journal article. So arXiv and ChemRxiv are not added as sources. ChemRxiv's own API answers
  403 behind a Cloudflare challenge anyway; Firecrawl can read its PDFs (46k characters).
- **Two kinds of 429.** `/rate-limit` lists per-second limits: 30/s overall, **1/s for semantic
  search**. Calling semantic search twice within a second returned 429 with $0.96 of the day left.
  The script retries, then asks `/rate-limit` (free) before saying the budget is gone.
- **Semantic search filters**: only `type`, `publication_year`, `is_oa`, `primary_location.source.id`,
  `has_abstract`, `has_fulltext`, `language`, `is_retracted`, `primary_location.license` and id
  filters. `is_paratext`, `raw_author_name.search` and `locations.source.id` return HTTP 400, so the
  script maps the source filter to `primary_location` and applies the author filter to the results.
- **Authors**: `raw_author_name.search:Grimme` 60 hits, "Stefan Grimme" 56, "S. Grimme" 2. Surnames only.
  Author names in the keyword query break it: "g-xTB tight-binding Grimme" found 1 unrelated paper.
- **Full text** (`content.openalex.org/works/<id>.grobid-xml`): cached PDFs and GROBID parses for
  60M+ open-access works, $0.01 each (about 100 a day on a free key). The g-xTB preprint: 128k
  characters with section headings in 0.5 s; an ACS Central Science article: 12 headings, 21
  paragraphs. Served gzip-compressed whatever the request says. GROBID leaves some sections without a
  heading; the script labels them rather than let them inherit the previous heading (an introduction
  paragraph was reported as "Abstract" before that fix).
- **Free copies**: of 50 open-access PFAS papers, 17 had more than one free copy and 30 had a
  repository copy. `locations[].version` says which: published, accepted or submitted (preprint).

## Crossref

- `query.bibliographic` matches loosely over authors, title, venue and year. "Dichtel 2017 Nature
  beta-cyclodextrin polymer PFOA" (the paper is in JACS): OpenAlex found 0, Crossref ranked the JACS
  paper first once its supporting-information DOI (`10.1021/jacs.7b02381.s001`, type `component`) was
  filtered out. "Grimme 2025 g-xTB general purpose extended tight-binding": the ChemRxiv preprint first.
- Free, no key, no daily budget. No arXiv (DataCite DOIs), abstracts only for some publishers, and
  `is-referenced-by-count` is Crossref's own count, lower than OpenAlex's (56 vs 100 for g-xTB).

## Semantic Scholar

- `/paper/search` is unusable without a key: 8 requests, 8 × HTTP 429 (AI en Man). It is never a
  search entry point.
- `POST /paper/batch` (up to 500 ids) works without a key: one call enriches a whole result list
  with `tldr`, `influentialCitationCount` and `openAccessPdf`.
- TLDRs are missing for many publisher papers (ACS often has none). Missing means empty, not an error.
- A batch in which S2 knows **none** of the papers (e.g. one ChemRxiv preprint) is answered with HTTP 400
  "No valid paper ids given", not with nulls. Treated as "no data".
- 429s come at random, with or without a key: at 3 s spacing `200, 200, 429, 200`; at 0.5 s
  `200, 200, 429, 200`. Retried with jittered back-off; a failure only drops the TLDRs.
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
