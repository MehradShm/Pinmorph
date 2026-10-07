# Phase 4 core walkthrough

The user explicitly requested the remaining implementation, so the marked learning cores
were implemented. This companion explains their statements in execution order. Read it
alongside the named functions rather than treating the generated code as a black box.
The separate training/CTR cores retain their own learning exercises.

## Stable experiment assignment — `experiments/assignment.py:assign_arm`

1. `json.dumps([user_id, name, salt, version], ...)` fixes both the inputs and their byte
   encoding. Compact separators and Unicode handling make the representation portable.
2. `.encode()` produces UTF-8 bytes; no process-dependent Python hash is involved.
3. `sha256(payload).digest()[:8]` selects the agreed portion of a stable digest.
4. `int.from_bytes(..., "big") % 10_000` maps it into a bounded integer bucket.
5. `boundary = 0` starts the first contiguous allocation interval.
6. `boundary += arm.buckets` advances its exclusive upper bound in configured arm order.
7. `bucket < boundary` selects the first containing interval; returning the arm supplies
   its name and ranker implementation together.
8. The final error is a guard; configuration validation already requires exactly 10,000
   allocated buckets. Golden buckets 1358, 6236 and 4510 test the encoding contract.

Alternative: persisted assignment supports migrations and sticky cross-experiment identities,
but adds storage and migration rules. At this scale deterministic hashing is sufficient.

Explain back: Why does changing the salt change assignment? Why is Python `hash()` wrong here?
What would you record if changing allocations while a study is running?

## Eligible catalog and baseline scores — `ml/baselines.py`

`CatalogCandidateSource.retrieve`:

1. Load the authenticated viewer so shared visibility checks can use their ID.
2. Select only ready pins with availability and creation no later than the request cutoff.
3. Apply both-direction blocks and the viewer's mutes through `visible_owner`.
4. Load hidden pin IDs separately; product hide state gates discovery.
5. The `counts` helper groups by pin and counts distinct users. Occurrence **and** receipt
   are strictly before `as_of`; a backdated late arrival and a tied boundary are excluded.
6. Call the helper for `Engagement.type == "save"` and for imported purchases separately.
   They retain different feature names and provenance rather than becoming fake views.
7. Build a Candidate for each eligible, unhidden pin with its source version.
8. Compute nonnegative hours since availability and attach the two historical counts.
   Board membership is intentionally absent from these historical ML counts.

`RecencyRanker.rank`:

1. Sort a new list by increasing age, then increasing pin ID for ties.
2. Use negative age as both rank score and initial final score; a newer pin scores higher.
3. Return RankedCandidate records without changing the input list or adding display position.

`PopularityRanker.rank`:

1. Add the separate save and imported-purchase counts with explicit equal weights.
2. Sort descending score, then increasing age and ID.
3. Return the score with the original candidate/features. With all-zero counts the tie
   rules become recency order. This is a proxy popularity baseline, not a CTR probability.

`IdentityReranker.rerank` copies the ranked list unchanged. That is a useful comparison
baseline when introducing diversity or creator caps later.

Explain back: Why must receipt time also be checked? Why does deleting a save from a board
not erase its recorded action? What would make imported purchases and app saves incomparable?

## Shared serving — `feed/service.py` and `feed/persistence.py`

`FeedService.serve`:

1. Assign the configured arm, then resolve its source/ranker/reranker through versioned
   registries. Unknown implementations fail at construction before accepting requests.
2. Retrieve candidates. The map keyed by pin ID prevents duplicate identity; a repeated
   candidate merges all source names instead of silently discarding attribution.
3. Rank the candidate values and pass the resulting list through the selected reranker.
4. Read saved optional interests. For this baseline, a matching interest word in title or
   description contributes one `interest_matches` feature.
5. Copy the candidate/features and score records, adding `matches * interest_boost` to the
   final score. Rank score retains the original baseline score.
6. Sort the boosted final scores deterministically. With no interests, use baseline order.
7. Record actual component versions and the assigned experiment arm, then call the common
   page helper. Both the interest selection and coefficient belong to the cursor context.

`page_candidates`:

1. Build a binding from user, surface, versions, config, context and arm.
2. Hash its canonical JSON, so a cursor cannot be applied to another user/surface/context.
3. Suppress exact pixel duplicates in rank order; retain the highest-ranked visible pin.
4. Decode the cursor fingerprint and bounded integer offset. Reject malformed or mismatched
   cursors with 422, including a crop or configuration change.
5. Slice the ranked pool and encode the next offset only if results remain.
6. Pass the slice and all provenance to `record_page`. No view is created here.

`record_page`:

1. Add FeedRequest containing request/user/surface, context, arm, versions and timing.
2. Flush it first so child records can reference it.
3. Enumerate this page from position zero and insert ServedItem with sources and scores.
4. Flush the items before adding their ServedFeature children.
5. Insert full feature snapshots with their schema version and cutoff time.
6. Commit all three record types together. Any error prevents a successful response and
   the Session closes/rolls back the unfinished transaction.
