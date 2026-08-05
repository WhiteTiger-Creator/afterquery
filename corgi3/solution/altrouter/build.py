"""Compile the Cython router and cache the graph as typed arrays.

Both belong in preparation: compiling is a one-off, and so is turning the text of the
network into the int32 arrays the compiled code wants. The shipped router re-parses a
gzipped text file on every run, which is pure repeated cost.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
CACHE = Path("/app/model")


def compile_extension() -> None:
    setup = HERE / "setup_fast.py"
    # The include path has to go on the Extension itself; passing it to setup() alone does
    # not reach the compiler.
    setup.write_text(
        "from setuptools import setup, Extension\n"
        "from Cython.Build import cythonize\n"
        "import numpy\n"
        "ext = [Extension('fast', ['fast.pyx'], include_dirs=[numpy.get_include()])]\n"
        "setup(ext_modules=cythonize(ext, quiet=True),\n"
        "      script_args=['build_ext', '--inplace'])\n"
    )
    done = subprocess.run(
        [sys.executable, str(setup)], cwd=str(HERE), capture_output=True, text=True
    )
    if done.returncode != 0:
        raise RuntimeError(
            f"compiling the router extension failed:\n{(done.stdout + done.stderr)[-2000:]}"
        )


def cache_graph(graph_path: str) -> Path:
    sys.path.insert(0, "/app")
    from router.graph import load

    graph = load(graph_path)
    CACHE.mkdir(parents=True, exist_ok=True)
    out = CACHE / "graph.npz"
    np.savez(
        out,
        start=np.asarray(graph.start, dtype=np.int32),
        head=np.asarray(graph.head, dtype=np.int32),
        weight=np.asarray(graph.weight, dtype=np.int32),
        n=np.int32(graph.n),
    )
    return out
