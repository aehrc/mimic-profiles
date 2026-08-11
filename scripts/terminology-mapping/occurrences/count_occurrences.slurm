#!/bin/bash
#SBATCH --job-name=count-occurrences
#SBATCH --account=OD-221174
#SBATCH --time=2:00:00
#SBATCH --ntasks-per-node=1
#SBATCH --mem=503g
#SBATCH --cpus-per-task=64
#SBATCH --mail-type=BEGIN,END,FAIL
#SBATCH --mail-user=Felix.Naumann@csiro.au
#SBATCH --output=/scratch3/nau025/mimic-on-fhir-delta/occurrences/slurm-%j.out

set -euo pipefail

# Ten column-pruned scans with a small group-by each, plus three resource-level
# shape views and ONE JOIN (MedicationRequest -> Medication, following
# medicationReference). Measured: seven scans in 1m06s (2026-08-06), all ten plus
# the shapes and the join in 1m22s (2026-08-10), so the 2-hour default stands with
# room to spare. READ-ONLY — this job never writes to the warehouse.
#
# ONE TASK, 64 CPUS — not 64 tasks. All the work runs in a single local-mode JVM
# (see PYSPARK_SUBMIT_ARGS below), so the cores belong to one task; asking for 64
# tasks describes an MPI job this is not, and combined with --exclusive it left
# the job PENDING on Resources rather than scheduling.
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
