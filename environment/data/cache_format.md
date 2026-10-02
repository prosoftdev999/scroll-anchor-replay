# Retained measurement-cache capture

The embedded browser process persisted virtual-list measurement state in a LevelDB database. The database directory itself was not copied before the crash; support retained the two active **LevelDB log files** listed in `cache_log_manifest.csv`. Their physical records and WriteBatch payloads use the standard LevelDB log/WriteBatch format. Physical-record CRC32C values use LevelDB's normal masked CRC. A torn or checksum-invalid physical record is not part of the recovered logical log. WriteBatch sequence numbers are global database sequence numbers; entries in a batch consume consecutive sequence numbers. Later sequence numbers supersede earlier values for the same key, and a deletion removes that key until a later put.

The application keys recovered from that key/value history are:

- `meta/<generation>`: UTF-8 JSON with integer `generation_seq`, a `parent` generation token (empty for a root), and signed `origin_delta_css`.
- `patch/<generation>/<cache_token>`: UTF-8 JSON. `{"op":"set","height_css":...}` installs an absolute retained height for that token in the generation. `{"op":"clear"}` removes an inherited retained height for that token.

A cache generation inherits the fully resolved retained-height map and origin value of its parent, applies its own patch keys, then adds its `origin_delta_css` to the inherited origin. Generation ancestry is acyclic. `cache_token_lifetimes.csv` gives the time-qualified logical row identity of each cache token; the interval is inclusive in `generation_seq`, and tokens can be reused in a later, non-overlapping interval. `frame_cache_bindings.csv` associates renderer frames with the retained-cache generation carried by that frame.

For a bound renderer frame, retained heights replace the corresponding historical row heights **before** that frame's deferred scheduler commits are applied. The recovered retained origin is added to the frame's painted content offset. It does not change DOM `scrollTop`.
