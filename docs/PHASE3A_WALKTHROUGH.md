# Phase 3A core walkthrough

This follows the meaningful statements in the implemented core. Read each function beside
its numbered explanation; constructors and contract declarations are covered in PHASE3A.md.
The developer asked for the core to be implemented, so the former TODOs are now working
reference implementations. Explain-back discussion remains open.

## 1. Pin encoding and storage

`ClipPinEmbedder.metadata` in `backend/app/ml/embeddings.py`:

1. Open a local HTTP client with a bounded timeout and no environment proxy.
2. Read `/health`; a failing service propagates an error.
3. Select the separate `personalization` recipe, not Lens's image-only recipe.
4. Compare version, architecture, checkpoint, hash, dimension, fusion and preprocessing/text
   policy against the configured values. Reject any mismatched field before inference.

`embed` returns an empty list without making a request for empty inputs. Otherwise it
validates metadata, sends each image/title to `/encode-content` in input order, validates
the returned version/dimension, normalizes its finite nonzero vector, and appends it.
It never returns a random fallback vector.

`encode_content` in `infra/lens/server.py`:

1. Use the existing image path to resize/center-crop/normalize pixels and obtain a normalized
   image vector from the verified model in evaluation/inference mode.
2. Encode the title with the checkpoint's tokenizer; retain up to 75 content tokens.
3. Add start/end tokens and pad the 77-token tensor. End-of-text is preserved when truncated.
4. Under the runtime's inference lock, encode and normalize the title vector.
5. Average image and title at equal weights; normalize the sum to return a unit direction.
   Normalizing each modality first stops its raw magnitude from changing the fusion weight.

`store_content_embedding` in `backend/app/ml/vector_store.py`:

1. Hash the title length, exact UTF-8 title and canonical image bytes. The length prefix
   removes ambiguity between title and pixel boundaries.
2. Take the transaction advisory lock; look up `(pin, recipe, content_hash)` and return
   unchanged for an existing record. This serializes v1 writes, including concurrent retries.
3. Verify runtime metadata; compare immutable model fields if the recipe is already
   registered, otherwise create that registration.
4. Encode and insert a new vector revision with its actual known time. Database checks
   enforce matching dimension and unit norm. The caller commits with the media result.

The upload job prepares EXIF-oriented, flattened, metadata-free pixels and writes both
independent recipes. Existing ready pins use the explicit backfill. The migration creates
the fused recipe's partial HNSW expression index; other model dimensions/spaces stay separate.

Explain back: why normalize before and after fusion? What changes require a new version?
Why would mixing Lens and fused vectors be an invalid experiment?

## 2. History availability and the user vector

`load_interactions` in `backend/app/ml/data.py`:

1. Read imported purchases independently of app saves, with exact import IDs and raw receipt.
2. Read only resolved/unattributed app actions, joining their canonical view and explicit
   reference receipt. Pending actions are not training/history inputs.
3. Set an action's known time to the latest required receipt. An impression alias may arrive
   after the canonical view, so the canonical receipt alone is insufficient.
4. Preserve the action's original receipt and occurrence. Mark a non-null run as simulator
   provenance; the app does not invent run IDs or simulation overrides.

`adapt_interactions`:

1. Keep declared source weights and labels known by the extraction cutoff.
2. Require an imported event to belong to an exact declared import run.
3. In historical source replay only, map known time to source occurrence while retaining raw
   receipt. Live and simulator actions keep their real known time.
4. Sort by source time and event ID; tied outcomes remain tied for feature filtering.

`eligible_history` and `MeanUserEmbedder.embed`:

1. Filter matching user, occurrence strictly before cutoff, and known time strictly before
   cutoff. Current-time ties, future actions and late receipts are excluded.
2. Sort newest first with deterministic event IDs; reject duplicate event identities.
3. If over N, take the Nth timestamp and keep the whole group at that boundary.
4. Empty history returns `None`, explicitly selecting cold-start behavior.
5. Require one model space/dimension, then allocate a zero vector of that dimension.
6. For each normalized pin vector, compute `2 ** (-relative_age / half_life)` and add its
   weighted values. Relative age removes a common factor and prevents all-old underflow.
