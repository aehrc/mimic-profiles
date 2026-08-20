#!/bin/bash
#SBATCH --job-name=extract-value-shapes
#SBATCH --account=OD-221174
#SBATCH --time=2:00:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=12
#SBATCH --mem=160g
#SBATCH --mail-type=BEGIN,END,FAIL
#SBATCH --mail-user=Felix.Naumann@csiro.au
#SBATCH --output=/scratch3/nau025/mimic-on-fhir-delta/valueshapes/slurm-%j.out

set -euo pipefail

# Three column-pruned scans of Observation (461M rows) PER ELEMENT, two of which
# carry a wide group-by: the exact countDistinct of value_key per code, and the
# frequency-ranked value domain. READ-ONLY — this job never writes to the
# warehouse.
#
# Two elements since 2026-08-20, so six scans rather than three. The second is
# Observation.component.code and its three group-bys are trivial: 2 codes, one
# unit each, and no value domain at all (every component value is a Quantity, so
# value_key is null throughout and the third pass filters everything out). It
# adds scans, not shuffle. If a future element carries a real string domain,
# revisit the numbers below rather than assuming they still hold.
#
# SIZED DOWN 2026-08-20, from 4h / 64 cores / 503g exclusive. The measured basis:
# the previous full run over all 461,098,908 codings had Spark up at 20:30:24 and
# its outputs written by 20:33 — about three minutes of work, against a 4-hour
# request. Twelve cores is a fifth of the CPU, so the same work lands in the tens
# of minutes and 2 hours keeps a wide margin. Dropping --exclusive lets this
# share a node, which is the honest thing to ask for at this size; it also means
# the cgroup limit below is now real rather than notional, so the JVM heap has to
# stay under it.
DATA="/scratch3/nau025/mimic-on-fhir-delta/spark_warehouse"

module load python/3.12.3
module load amazon-corretto/21.0.0.35.1

# Local-mode driver is the whole job — all work runs in this one JVM, so these
# MUST track the #SBATCH request above rather than being tuned separately.
# `local[N]` is the thread count and driver.memory is the heap; leaving either at
# its old value under the smaller allocation is not a slow job but a dead one —
# local[64] on 12 CPUs is 5x oversubscription, and a 400g heap inside a 160g
# cgroup is an OOM kill once the JVM actually grows into it. `pyspark-shell`
# suffix is required.
#
# 128g of 160g is the same ~80% heap-to-allocation ratio the 400g/503g pair used.
# The remainder is not slack: it covers JVM metaspace, off-heap and direct
# buffers, and the Python process this script runs in.
#
# maxResultSize scaled with it. It is a ceiling on collected results, not an
# allocation, and every collect() here is bounded by distinct codes times a cap
# — a few thousand rows — so 8g is still far above anything this job returns,
# while no longer being a quarter of the heap.
#
# shuffle.partitions STAYS at 1024, raised over count_occurrences.py's 256: the
# value-domain group-by keys on (system, code, value) rather than (system, code),
# so its shuffle is orders of magnitude wider and 256 partitions would make each
# one large enough to spill. That is a statement about partition SIZE, not about
# core count — with less memory than before, fewer partitions would spill sooner,
# so this number wants to stay put even though there are now 12 cores to run 1024
# partitions across.
export PYSPARK_SUBMIT_ARGS="--master local[12] \
  --conf spark.driver.memory=128g \
  --conf spark.driver.maxResultSize=8g \
  --conf spark.sql.shuffle.partitions=1024 \
  --conf spark.default.parallelism=1024 \
  pyspark-shell"

# The REMOTE project's uv env (Python 3.12), never this repo's pyproject — and
# no `uv sync` here: compute nodes have no internet.
cd $SCRATCH3DIR/mimic-on-fhir-delta

uv run python3 -u valueshapes/extract_value_shapes.py \
  --data "$DATA" \
  --out-dir valueshapes
