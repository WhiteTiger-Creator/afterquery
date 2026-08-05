# Make the router fast without changing a single answer

`/app` holds a correct shortest-path implementation over a real road network, and it is
slow. Your job is to make queries much faster while every distance it returns stays exactly
as it is.

## The network

`data/road.gr.gz` is a road network in DIMACS format: 6,262,104 nodes and 15,248,146
directed arcs — the western United States. A `p sp N M` line gives the sizes, then one `a tail head weight` line per arc. Weights
are travel distances — positive integers — and node numbers are one-based.

Queries come in two kinds, and the file mixes them:

    P <source> <target>    the exact length of the shortest directed path, or -1 if none
    S <source>             the sum of the distances from that node to everything it reaches

They are not the same problem. A point-to-point query has somewhere to aim, and everything
that makes those fast works by not exploring in directions the answer never goes. A sweep
has no target at all: the whole reachable network has to be settled however clever you are,
so nothing that steers towards a destination helps even slightly. Both are timed together,
and the score is the total.

## The contract

Two scripts define the interface. Both already exist.

    /app/solve.sh <graph> <queries> <output>   answer a batch of queries
    /app/prepare.sh <graph>                    optional one-off work on the network

`solve.sh` reads a query file with one query per line and writes one line per query, in the
same order: the exact distance for a `P` query (`-1` if unreachable), the exact sum for an
`S` query. **Only `solve.sh` is timed.**

`prepare.sh` runs once before any timing, is not itself timed, and may write whatever it
likes under `/app`. It receives the network and nothing else — it never sees the queries, so
whatever it builds has to be useful for any of them. It has thirty minutes.

You may rewrite anything under `/app`, restructure the code, add modules, or compile an
extension; `numpy`, `cython` and a C compiler are all installed. The two script paths
and their argument order are fixed.

## Scoring

Correctness is a gate, not a component. Every distance must match the reference exactly.
One that does not scores zero, however fast it was produced — as do a crash, an unreadable
output file, the wrong number of lines, and a run that exceeds its limit.

Once every answer matches:

    score = 0.5 + 0.5 × (reference_time / your_time)

Matching the shipped implementation's speed scores 1.0. Twice as fast scores 1.5, four times
scores 2.5, ten times scores 5.5. There is no cap and no target to reach — every further
factor of speed is worth the same half point as the last, so there is no point at which
optimising stops paying.

## How the time is measured

The reference and your implementation are run **alternately**, three times each, over 66
queries on the network above — 60 point-to-point and 6 sweeps — and their **medians** are
compared. Interleaving them puts whatever else the machine is doing onto both sides rather
than onto one, and the median discards the worst of what remains. The reference is run from the verifier's own untouched
copy, so changing the code under `/app/router` affects only your side of the comparison.

Files written during a *timed* run are deleted before the next one — everywhere, not only
under `/app`. A cache in `/tmp`, `/dev/shm`, or anywhere else in the container is gone by
the next round, so answers computed once cannot be handed back free the second time. What
`prepare.sh` wrote is left alone; that is the intended place for precomputation.

Nothing survives preparation as a *process*, either. Whatever `prepare.sh` starts is stopped
before the first measurement, and anything a timed round leaves running is stopped after it.
Preparation has to leave its results on disk — a daemon holding the graph, or the answers,
in memory is not preparation.

## Where the time actually goes

The shipped implementation is Dijkstra with a binary heap, and its problem is not the heap.
It is that Dijkstra does not know where the target is. Asked for a route from one side of
the network to the other, it settles nodes in every direction at once, including all the
ones leading away from the destination, because nothing in the algorithm distinguishes them.
On a network of six million nodes, almost all of the work is exploring places the answer
never goes.

That is a well-studied problem with a well-studied set of answers, and the useful thing
about all of them is that they change which nodes get looked at, not which distances come
back. Some cost nothing up front. Others spend preparation time to buy much more at query
time, which is what `prepare.sh` is for.

There is also a second, independent axis: the inner loop is interpreted Python doing one
heap operation and one dictionary lookup per arc. That is a long way off what the same
algorithm costs in a compiled language, and both axes multiply.

## Working loop

    ./selfcheck.sh

runs the shipped router and yours alternately over `data/queries.dev.txt`, checks every
distance matches, and reports the ratio of medians and an estimated score. It uses the same
alternating method the real measurement does, so its verdict on whether a change helped is
trustworthy even when the machine is busy.

    ./selfcheck.sh --rounds 5        steadier medians, slower
    ./selfcheck.sh --queries FILE    a different query set

The development file has 22 queries (20 point, 2 sweep); the graded one has 66 (60 and 6)
on the same network. Fixed costs
you pay once — reading the graph, loading tables — are amortised over four times as many
queries there, so a change that trades start-up time for query time will look worse locally
than it really is. Worth generating your own larger query file to see that effect clearly:
any pair of node numbers between 1 and 6,262,104 is a valid query.

## Constraints

There is no network. Everything installed is already installed.

Answers must be exact. Not approximate, not heuristic, not "correct on the queries I tried":
the graded queries are different ones on the same network, and a bound that happens to hold
for short routes and fails for long ones will be found. If you use a lower bound to guide
the search, it must be admissible — never an overestimate — or the first answer off the heap
will not be the shortest.

`solve.sh` must be deterministic and self-contained: same inputs, same outputs, reading only
the graph, the query file, and what `prepare.sh` left behind.

Do not modify `data/`, and leave `.reference/` alone — it is the copy `selfcheck.sh` measures
you against.

## Pacing yourself

The budget is long and the system clock will not tell you where you are in it. `/app/.timer`
will:

    cat /app/.timer/remaining_secs

with `alert_30min`, `alert_10min` and `alert_5min` appearing as the end approaches. Check it
before anything expensive — the shipped router alone needs about eight minutes for the
development queries, and a preprocessing pass over six million nodes is longer still — and keep enough at the end to run `prepare.sh` and one clean
`selfcheck.sh` on a tree you are happy to be measured on.

Remember that whatever `prepare.sh` produces must be on disk when the timing starts. A
router that would be fast after preparation, in a workspace where preparation was never run,
is a slow router.

## How to work

Work alone and keep going; there is nobody to ask. Keep the router correct at every point:
a modest speedup that returns the right distances scores, and a brilliant one that returns a
wrong distance scores nothing at all. Check correctness after every change, not at the end —
an optimisation that quietly breaks one query in a thousand is much easier to find when you
have just made it.

Take the largest cost first and measure rather than assume, and watch which kind of query
your change actually helped. The two kinds reward different work, and a technique that
transforms one of them may do nothing at all for the other — at which point the other is
where all the remaining time is, and the next improvement is a different piece of work
rather than more of the last one.

Expect the last improvements to be harder than the first, and expect there to be more of
them than you think. There is no target here and no ceiling: the gap between exploring a
whole city and walking almost straight to the destination is large, and past that there is
still the gap between interpreted and compiled. When one direction stops paying, bank it and
take another.
