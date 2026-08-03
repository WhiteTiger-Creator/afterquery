# pgnpack

A lossless archive format for chess game collections.

## What is here

    compress.sh <input.pgn> <out_dir>     pack an archive
    decompress.sh <out_dir> <output.pgn>  rebuild it, byte for byte
    selfcheck.sh                          round trip + size + score estimate
    pgnpack/                              the current implementation
    corpus/train.pgn                      games to model on
    corpus/holdout.pgn                    games to measure on
    scoring.json                          the numbers selfcheck scores against
    manifest.json                         hashes of the files shipped in this image

## The current implementation

`pgnpack` transmits, for each ply, the index of the played move within the list of legal
moves in that position, sorted by UCI. Both sides of the channel can generate that list,
so the move itself never travels. Indices are range coded as though every legal move were
equally likely, which costs about log2(29) bits per ply. Headers are handed to bzip2 as
one undifferentiated blob.

Both of those are placeholders for something better.

## Measuring

    ./selfcheck.sh

reports the archive size, anything you added under `/app`, whether the rebuild was exact,
and an estimated score. Both parts of the footprint count: bytes moved out of the archive
and into a source file are still bytes.

The holdout in `corpus/` is not the collection you are scored on. That one is drawn from a
different population of games — stronger players, different time controls, longer games —
so a model that fits the local files too closely will do worse there than here.