7. Only then serialize a FeedPage with request ID and explicit item positions.

Alternative: freeze a serving session's candidate list and features across pages. The current
small-scale baseline refreshes live data and can move items between page requests; this is
an explicit pagination limitation, not a claim of immutable sessions.

Explain back: Why persist before responding? Which records distinguish served from viewed?
How would you preserve a feed ordering while new saves are arriving?

## Idempotent events — `logging/service.py:EventIngestor.ingest`

1. Dump the validated discriminated event schema to JSON-compatible values.
2. Hash canonical payload JSON. Diagnostic client time participates in retry identity;
   the server receipt timestamp does not.
3. Derive a signed advisory-lock key from the event UUID and acquire a transaction lock.
   This serializes global ID reuse even when two different authenticated users submit it.
4. If a receipt already exists, compare both authenticated user and payload hash. Conflicting
   reuse raises EventConflict; an exact retry returns duplicate without another action/view.
5. Convert optional request/pin UUIDs to storage identities.
6. For an attributed event, lock its FeedRequest. Verify its user and the saved pin/position.
   Different view IDs for this same request are now serialized as well.
7. A direct action requires an existing pin but has no served-item attribution.
8. When an explicit impression reference is already known, check its kind, user, request,
   pin and position. A known mismatching reference cannot become a valid attribution.
9. Look up the canonical view for this served pin. A second view ID yields `duplicate_view`.
10. An action without a request is `unattributed`; an attributed action is accepted if the
    view/reference is present, otherwise pending. An unknown explicit reference stays pending.
11. Insert/flush the receipt before its view or action child. Effective event time is receipt
    time; an untrusted client cannot move ordinary events into the past.
12. For a first view, insert/flush Impression. For a repeated view ID, use the existing view.
13. Find pending engagements for the same user/request/pin/position. Reconcile only those
    with no explicit reference or a reference to this arriving view/alias ID.
14. A duplicate-view alias resolves to the original Impression; it never inflates view count.
15. For an action, preserve both the requested reference and resolved impression FK, with
    an explicit pending/attributed/unattributed status.
16. Commit the receipt and all reconciliation together, then return the ingestion outcome.
    There is no Save/Board mutation anywhere in this telemetry function.

The browser's ViewedPin component starts a timer only when the card crosses 50% visibility.
It cancels on lower visibility, document hiding or unmount; after 1000 ms it creates one ID
and retries that exact payload. Closeup/save/outbound actions carry the originating request
when available. A shareable direct link remains a valid unattributed closeup.

Explain back: Why do both event-ID and request locks matter? How can an action arrive before
its view? Why is an unviewed served pin not automatically a training negative?

## Following and public related pins — `ml/discovery.py`

`FollowingCandidateSource.retrieve`:

1. Load the viewer and followed creator IDs whose follows existed by `as_of`.
2. Join Saves → Boards → BoardFollows for that viewer. Require public boards and known
   follow/save/board creation times; apply block/mute rules to the board owner.
3. Reuse the eligible catalog source for pin-level availability/privacy and historical features.
4. For each eligible candidate, add `following:creator:v1` and/or `following:public-board:v1`.
5. Keep a single candidate carrying every contributing source. The API applies deterministic
   recency ranking and the common serving writer.

Alternative: fan-out on write makes reads faster, but publication changes, blocks, unfollows
and large-fanout creators require invalidation. This baseline computes the union on read.

`RelatedPinSource.retrieve`:

1. Find only visible public boards containing the context pin, with eligible save times.
2. Count distinct shared boards for other saved pins; exclude the context pin and future saves.
3. Join those counts conceptually to the shared eligible catalog pool. Hidden/blocked/muted
   and unavailable candidates never survive this step.
4. Copy features to add `shared_public_boards`, retain the co-board source and use count as
   retrieval score. Sort descending score, then ID.
5. If no eligible co-board result exists, load same-recipe catalog vectors.
6. Find the context pin's eligible vector; if absent, return an honest empty result.
7. Exact-search the other eligible vectors, preserve similarity/source/features, and use
   the common attributed serving path with the context pin recorded.

Explain back: Why are secret boards excluded even if the viewer owns one? What evidence
must be filtered before counting? When would similarity alone beat co-board counts?

## CLIP, exact search and HNSW — `infra/lens/server.py`, `ml/vector_store.py`, `ml/retrieval.py`

Encoder startup:

1. Read the local checkpoint and verify its SHA-256 before deserialization.
2. Load the verified JIT archive on CPU and rebuild the pinned CLIP architecture from its
   state dict. Use float32 and `eval()`; discard the temporary archive after setup.
3. Construct the checkpoint's bicubic resize/center-crop/tensor/RGB-normalization transform.
4. Build fixed safety prompt tokens once and normalize their text embeddings in inference
   mode. No request-time downloads, model training or random-vector fallback occur.

Image encoding:

