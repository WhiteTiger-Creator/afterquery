# cython: language_level=3, boundscheck=False, wraparound=False, cdivision=True
"""Dijkstra with a binary heap, compiled.

Exactly the algorithm the shipped router runs — same order of settling, same distances —
with the interpreter taken out of the inner loop. Everything is a typed C array and the
heap is hand-rolled over one, so a relaxation costs a few machine instructions instead of
a bytecode dispatch, a heap tuple allocation and a dictionary lookup.

Nothing here is clever. It is the same idea, made cheap.
"""

import numpy as np
cimport numpy as cnp
from libc.stdlib cimport malloc, free

cnp.import_array()

ctypedef cnp.int32_t I32
ctypedef cnp.int64_t I64

cdef long long INF = 9223372036854775807


cdef inline void _push(long long* hd, int* hn, Py_ssize_t* size, long long d, int node):
    cdef Py_ssize_t i = size[0]
    cdef Py_ssize_t parent
    hd[i] = d
    hn[i] = node
    size[0] = i + 1
    while i > 0:
        parent = (i - 1) >> 1
        if hd[parent] <= hd[i]:
            break
        hd[parent], hd[i] = hd[i], hd[parent]
        hn[parent], hn[i] = hn[i], hn[parent]
        i = parent


cdef inline void _pop(long long* hd, int* hn, Py_ssize_t* size, long long* od, int* on):
    od[0] = hd[0]
    on[0] = hn[0]
    size[0] -= 1
    cdef Py_ssize_t n = size[0]
    if n == 0:
        return
    hd[0] = hd[n]
    hn[0] = hn[n]
    cdef Py_ssize_t i = 0, left, right, small
    while True:
        left = 2 * i + 1
        right = left + 1
        small = i
        if left < n and hd[left] < hd[small]:
            small = left
        if right < n and hd[right] < hd[small]:
            small = right
        if small == i:
            break
        hd[small], hd[i] = hd[i], hd[small]
        hn[small], hn[i] = hn[i], hn[small]
        i = small


def sweep_batch(cnp.ndarray[I32, ndim=1] start,
                cnp.ndarray[I32, ndim=1] head,
                cnp.ndarray[I32, ndim=1] weight,
                cnp.ndarray[I32, ndim=1] sources,
                int n):
    """Sum of distances from each source to everything it reaches.

    No target, so nothing that steers towards one is any use; the whole reachable component
    has to be settled. All that is left to win is the cost of settling it.
    """
    cdef Py_ssize_t q, nq = sources.shape[0]
    cdef cnp.ndarray[I64, ndim=1] out = np.empty(nq, dtype=np.int64)

    cdef long long* dist = <long long*> malloc(n * sizeof(long long))
    cdef long long* hd = <long long*> malloc((2 * head.shape[0] + 16) * sizeof(long long))
    cdef int* hn = <int*> malloc((2 * head.shape[0] + 16) * sizeof(int))
    if dist == NULL or hd == NULL or hn == NULL:
        raise MemoryError()

    cdef I32* s_ptr = &start[0]
    cdef I32* h_ptr = &head[0]
    cdef I32* w_ptr = &weight[0]

    cdef Py_ssize_t size, i
    cdef long long d, nd, total
    cdef int u, v, src

    try:
        for q in range(nq):
            src = sources[q]
            for i in range(n):
                dist[i] = INF
            dist[src] = 0
            size = 0
            _push(hd, hn, &size, 0, src)
            total = 0
            while size > 0:
                _pop(hd, hn, &size, &d, &u)
                if d > dist[u]:
                    continue
                total += d
                for i in range(s_ptr[u], s_ptr[u + 1]):
                    v = h_ptr[i]
                    nd = d + w_ptr[i]
                    if nd < dist[v]:
                        dist[v] = nd
                        _push(hd, hn, &size, nd, v)
            out[q] = total
    finally:
        free(dist)
        free(hd)
        free(hn)
    return out


def ball_batch(cnp.ndarray[I32, ndim=1] start,
               cnp.ndarray[I32, ndim=1] head,
               cnp.ndarray[I32, ndim=1] weight,
               cnp.ndarray[I32, ndim=1] sources,
               cnp.ndarray[I64, ndim=1] radii,
               int n):
    """How many nodes lie within each radius. Bounded search: stop expanding past it."""
    cdef Py_ssize_t q, nq = sources.shape[0]
    cdef cnp.ndarray[I64, ndim=1] out = np.empty(nq, dtype=np.int64)

    cdef long long* dist = <long long*> malloc(n * sizeof(long long))
    cdef long long* hd = <long long*> malloc((2 * head.shape[0] + 16) * sizeof(long long))
    cdef int* hn = <int*> malloc((2 * head.shape[0] + 16) * sizeof(int))
    if dist == NULL or hd == NULL or hn == NULL:
        raise MemoryError()

    cdef I32* s_ptr = &start[0]
    cdef I32* h_ptr = &head[0]
    cdef I32* w_ptr = &weight[0]

    cdef Py_ssize_t size, i
    cdef long long d, nd, radius, reached
    cdef int u, v, src

    try:
        for q in range(nq):
            src = sources[q]
            radius = radii[q]
            for i in range(n):
                dist[i] = INF
            dist[src] = 0
            size = 0
            _push(hd, hn, &size, 0, src)
            reached = 0
            while size > 0:
                _pop(hd, hn, &size, &d, &u)
                if d > dist[u]:
                    continue
                reached += 1
                for i in range(s_ptr[u], s_ptr[u + 1]):
                    v = h_ptr[i]
                    nd = d + w_ptr[i]
                    if nd <= radius and nd < dist[v]:
                        dist[v] = nd
                        _push(hd, hn, &size, nd, v)
            out[q] = reached
    finally:
        free(dist)
        free(hd)
        free(hn)
    return out