7. A near-zero sum means cancellation: return `None`. Otherwise normalize the final vector.
   Dividing by total weight is unnecessary because the final normalization removes it.

Explain back: why does old occurrence not imply past availability? Why is N a soft cap?
What information would multiple user vectors retain that this mean loses?

## 3. Shared point-in-time features

`PointInTimeFeatures` in `backend/app/ml/features.py`:

1. Index catalog items by ID and reject duplicate catalog/event identities.
2. Build history only from prior known actions whose selected content is available at cutoff.
3. Encode that same history with the configured user policy.
4. Compute similarity by a dot product of normalized, compatible user/pin vectors; use zero
   if there is no user vector.
5. Compute age from availability, clamped at zero.
6. Count distinct prior saving users and purchasing users independently, with both occurrence
   and known time before cutoff. Multiple saves by one user do not increase popularity.
7. Count the eligible capped user-history events; return the five original feature values.

Offline examples and live candidates call this class. Scoring standardizes these values;
serving snapshots keep the originals. Integration acceptance compares served values against
the builder at the exact recorded cutoff. V1 repeatedly scans in-memory history for clarity;
a production feature store would aggregate/cache/index these queries.

Explain back: why are save/purchase counts separate? Which timestamp matters for late
reconciliation? How would you optimize this without changing its feature semantics?

## 4. Candidate retrieval and blending

`BlendedCandidateSource.retrieve` in `backend/app/ml/retrieval.py`:

1. Load eligible same-version vectors/history and compute the user vector.
2. Load the visible baseline catalog, including block/mute/hide and availability rules.
3. Fill the five features for vector-backed pins; unembedded pins can still enter through
   baselines with zero similarity/history features.
4. Order baseline popularity and recency lists and attach their actual source names.
5. If no user vector, return the configured fallback pool with an explicit cold marker.
6. Otherwise run the filtered HNSW query, map hits back to visible candidates and retain
   each ANN similarity as retrieval score.
7. Blend lists and prepend the actual blend version to their contributing sources.

`blend_candidates`:

1. Multiply pool size by the 70/15/15 shares, floor quotas, then assign remaining slots by
   largest fractional remainder with a stable source-order tie break.
2. Keep a dictionary keyed by pin ID. A repeated ID merges source names rather than adding
   another item. New IDs consume a slot while capacity remains.
3. Walk each source to fill its unique-item quota; overlap does not consume a new quota slot.
4. Walk sources again in declared order to fill shortages until pool/corpus exhaustion.

`PgvectorANNRetriever` matches the model/dimension partial index, filters availability and
visibility, and chooses latest known content revisions. `ExactVectorRetriever` normalizes
and compares the same eligible space as the correctness reference. Reported agreement is
separate from relevance, and forced-index measurements on 32 items do not prove scalability.

Explain back: what happens if ANN has only two hits? How are overlapping source contributions
retained? Why measure candidate recall separately from ranking quality?

## 5. Chronology, examples and fitting

`split_name`/`split_interactions` in `backend/app/ml/training.py`:

1. Use half-open train/validation/test intervals; exclude outside times.
2. Sort chronologically without shuffling. Equal occurrence times land in the same interval.

`build_examples`:

1. Check feature schema and unique input identities.
2. Keep declared purchase/save targets inside the splits; closeups/clicks can inform history
   but cannot become target positives.
3. Verify replay adaptation, exact imports and retained raw receipt; enforce extraction time.
4. Build the eligible same-version universe using content availability at target time; skip
   unavailable positives.
5. Exclude this target ID only. Do not remove pins because of tied or future outcomes.
6. Hash `(manifest seed, event ID)` to obtain a stable per-target seed; sample without
   replacement from the sorted universe and record any shortage.
7. Attach target provenance, source weight, seed and universe hash/count to the positive and
   sampled-unobserved negatives. Build each row's features at the target occurrence cutoff.

`fit_ranker`:

