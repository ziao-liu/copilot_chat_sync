# Source and Local Use

This is the unmodified OpenCodeReview delegation skill from
[alibaba/open-code-review](https://github.com/alibaba/open-code-review), commit
`cf64e7080f600d507888a26785ad6a8b7a13ab6a`, path
`skills/open-code-review-delegate/SKILL.md`. Its Apache-2.0 license is included here.
It is a development tool, not part of the installed Copilot Chat Sync application.

For this checkout, the official v1.12.7 Linux x64 CLI is installed at
`.tools/opencodereview/ocr` (gitignored). Its GitHub asset SHA256 is
`56649575421b8ca3be3cfaededc0a9037ae7cc9ae560f167bf504bfb4054451a`.

Use the project-local command in place of `ocr` in the skill. Delegation mode only
selects files and resolves rules; this assistant performs the review. It does not
make a separate LLM request or require an OCR API key. Do not run `ocr review` or
configure external providers without the user's approval.

The CLI requires Git 2.41+ for supported operation. The current environment's Git
2.39.5 warns but successfully produced preview/rule output; that is not a promise
that all OCR operations work with this older Git. No global software was changed.

Review tests, packaging recipes and documentation explicitly when OCR excludes
them. Record actual coverage and remaining platform validation in the review report.