1. Bound input bytes and decoded pixels, then convert validated transient pixels to RGB.
2. Apply evaluation preprocessing and add a batch dimension.
3. Acquire the small inference lock and use `torch.inference_mode()`.
4. `encode_image` computes the trained representation; normalize it by its L2 norm.
5. Return the declared image-only model recipe and 512 finite values.

Vector storage:

1. Hash the canonical catalog RGB pixels and check the `(pin, recipe, content_hash)` identity.
2. Encode only if that immutable content record does not exist.
3. Verify the runtime recipe/weight hash/dimension and serialize model registration with an
   advisory lock. Persist checkpoint/preprocess/text policy/image weight/runtime metadata.
4. Add the normalized vector with its known time. Pin publication and this vector commit
   in the media worker's transaction. Existing catalogs use explicit backfill.
5. Catalog vector reads filter ready/available/known state, recipe, viewer policy and hides;
   ordering by known time/hash picks one latest eligible revision per pin.

`normalize_vector` checks nonempty finite values, computes `math.hypot`, rejects zero or
nonfinite norm and divides each component. Cosine retrieval never treats a zero vector as
meaningful. The known `(3,4)` reference becomes `(0.6,0.8)`.

`ExactVectorRetriever.search`:

1. Reject nonpositive k and normalize the query.
2. Reject duplicate pin identity; skip other recipes and unavailable/not-yet-known items.
3. Reject a matching recipe with inconsistent dimension, then normalize its values.
4. Dot corresponding unit-vector values with strict dimension matching: this is cosine.
5. Sort descending similarity and ID ties, then slice top k. This is the correctness reference.

`PgvectorANNRetriever.search`:

1. Validate k/query norm and load the viewer.
2. Define a correlated `NOT EXISTS` to exclude a revision superseded by a later known
   revision of the same pin/recipe; content hash breaks known-time ties deterministically.
3. Cast vectors to the selected fixed dimension and use cosine distance `<=>`.
4. Filter recipe, dimension, known time, ready/available/created state, blocks/mutes and hides.
5. Set HNSW search breadth to 100 and enable strict iterative scanning after filters.
6. Order by cosine distance and limit k; the shipped recipe's partial expression index
   supports this ordering. PostgreSQL can prefer exact scanning on a very small table.
7. Convert distance to similarity and order returned ties by ID.

`LensService.search` encodes the prepared crop, obtains eligible baseline features, bounds
its candidate pool, chooses configured exact or ANN retrieval, and attaches similarity and
actual sources to matched candidates. The API pages/persists them through the common writer.
`eligible_lens_vectors` explicitly rejects duplicates and applies recipe/time filters.
`compare_lens_retrieval` rejects invalid k/duplicates, then divides top-k ID overlap by the
size of the exact top-k set; an empty reference is None, not a perfect score.

The measured report fixes corpus/version/crops and uses `perf_counter()` for elapsed timing.
ANN agreement is not labeled relevance. The tiny corpus produced perfect overlap while
exact computation was faster; that is useful evidence rather than a reason to hide a result.

Explain back: Why must catalog and crop recipes match? Why can exact search be faster here?
What could make a filtered HNSW result shorter than k, and how would you measure that?

## Upload holds and the remaining product modules

Pixel hashing applies orientation, flattens transparency and hashes dimensions plus RGB
pixels. It catches exact duplicates across file encodings. The DB uniqueness guard prevents
same-owner races; ranking suppresses same pixels across owners. It is not a perceptual hash.

The zero-shot safety gate compares the image to fixed unsafe/safe text vectors. Two explicit
conditions must hold: unsafe similarity ≥ 0.28 and its margin over best safe similarity ≥
0.03. A hold stores private variants and opens a report; it does not publish the pin. These
uncalibrated similarities need labeled evaluation before real safety use. Human reports,
reviewer authorization and audited remove/restore/dismiss decisions are separate modules.

URL import pins DNS-approved public IPs on each redirect while TLS verifies the original
hostname. It bounds response size/time and decodes the image before entering the upload
pipeline. Comments use ownership checks and plain React text rendering; likes have a
per-user/pin primary key; hiding filters discovery and supports restoration; share links
identify the pin. Notifications obey block/mute policy.

Daily digest preparation locks the user and uses a unique `(user, UTC date)` outbox identity.
Dispatch locks pending rows, rechecks opt-out/current visibility and sends to local Mailpit.
It commits delivered state after SMTP succeeds. A process crash after SMTP acceptance and
before commit can resend the message; a stable Message-ID helps diagnosis but does not
make SMTP exactly once.

Explain back: Why does an upload classifier hold need a review path? Which near duplicates
can pixel hashing miss? Why is SMTP delivery at least once despite an idempotent outbox?

## Revisit and discussion status

Revisits are fan-out versus read-time union, co-board versus similarity on fixed candidates,
learned interest/cold-start features, frozen feed sessions, larger-corpus ANN recall/latency,
image/title fusion, object-proposed crops, perceptual hashing, labeled safety evaluation and
provider/batched notification delivery. The user has not yet answered the explain-back
questions; learning discussion remains open without leaving the implementation unfinished.