1. Select train and validation rows by time; never select final-test rows for fitting.
2. Reject empty/single-class training, bad C values, incompatible features and undeclared
   positive sources before creating a model.
3. Construct X in declared feature order, y and source weights. Fit `StandardScaler` using
   X_train only; transform it with those fixed means/scales.
4. Fit each declared C with seeded weighted logistic regression; treat failure to converge
   as an error instead of quietly exporting that model.
5. Transform validation using the already fitted scaler and measure weighted log loss.
6. Choose lowest validation loss, with smaller-C tie break. If validation is absent, use the
   declared smallest-C fallback and record that no validation selection occurred.
7. Bind the semantic model ID to manifest, train/validation rows, options, coefficients,
   intercept/scaling and library versions. Final-test changes cannot change this identity.
8. Export the ordered finite coefficients/scaling to the validated artifact. `track_training`
   records the MLflow run ID, manifest and exact returned artifact.

The CLI publishes a fresh immutable run directory, sample audit and final report. Artifact
bytes have their own SHA256 in the generated serving config. A new run can repeat the same
predictive model ID while having a different artifact hash due to run ID/training timestamp.
No fitting step activates a feed.

Explain back: why can a later-positive pin be sampled as a negative now? What breaks if the
scaler sees test rows? Why isn't the sigmoid score measured CTR?

## 6. Scoring, reranking, evaluation and activation

`LogisticRegressionRanker.rank` in `backend/app/ml/ranking.py`:

1. Extract every artifact feature in its saved order; reject nonfinite values.
2. Compute `intercept + sum(coef * (value - mean) / scale)` using saved train-only parameters.
3. Reject a nonfinite logit; calculate sigmoid with separate positive/negative branches to
   avoid exponential overflow.
4. Keep the original candidate and score, then sort by descending score and stable pin ID.

`DiversityReranker.rerank`:

1. Walk the already ranked list. Reject repeated pin IDs immediately.
2. Enforce the creator cap only for known owner IDs; unknown owners have no shared bucket.
3. Normalize available vectors and compare compatible spaces to retained vectors. Suppress
   cosine similarity at/above the threshold. Missing vectors still obey creator caps.
4. Retain the original scores and order, then update accepted creator/vector state. Serving
   assigns final positions afterward. Removing items can shorten the feed and lose targets.

`recall_at_k`, `ndcg_at_k` and `catalog_coverage` in `ml/evaluation.py` count unique hits,
binary discounted gain and eligible unique recommendations respectively. NDCG duplicates
receive gain once but keep their real positions. Nonpositive k/outside-catalog predictions
are errors; an empty target/catalog returns `None` instead of a fake zero observation.

`evaluate_ranker` in `ml/offline.py`:

1. Group final-test positives by user/time; filter the eligible catalog and target set.
2. Build every candidate's features strictly at that cutoff; prior evaluation events may
   update history, while the fitted model stays unchanged.
3. Give recency, popularity, similarity and logistic methods the identical candidate list;
   evaluate reranking separately and include the actual cold-fallback serving policy.
4. Record candidate fingerprints, targets, predictions and cold/warm cohort for each query.
5. Aggregate only defined queries, track unavailable targets and report eligible coverage.
   Refuse an empty eligible test task. MLflow receives the final metrics/report separately.

`FeedService` verifies artifact checksum, recipe/feature/history versions and registered
vector metadata before using its registries. Cold requests choose the actual baseline
ranker and record a reason; warm requests record the fitted model/hash. The shared writer
atomically saves request, items and original features, without inventing viewed impressions.
Changing the explicit config restarts serving with a different pipeline; rollback retains
historical requests and rejects cursors bound to a different configuration.

Explain back: why can diversity lower recall? Which method did best on the authored trace,
and why can't that answer establish real-user quality? How would you prove rollback from
the saved serving records rather than the visible order alone?

Revisit experiments: image-only/fused content; one/multiple interests; exact/HNSW shortlist
recall; alternate quotas; logistic/LightGBM; cap/threshold/MMR; real declared imports;
later simulator workloads for delayed events, saturation and model/config rollout.
