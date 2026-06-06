This folder contains the raw structured source for the coding problem catalog RAG.

Recommended model:

- one JSON file per company
- each file contains an array of problems
- each problem is retrieval-friendly and self-contained

Current schema:

- `id`
- `title`
- `company`
- `difficulty`
- `prompt`
- `constraints`
- `examples`
- `starter_template`
- `expected_topics`
- `style_tags`
- `complexity_target`
- `edge_case_hints`

`starter_template.kind` can be:

- `function`
- `class`

The backend expands these templates into per-language starter code at load time.

Good public sources for expanding this dataset later:

- https://github.com/neenza/leetcode-problems
- https://context7.com/liquidslr/leetcode-company-wise-problems
- https://huggingface.co/datasets/whiskwhite/leetcode-complete

When importing from external sources, keep the public dataset only as inspiration or metadata input and normalize the final problems into this app-specific JSON format.