def kth_batch(cnp.ndarray[I32, ndim=1] start,
              cnp.ndarray[I32, ndim=1] head,
              cnp.ndarray[I32, ndim=1] weight,
              cnp.ndarray[I32, ndim=1] sources,
              cnp.ndarray[I64, ndim=1] ks,
              int n):
    """Distance to the k-th closest node. Stop as soon as enough have been settled."""
    cdef Py_ssize_t q, nq = sources.shape[0]
    cdef cnp.ndarray[I64, ndim=1] out = np.empty(nq, dtype=np.int64)

    cdef long long* dist = <long long*> malloc(n * sizeof(long long))
    cdef long long* hd = <long long*> malloc((2 * head.shape[0] + 16) * sizeof(long long))
    cdef int* hn = <int*> malloc((2 * head.shape[0] + 16) * sizeof(int))
    if dist == NULL or hd == NULL or hn == NULL:
        raise MemoryError()

    cdef I32* s_ptr = &start[0]
    cdef I32* h_ptr = &head[0]
    cdef I32* w_ptr = &weight[0]

    cdef Py_ssize_t size, i
    cdef long long d, nd, k, settled, answer
    cdef int u, v, src

    try:
        for q in range(nq):
            src = sources[q]
            k = ks[q]
            for i in range(n):
                dist[i] = INF
            dist[src] = 0
            size = 0
            _push(hd, hn, &size, 0, src)
            settled = 0
            answer = -1
            while size > 0:
                _pop(hd, hn, &size, &d, &u)
                if d > dist[u]:
                    continue
                settled += 1
                if settled >= k:
                    answer = d
                    break
                for i in range(s_ptr[u], s_ptr[u + 1]):
                    v = h_ptr[i]
                    nd = d + w_ptr[i]
                    if nd < dist[v]:
                        dist[v] = nd
                        _push(hd, hn, &size, nd, v)
            out[q] = answer
    finally:
        free(dist)
        free(hd)
        free(hn)
    return out


def solve_batch(cnp.ndarray[I32, ndim=1] start,
                cnp.ndarray[I32, ndim=1] head,
                cnp.ndarray[I32, ndim=1] weight,
                cnp.ndarray[I32, ndim=1] sources,
                cnp.ndarray[I32, ndim=1] targets,
                int n):
    """Answer a batch of queries; returns int64 distances, -1 where unreachable."""
    cdef Py_ssize_t q, nq = sources.shape[0]
    cdef cnp.ndarray[I64, ndim=1] out = np.empty(nq, dtype=np.int64)

    cdef long long* dist = <long long*> malloc(n * sizeof(long long))
    cdef long long* hd = <long long*> malloc((2 * head.shape[0] + 16) * sizeof(long long))
    cdef int* hn = <int*> malloc((2 * head.shape[0] + 16) * sizeof(int))
    if dist == NULL or hd == NULL or hn == NULL:
        raise MemoryError()

    cdef I32* s_ptr = &start[0]
    cdef I32* h_ptr = &head[0]
    cdef I32* w_ptr = &weight[0]

    cdef Py_ssize_t size, i
    cdef long long d, nd
    cdef int u, v, src, dst
    cdef int found

    try:
        for q in range(nq):
            src = sources[q]
            dst = targets[q]
            if src == dst:
                out[q] = 0
                continue
            for i in range(n):
                dist[i] = INF
            dist[src] = 0
            size = 0
            _push(hd, hn, &size, 0, src)
            found = 0
            while size > 0:
                _pop(hd, hn, &size, &d, &u)
                if d > dist[u]:
                    continue
                if u == dst:
                    out[q] = d
                    found = 1
                    break
                for i in range(s_ptr[u], s_ptr[u + 1]):
                    v = h_ptr[i]
                    nd = d + w_ptr[i]
                    if nd < dist[v]:
                        dist[v] = nd
                        _push(hd, hn, &size, nd, v)
            if not found:
                out[q] = -1
    finally:
        free(dist)
        free(hd)
        free(hn)
    return out
