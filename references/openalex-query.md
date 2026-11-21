# Writing good `find` queries

Keyword mode searches **titles and abstracts** in OpenAlex.

| Want | Write |
|---|---|
| all words (default) | `cyclodextrin PFAS adsorption` |
| exact phrase | `"cyclodextrin polymer" PFAS` |
| either term | `cyclodextrin AND (PFAS OR PFOA OR "perfluoroalkyl")` |
| exclude | `cyclodextrin PFAS NOT drug` |

`AND` / `OR` / `NOT` must be upper case. Measured on one topic: plain words 121 hits,
the phrase version 28, the OR version 148.

Tips:
- Abbreviations and full names are different words: include both (`PFAS OR "perfluoroalkyl"`).
- Too many hits: add a phrase, `--years`, or `--type review`. Too few: drop a word, use `OR`,
  or rely on the semantic half of `find` (it matches meaning, not words).
- Natural-language questions work best in `--mode semantic`.
- `--type` values: `article`, `review`, `preprint`, `book-chapter`, `dissertation`, `letter`, `editorial`.
- `--sort cited` favours old papers; combine with `--years` to find what is influential *recently*.
- Citation counts lag by months; for papers from the last year, `--sort recent` is more useful.
