# router

Shortest-path queries on a road network.

## What is here

    solve.sh <graph> <queries> <out>   answer a batch of queries   (this is what is timed)
    prepare.sh <graph>                 optional one-off work       (this is not)
    selfcheck.sh                       correctness + speed against the shipped router
    router/                            the current implementation
    data/road.gr.gz                    the network: 264,346 nodes, 733,846 arcs
    data/queries.dev.txt               60 queries to develop against
    .reference/                        a pristine copy of the shipped router

## The network

Standard DIMACS format. A `p sp N M` line, then one `a tail head weight` line per directed
arc. Weights are travel distances: positive integers. Node numbers are one-based.

## The current implementation

`router` runs Dijkstra with a binary heap. It is correct and it is slow, and the reason is
worth stating plainly: it does not know where the target is. Asked for a route across the
network it will settle nodes in the wrong direction first, because nothing in the algorithm
distinguishes progress towards the destination from progress away from it.

Fixing that is the whole job, and none of the ways of fixing it change a single answer.

## Measuring

    ./selfcheck.sh

runs both routers alternately and reports whether every distance still matches, along with
the ratio of medians. Alternating matters: run one after the other and any noise on the
machine lands entirely on whichever went second.
