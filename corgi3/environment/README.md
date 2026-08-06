# router

Shortest-path queries on a road network.

## What is here

    solve.sh <graph> <queries> <out>   answer a batch of queries   (this is what is timed)
    prepare.sh <graph>                 optional one-off work       (this is not)
    selfcheck.sh                       correctness + speed against the shipped router
    router/                            the current implementation
    data/road.gr.gz                    the network: 6,262,104 nodes, 15,248,146 arcs
    data/queries.dev.txt               21 queries to develop against
    .reference/                        a pristine copy of the shipped router

## The network

Standard DIMACS format. A `p sp N M` line, then one `a tail head weight` line per directed
arc. Weights are travel distances: positive integers. Node numbers are one-based. This is
the western United States.

## The queries

Three kinds, mixed in one file:

    P <source> <target>    the shortest distance between two nodes, or -1 if unreachable
    S <source>             the sum of distances from one node to everything it reaches
    B <source> <radius>    how many nodes lie within that distance of that node

They are not variants of one problem. What makes each fast is different, and a technique
that transforms one may do nothing at all for the other two.

## The current implementation

`router` runs Dijkstra with a binary heap. It is correct and it is slow. For `P` queries
the reason is that it does not know where the target is, and settles nodes in the wrong
direction because nothing distinguishes them. For `S` and `B` there is no target to know
about, and the cost is simply that every settled node costs a great deal more in
interpreted Python than it needs to.

## Measuring

    ./selfcheck.sh

runs both routers alternately and reports whether every answer still matches, along with
the ratio of medians. Alternating matters: run one after the other and any noise on the
machine lands entirely on whichever went second.
