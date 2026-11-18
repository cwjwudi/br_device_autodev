# Project variable catalog cache

`plc_search_variables` and `plc_list_variables` save the complete unfiltered catalog to
`<directory containing the .apj>/.br-auto-dev/plc_symbol_catalog.json`. Each entry includes
its PVI name and existing source, type, access-configuration and confidence fields. A query
returns only the requested page, plus `catalog_path` and `cache_status` (`rebuilt` or `hit`).
The cache is generated data and can be excluded from version control with `.br-auto-dev/`.

The running MCP server checks projects after their first catalog query, normally every two
seconds, and refreshes a changed catalog in the background. After the server stops, the next
query checks and refreshes it before use. Source files, project configuration and generated
variable headers are fingerprinted; updates, additions and removals invalidate the cache.
Source files and generated headers are content-hashed even if timestamps are preserved.
Other project assets use file size and modification time. A changed project source with
unchanged generated headers falls back to source scanning until artifacts are rebuilt.
Cache files are replaced atomically; an unstable project during indexing is retried and
then reported as an error. If background refresh fails, it is retried and logged to stderr;
the next query also rechecks the inputs.

The catalog describes source/build candidates, not a live PVI scan. Array elements and
structure members are not expanded into individual entries. Source scanning has low
confidence and can include variables not present on the running PLC. Search uses text
matching, not regular expressions, and the access filter reflects configured entries, not
live permissions. Verify selected addresses through PVI before use.
