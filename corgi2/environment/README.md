# molprop

Predict a molecular property from structure.

## What is here

    train.sh                 fit a model on data/train.csv and save it
    predict.sh <in> <out>    predict for a csv of SMILES
    selfcheck.sh             predict for data/dev.csv and report the error
    molprop/                 the current implementation
    data/train.csv           56,718 molecules with measured values
    data/dev.csv             10,681 more, held out
    scoring.json             the two numbers your score is computed from

## The property

`gap` is the difference between the highest occupied and lowest unoccupied molecular
orbital energies, in Hartree, computed with density functional theory. It is a property of
the electronic structure, so it depends on what is bonded to what — conjugation, ring
systems, the placement of heteroatoms — far more than on the formula.

## The current implementation

`molprop` counts characters in the SMILES string: how many carbons, how many `=`, how many
ring-closure digits. It then fits gradient boosting to those counts. It runs end to end and
it is not very good, because character counts cannot tell two molecules with the same
formula and different connectivity apart.

Reading the structure is the work.

## Measuring

    ./train.sh          # refit after changing how the model is built
    ./selfcheck.sh      # predict for the development molecules and score

`data/dev.csv` has at most one ring per molecule, exactly like `data/train.csv`. The
molecules you are scored on all have two or more. Treat the development score as a floor
rather than a forecast.
