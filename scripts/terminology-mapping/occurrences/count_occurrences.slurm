#!/bin/bash
#SBATCH --job-name=count-occurrences
#SBATCH --account=OD-221174
#SBATCH --time=2:00:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=64
#SBATCH --mem=503g
#SBATCH --exclusive
#SBATCH --mail-type=BEGIN,END,FAIL
#SBATCH --mail-user=Felix.Naumann@csiro.au
#SBATCH --output=/scratch3/nau025/mimic-on-fhir-delta/occurrences/slurm-%j.out

set -euo pipefail

# Seven column-pruned scans with a small group-by each; minutes of work, so the
# 2-hour default stands. READ-ONLY — this job never writes to the warehouse.
DATA="/scratch3/nau025/mimic-on-fhir-delta/spark_warehouse"

module load python/3.12.3
module load amazon-corretto/21.0.0.35.1

# Local-mode driver is the whole job — all work runs in this one JVM. These are
# the resources for the 64-core / 503 GB node. `pyspark-shell` suffix is required.
export PYSPARK_SUBMIT_ARGS="--master local[64] \
  --conf spark.driver.memory=400g \
  --conf spark.driver.maxResultSize=32g \
  --conf spark.sql.shuffle.partitions=256 \
  --conf spark.default.parallelism=256 \
  pyspark-shell"

# The REMOTE project's uv env (Python 3.12), never this repo's pyproject — and
# no `uv sync` here: compute nodes have no internet.
cd $SCRATCH3DIR/mimic-on-fhir-delta

uv run python3 -u occurrences/count_occurrences.py \
  --data "$DATA" \
  --out-dir occurrences
