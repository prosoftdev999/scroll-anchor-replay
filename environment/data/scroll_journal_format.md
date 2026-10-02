# Scroll crash-journal format

The renderer and browser processes each kept a small crash ring. The ordinary CSV exporter flushed independently, so an incident frame can have a newer scroll reconciliation in the ring than the row left in `frame_scroll_bindings.csv`. Healthy-session CSV records are complete. For `s-z62`, a broker-installed renderer transaction supersedes the CSV binding for the same renderer frame; otherwise the CSV row remains in force.

The two files use the same page framing:

- `scroll_journal.rbuf` is the renderer-side scroll journal.
- `broker_journal.rbuf` is the browser-side handoff journal.
- Page size is 768 bytes. Integers are little-endian.
- Each page starts with `<4sHHIHHI>`: magic `RBJ2`, physical page slot, page epoch, page write sequence, used payload bytes, flags, and CRC-32. `flags` is zero in this capture. The CRC-32 covers the first 16 header bytes followed by the used payload bytes. A page with a bad header, slot, bounds, flags, or CRC is not part of the recovered stream.

A valid page payload is a sequence of fragments. Every fragment starts with `<IHHBBHII>`: logical record sequence, fragment index, fragment count, codec, copy generation, fragment length, total encoded-record length, and CRC-32 of the decoded record body. Codec 0 stores the body directly; codec 1 stores a zlib stream. Records may span pages, and physical page order is unrelated to logical record order.

A crash can leave older copies of a fragment in the ring. For one `(logical sequence, fragment index)`, use the copy with the greatest tuple `(copy generation, page epoch, page write sequence, physical slot)`. Reassemble fragment indexes `0..count-1`, require the advertised encoded length, decode the selected codec, and verify the decoded-body CRC. Incomplete or corrupt logical records are ignored. The surviving record bodies are UTF-8 JSON objects and replay in ascending logical record sequence.

## Dictionaries and renderer transactions

`dict_reset` starts an integer-code dictionary epoch. `dict` records populate `(space, code)` within that epoch. Numeric codes are only meaningful inside their own dictionary epoch; the capture intentionally reuses codes after a reset.

Renderer changes are journal transactions. A transaction starts with `txn_begin`; the records that follow for that `(epoch, txn)` are its data until a terminal `txn_commit` or `txn_abort`. If more than one terminal record survived, the later logical record is the terminal state. A commit is usable only when its `count` equals the number of data records before that terminal record and its SHA-256 equals the digest of those data-record JSON bodies concatenated in logical-record order. For this digest, serialize each body as UTF-8 JSON with keys sorted and separators `,` and `:` and no added whitespace. Aborted, incomplete, or digest-invalid transactions do not install data.

Committed renderer transactions can contain `binding`, `reconcile`, `ack`, and `base` records. After dictionary expansion, they have the same semantics as `frame_scroll_bindings.csv`, `scroll_reconciliations.csv`, `scroll_ack_records.csv`, and `scroll_base_records.csv`. Their `version` is local revision metadata; it does not by itself mean that the browser displayed the transaction.

A `txn_commit` also carries a handoff token and handoff generation. Several checksum-valid renderer transactions can exist for one frame because the renderer can prepare replacements before the browser chooses one.

## Browser handoff state

`broker_journal.rbuf` uses its own dictionary epochs. Its `lease_open`, `accept`, and `revoke` records are timestamped on the browser's `broker_us` clock. `broker_clock_sync.csv` gives same-instant samples of renderer `comp_us` and browser `broker_us`; their relationship is stable and affine over this capture.

For a particular `(handoff token, handoff generation)` at a renderer-frame time, consider only broker records no later than that frame after converting clocks. The latest such broker record decides the state: `accept` means the renderer transaction is installed; `lease_open` or `revoke` means it is not. Handoff tokens are reused across generations, so generation is part of the identity.

A renderer transaction can affect a frame only if its reconciliation had already applied by that frame's `comp_us` and its handoff was installed at that frame time. The incident journal is constructed so that exactly one committed transaction is installed for each frame it supplements. Its binding then supersedes the CSV binding for that frame, and its reconciliation/ack/base rows participate in the same sparse parent-state and pending-input rules documented in `trace_format.md`.
