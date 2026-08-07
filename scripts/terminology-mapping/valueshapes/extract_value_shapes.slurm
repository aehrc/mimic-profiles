#!/bin/bash
#SBATCH --job-name=extract-value-shapes
#SBATCH --account=OD-221174
#SBATCH --time=4:00:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=64
#SBATCH --mem=503g
#SBATCH --exclusive
#SBATCH --mail-type=BEGIN,END,FAIL
#SBATCH --mail-user=Felix.Naumann@csiro.au
#SBATCH --output=/scratch3/nau025/mimic-on-fhir-delta/valueshapes/slurm-%j.out

set -euo pipefail

# Three column-pruned scans of Observation (461M rows), two of which carry a
# wide group-by: the exact countDistinct of value_key per code, and the
# frequency-ranked value domain. That is heavier than count_occurrences.py's
# seven small group-bys, so 4 hours rather than its 2. READ-ONLY — this job
# never writes to the warehouse.
DATA="/scratch3/nau025/mimic-on-fhir-delta/spark_warehouse"

module load python/3.12.3
module load amazon-corretto/21.0.0.35.1

# Local-mode driver is the whole job — all work runs in this one JVM. These are
# the resources for the 64-core / 503 GB node. `pyspark-shell` suffix is required.
#
# shuffle.partitions is raised over count_occurrences.py's 256: the value-domain
# group-by keys on (system, code, value) rather than (system, code), so its
# shuffle is orders of magnitude wider and 256 partitions would make each one
# large enough to spill.
export PYSPARK_SUBMIT_ARGS="--master local[64] \
  --conf spark.driver.memory=400g \
  --conf spark.driver.maxResultSize=32g \
  --conf spark.sql.shuffle.partitions=1024 \
  --conf spark.default.parallelism=1024 \
  pyspark-shell"

# The REMOTE project's uv env (Python 3.12), never this repo's pyproject — and
# no `uv sync` here: compute nodes have no internet.
cd $SCRATCH3DIR/mimic-on-fhir-delta

uv run python3 -u valueshapes/extract_value_shapes.py \
  --data "$DATA" \
  --out-dir valueshapes
