# Shrink the game archive

`/app` holds a working lossless archiver for chess game collections in PGN format, and a
collection of games to develop against. Your job is to make the archives much smaller
without ever losing a byte.

## The contract

Two scripts define the interface. Both already exist and both must keep working.

    /app/compress.sh <input.pgn> <out_dir>
    /app/decompress.sh <out_dir> <output.pgn>

`compress.sh` reads a PGN file and writes whatever it likes into `out_dir`. `decompress.sh`
reads only `out_dir` and must write a file identical to the original — every byte, including
line breaks and the exact spelling of every move. A single differing byte scores zero, so
correctness is not something to trade away for size.

You may rewrite anything under `/app`, change the archive format entirely, add modules, or
replace the implementation language of the internals. The two script paths and their
argument order are fixed.

## What is here now

    compress.sh  decompress.sh     the interface
    selfcheck.sh                   round trip, size, and a score estimate
    pgnpack/                       the current implementation
    corpus/train.pgn               22,000 games to model on
    corpus/holdout.pgn             3,001 games to measure on
    scoring.json                   the two constants your score is computed from
    manifest.json                  hashes of every file shipped in this image
    README.md

The current implementation already does the one obvious thing. For each ply it transmits
the index of the played move within the list of legal moves in that position, sorted by
UCI, because both sides of the channel can generate that list from the position they
already share. With about 29 legal moves in a typical position that costs a little under
five bits, against roughly seven bytes for the text of the move.

It then throws away everything else it knows. Move indices are coded as though every legal
move in a position were equally likely, which is plainly false — most positions have one or
two moves a competent player would actually consider. The header block is handed to a
general-purpose compressor as one undifferentiated lump, so the fact that every game
carries a date, two ratings, a time control and an opening name in the same order is
rediscovered from scratch rather than exploited.

Both of those are where the remaining bytes live.

## Scoring

Your score is computed from one number: the total size of everything needed to rebuild the
graded collection.

    footprint = bytes in out_dir
              + bytes of any file under /app that differs from manifest.json

    ratio     = original_bytes / footprint

    score     = clamp((ratio - 12.243313) / (15.117072 - 12.243313), 0, 1)

The two constants are in `scoring.json`. The lower one is what the shipped implementation
achieves on the graded collection; matching it scores zero. The upper one is a ratio that
has been reached on that same collection, so the range is real rather than aspirational.
Partial progress counts in full — every byte you remove moves the score, and there is no
threshold below which improvement is wasted.

The second term of the footprint matters, and it is broader than it first looks. Anything
under `/app` that was not in the shipped image counts: a trained model, a dictionary, a
table of openings — and the code you write, too. Moving bytes between `out_dir` and a
source file changes nothing, which is the point. A model is not cheaper for being spelled
out as a Python literal.

Two practical consequences. Keep scratch files, logs and experiments in `/tmp`, because
anything left under `/app` is charged for. And delete what you no longer need — a training
script that has already produced its weights is not required to unpack anything, so
leaving it in place is a few thousand bytes of pure loss.

Failure is absolute rather than proportional: a rebuild that differs anywhere, a script
that exits non-zero, a crash, or a run that exceeds its time limit all score zero
regardless of how small the archive was.

## The collection you are scored on

It is not `corpus/holdout.pgn`, and it is not drawn from the same population. The games in
`corpus/` are from a general pool of club-strength players. The graded collection is from
substantially stronger players, with a different mix of time controls and games that run
noticeably longer. Openings, move choices, rating values and game lengths all shift.

A model tuned tightly to the local files will do worse there than it does here. Prefer
whatever generalises: the statistics of chess itself travel between populations, the exact
habits of one rating band do not.

## Working loop

    ./selfcheck.sh

packs `corpus/holdout.pgn`, rebuilds it, checks the two files are identical, and reports the
archive size, anything you have added under `/app`, and an estimated score. Run it after
every change worth keeping. It uses the same footprint rule the score does, so if it says a
change helped, the change helped.

`./selfcheck.sh --input FILE` runs against some other PGN, which is useful for fast
iteration on a small slice while a bigger idea is still settling.

Both directions have a time limit when the archive is graded: about forty minutes each for
a collection of twenty thousand games. Compression that takes an hour is worth nothing, so
keep an eye on how long `selfcheck.sh` reports, and remember the graded collection is larger
than the local holdout.

## Constraints

There is no network. Everything installed is already installed; `python-chess`, `numpy` and
`scipy` are available, along with the usual compression tools.

The rebuild must be deterministic. The same archive must produce the same output every
time, on a machine that has never seen the original — no clocks, no randomness that is not
seeded and stored, nothing read from outside `out_dir` and `/app`.

Do not modify anything under `corpus/`; those files are shipped image content and altering
them counts against your footprint.

## Pacing yourself

The budget is long and the system clock will not tell you where you are in it. `/app/.timer`
will:

    cat /app/.timer/remaining_secs

and `alert_30min`, `alert_10min` and `alert_5min` appear in that directory as the end
approaches. Check it before starting anything expensive — a full training run or a
compression pass over the whole corpus — and keep enough left at the end for one clean
`selfcheck.sh` on a tree you are happy to be graded on.

## How to work

Work alone and keep going; there is nobody to ask and no reason to stop early. Leave the
tree in a state that packs and unpacks correctly at all times, because a working archiver
that is only somewhat smaller scores, and a broken one scores nothing at all no matter how
promising the idea behind it was.

Take the largest remaining source of bytes first, and measure rather than assume — the two
places this format currently wastes space are not equally large, and neither is equally easy
to fix. When something does not pay for itself, revert it and take the next idea; a model
that costs more to store than it saves is a loss even when it predicts well.

Expect the last improvements to be harder than the first. There is real depth here: the
gap between coding a move as one of twenty-nine equally likely options and coding it as
what a chess player would actually expect is large, and closing it rewards better position
features, better use of what has already been seen in the game, and better handling of the
positions where the model is confidently wrong. When one direction stops paying, bank it
and move to another rather than polishing something that has stopped moving the number.
