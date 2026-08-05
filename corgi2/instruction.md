# Predict the electronic gap from molecular structure

`/app` holds a working but crude pipeline that predicts a quantum-chemical property of
small organic molecules, and a collection of molecules to fit it on. Your job is to make it
substantially more accurate on molecules unlike the ones it was trained on.

## The property

`gap` is the energy difference between a molecule's highest occupied and lowest unoccupied
molecular orbital, in Hartree, from a density-functional calculation. It is a property of
the electronic structure: conjugation, aromatic systems, ring strain and where the
heteroatoms sit all move it. Two molecules with identical formulas and different
connectivity can have very different gaps.

## The contract

Two scripts define the interface. Both already exist and both must keep working.

    /app/train.sh                          fit a model, leave it on disk
    /app/predict.sh <input.csv> <out.csv>  predict for a csv of molecules

`predict.sh` receives a csv with a single `smiles` column and no measured values. It must
write a csv with columns `smiles,gap` containing exactly one row per input row, in the same
order, each `gap` a finite number. Anything else scores zero: a missing row, a reordered
row, a value that will not parse, a crash, or a run that exceeds its limit.

Only `predict.sh` is run when the work is scored. Whatever `train.sh` produces must already
be on disk by then, so refit before you finish. You may restructure anything under `/app`,
add modules, change the model, or replace the pipeline entirely; the two script paths and
their arguments are fixed.

## What is here now

    train.sh  predict.sh          the interface
    selfcheck.sh                  predict for the development molecules and score
    molprop/                      the current implementation
    data/train.csv                56,718 molecules with measured values
    data/dev.csv                  10,656 more, held out from training
    scoring.json                  the two numbers your score is computed from

The current implementation counts characters in the SMILES string — carbons, nitrogens,
`=` signs, ring-closure digits — and fits gradient boosting to those seventeen counts. It
runs end to end and it is a poor model, for a reason worth being precise about: character
counts cannot distinguish molecules that share a formula but differ in what is bonded to
what, and the gap depends almost entirely on that. The string is a description of a graph;
nothing in the pipeline currently reads it as one.

No cheminformatics toolkit is installed and there is no network, so building a
representation from the raw SMILES is part of the work. `numpy`, `scipy`, `scikit-learn`
and `joblib` are available.

## Scoring

Your score comes from the mean absolute error of your predictions on a collection of
molecules you have not seen.

    score = clamp((0.017082 - mae) / (0.017082 - 0.014000), 0, 1)

Both constants are in `scoring.json`. The upper error is what the shipped pipeline achieves
on that collection; matching it scores zero. The lower one has been reached on the same
collection, so the range is real rather than aspirational. Partial progress counts in full —
every reduction in error moves the score, and there is no threshold below which improvement
is wasted.

## The molecules you are scored on

They are not `data/dev.csv`, and they are not drawn from the same region of chemical space.
Every molecule in `data/` has **at most one ring**. Every molecule you are scored on has
**two or more** — fused systems, bridged systems, spiro centres, and the strain and
conjugation patterns that come with them.

This is the whole difficulty of the task. A model fitted to acyclic and single-ring
molecules has never seen a fused aromatic system, and gradient boosting in particular
cannot extrapolate past the range of the leaves it was fitted on. Representations and
models that merely interpolate well on the development set will lose much of their apparent
advantage on the graded one. Prefer whatever transfers: substructures that recur across
both regions, features whose meaning does not change when a second ring appears, and models
that degrade gracefully rather than confidently off-distribution.

## Working loop

    ./train.sh          # refit after changing how the model is built
    ./selfcheck.sh      # predict for data/dev.csv, check the format, report the error

`selfcheck.sh` applies the same format checks the scoring does — row count, ordering, finite
values — so a run that passes locally will not be rejected on a technicality. It also prints
an estimated score, which is optimistic by construction: the development molecules have at
most one ring, like the training ones. Read it as a floor on your error, not a forecast.

`./selfcheck.sh --input FILE` scores against any other labelled csv, which is useful if you
carve out your own harder split — and carving one is probably a good idea, since the gap
between the development molecules and the graded ones is exactly what you are trying to
close.

Prediction has a time limit of one hour for roughly sixty-six thousand molecules when the
work is scored. Featurisation that takes a millisecond per molecule is fine; anything much
slower is not. Training has no limit beyond your own budget, but it comes out of it.

## Constraints

There is no network. Everything installed is already installed.

Prediction must be deterministic: the same molecules must produce the same numbers every
time. Seed anything stochastic and store the seed. Be careful with hashing — Python salts
string hashing per process, so a feature built on the builtin `hash()` will silently land in
different buckets at training time and prediction time, and the model will appear to work
until the moment it is scored.

Do not modify anything under `data/`.

## Pacing yourself

The budget is long and the system clock will not tell you where you are in it. `/app/.timer`
will:

    cat /app/.timer/remaining_secs

and `alert_30min`, `alert_10min` and `alert_5min` appear in that directory as the end
approaches. Check it before starting anything expensive — a full refit over the training set
is minutes, a careless featurisation sweep is not — and keep enough left at the end to refit
and run one clean `selfcheck.sh` on a tree you are happy to be scored on.

## How to work

Work alone and keep going; there is nobody to ask. Leave the pipeline in a state that
trains and predicts correctly at all times, because a model that is only somewhat better
still scores and a broken one scores nothing at all.

Measure rather than assume. The obvious first move is a better representation, and it will
help — but which representation, at what resolution, is an empirical question, and the
answer on the development molecules is not automatically the answer on the graded ones. When
you add capacity and the development error falls while the gap to the graded regime widens,
you have made things worse in the way that matters.

Expect the last improvements to be harder than the first. There is real room here: the
difference between counting symbols and understanding structure is large, and closing it
rewards better substructure features, better handling of rings the training data never
contained, and models chosen for how they fail rather than how they fit. When one direction
stops paying, bank it and take another rather than polishing something that has stopped
moving the number.
