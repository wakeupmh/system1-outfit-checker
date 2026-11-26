# Unknowns register

Run on 2026-11-26, updated the same day. Each row is VERIFIED, NOT VERIFIED or INCONCLUSIVE, with its evidence.
Model numbers come from `bench/outfit_eval.py` on 4 CPU threads (no GPU in this environment), except the Mac
section, which ran on the presenter's MacBook Air M4.
Cloud facts come from the linked docs.

## Model results

Labelled set: 8 images with no outfit, 5 with sport or plain clothes, 9 styled fashion photos.
Pass: mean(none) < mean(plain) < mean(styled) and AUC(styled vs rest) >= 0.85.

| Model | none | plain | styled | AUC | CPU s/frame | Peak RAM | Result |
|---|---|---|---|---|---|---|---|
| Strands Decider E2B v2 (Gemma 4), bf16 | 0.67 | 1.57 | 2.95 | 1.00 | 2.52 | 5.0 GB | PASS |
| d1-2B, fp32 | 1.00 | 1.97 | 2.87 | 1.00 | 2.76 | not measured | PASS |
| SigLIP2 base zero-shot, fp32 | 0.69 | 0.66 | 3.02 | 0.97 | 0.24 | not measured | FAIL, none and plain tie |
| d1-omni-600M, fp32 | about 3 for every image | | | | 1.1 to 1.8 | | FAIL |

### Same-studio check

In the set above every styled image is a fashion photo and every other image is a COCO snapshot, so a
model could pass by detecting photo style. `bench/labels_same_studio.csv` holds 12 DeepFashion studio
photos with the same background and light: 6 plain outfits and 6 styled ones, labelled by eye.

| Model | plain | styled | AUC | CPU s/frame |
|---|---|---|---|---|
| Strands Decider E2B v2, 4 threads | 2.02 | 2.60 | 1.00 | 2.62 |
| Strands Decider E2B v2, 2 threads | 2.03 | 2.60 | 1.00 | 4.30 |
| d1-2B, 4 threads | 2.16 | 2.77 | 1.00 | 3.89 |
| SigLIP2 base | 1.28 | 2.16 | 0.94 | 0.24 |

All four rank the outfits, so photo style does not explain the first result. The gap between plain and
styled is about 0.6 of a level, which the page must stretch. Webcam frames of one person in three
outfits remain the final check.

### Webcam-quality proxy

`--webcam` puts each photo whole into a 640x480 frame on a wall-coloured background, then blurs it, dims
it and saves it as JPEG quality 35. Same models, same labels, 4 CPU threads:

| Model, set | Clean | Webcam-quality | AUC (styled vs rest) |
|---|---|---|---|
| Decider E2B v2, same studio | plain 2.02, styled 2.60 | plain 1.77, styled 2.51 | 0.97, one pair swapped |
| Decider E2B v2, mixed set | none 0.67, plain 1.57, styled 2.95 | none 0.60, plain 1.26, styled 2.60 | 1.00 |
| SigLIP2 base, same studio | plain 1.28, styled 2.16 | plain 1.27, styled 2.42 | 0.97 |
| SigLIP2 base, mixed set | none 0.69, plain 0.66, styled 3.02 | none 0.30, plain 0.34, styled 2.89 | 1.00 |

All four pass. Degrading the frames lowers scores a little but keeps plain and styled apart; the
same-studio gap for the decider grew from 0.58 to 0.74 levels. With the current stretch
(`LEVEL_LO` 0.5, `LEVEL_HI` 3.2) a plain outfit reads about 47 and a styled one about 74.

Decider took 5.5 to 6.2 s per frame here against 2.6 s on the 512 px images, likely because a 640x480
frame gives it more image to read (inferred, not measured). The app caps frames at 512 px.

These are still stock photos. Real webcam photos of the presenter (`--dir`) remain the final check.

### Two real phone photos

Two phone photos sent by the presenter, not committed: an athleisure outfit (track jacket, cap) and a
casual pastel one (floral jacket, wide trousers). Different people, one photo each, so a first signal only.

| Model | Athleisure | Pastel casual | Order |
|---|---|---|---|
| Decider E2B v2, as shot | 1.47 | 1.65 | right, 0.18 apart |
| Decider E2B v2, `--webcam` | 0.92 | 1.72 | right, 0.80 apart |
| SigLIP2 base | 2.33 | 1.09 | reversed |

- Through the whole app the meter read 37 and 43, and the facts were right: `athleisure`/`neutral` and
  `casual`/`pastel`.
- Real photos landed about one level below the stock styled photos (1.5 to 1.7 against 2.5 to 3.0). With
  `LEVEL_HI` 3.2 a good real outfit may never pass about 50 on the meter; recalibrate from presenter photos.
- SigLIP2 reversed the pair, so it is not a fallback for the score.

### The choose flow in a browser, real model, CPU

`dev/rehearse.js` drives Escolher o look in Chromium against `DECIDER_MOCK=0 dev/run.sh`:

| Occasion | Pick | Fits (tank / blazer / dress) | Margin | Model time |
|---|---|---|---|---|
| Jantar romântico | blazer | 34 / 100 / 60 | 0.81 | 34.1 s |
| Corrida no parque | plain tank | 60 / 0 / 0 | 0.97 | 28.3 s |

Through `curl` alone the same decisions take 13 to 16 s. With Chromium on the same 4 cores (camera stream
and animations at about 70% of a core) the model got about 2.2 cores and took twice as long. A laptop with
more cores, or Apple MPS (now picked automatically), should do better. The Mac is measured next.

### The choose flow on the presenter's Mac, real model, Apple MPS

MacBook Air (Mac16,12), Apple M4 with 4 performance and 6 efficiency cores, 16 GB of memory, macOS 26.6.2.
Python 3.14.6, torch 2.15.0, strands-decider 0.4.0. PyTorch picks `mps` by itself and reports a
`recommended_max_memory()` of 12.71 GB.

`dev/rehearse.js` against `DECIDER_MOCK=0 dev/run.sh`, stock trio, before and after `/choose` went from five
questions per look to the fit and `person`:

| Occasion | Pick | Fits (tank / blazer / dress) | Margin | In the browser, 5 questions | In the browser, fit and person |
|---|---|---|---|---|---|
| Jantar romântico | blazer | 31 / 100 / 62 | 0.81 | 49.6 s, the first decision after the load | 18.4 s, also the first |
| Corrida no parque | plain tank | 58 / 0 / 0 | 0.94 | 14.0 s | 7.8 s |

`REHEARSAL OK` both times, with the picks of the CPU run, fits within 3 points and margins within 0.03.
Through the front door with `curl`, 3 runs each:

| Request | 5 questions | Fit and person |
|---|---|---|
| 3 looks | 12.6 to 19.2 s | 6.3 s |
| 2 looks | 10.1 to 13.4 s | 4.2 s |
| `/facts` for 3 photos | not needed | 8.1 to 8.3 s |
| One `/score` | 7.4 to 7.8 s | 4.1 to 4.5 s |

The five-question numbers come from a Mac with Cursor and another agent session open and swap at 11.8 GB, the
others from a quieter one, so that table overstates the gain. The next one is measured within one load.

What one look costs, timed in one process with the decider's own engine and questions, median of 3 runs after
a warm-up run:

| Questions in the request | Quiet Mac, 512x512 | Loaded Mac, 512x512 | Loaded Mac, 512x288 |
|---|---|---|---|
| The fit alone | 1.8 s | 3.18 s | 2.55 s |
| The fit and `person` | 2.1 s | 4.16 s | |
| All 5 | | 4.15 s | 4.50 s |

- All of them give the same level, to 2 decimals.
- Time goes by pass through the model, not by how many questions a pass carries. `person` beside the fit costs
  0.3 s, and a smaller photo saves little: the fit alone still takes 2.41 s on 256 px photos and 2.66 s at
  384 px. Smaller photos do change the level (blazer 2.68 at 512 px, 2.36 at 384 px, 2.06 at 256 px), so the
  page keeps sending 512 px.
- The load takes 29 to 62 s once the weights are cached on a quiet Mac, about 88 s with the machine loaded. The
  first call after it takes 17 s (57 s loaded) and the next ones about 2 s, so the first decision in the browser
  costs about 18 s. New image shapes later cost nothing visible (5.0 s and 4.5 s).
- With the model on MPS the process holds 10.73 GB. Loaded with the Podman VM (4.33 GB), Chrome and Cursor
  open, the Mac ran out of memory and macOS killed idle system daemons, twice
  (`JetsamEvent-2026-11-26-170105` and `-170126` in `/Library/Logs/DiagnosticReports`). No user process was
  killed. With Podman stopped and Chrome closed, the same load caused no kill. Close other apps before a
  Plan B run.
- CPU is no fallback on this Mac. In bf16 on 4 threads a 3-image request took 122.5 s and 149.4 s (machine
  under load), and float32 weights would be about 20 GB, more than the Mac has.

**`person` stays in `/choose`.** Asked for its fit alone, the eight stock photos with no outfit in them
(`bench/labels.csv`, group none) are not held back. How many of them score above fit 25, and the highest level
among them:

| Way of asking | Dinner date | Morning run |
|---|---|---|
| The fit alone | 7 of 8, level 2.18 (fit 86) | 4 of 8, level 1.62 (fit 51) |
| The fit and `person` | 2 of 8, level 1.81 (fit 63) | 2 of 8, level 1.52 (fit 45) |
| The fit with "If no outfit is visible, pick the lowest level." added | 3 of 8, level 1.38 (fit 36) | 1 of 8, level 1.50 (fit 44) |

With `person`, the six photos with nobody in them score 0. The other two show a person (0.69 to 0.85), which
the first design let through as well: a plain tank and one of them tie for a morning run at level 1.5, and one
of them beats a blazer. The extra sentence holds back less and moves real looks by up to 0.2 of a level (the
dress 1.58 to 1.78 for a dinner date), so the wording stays as it is.

`bench/choice_eval.py --device mps` takes 2.5 minutes on the Mac. On its CPU the same table's rows took 122 to
149 s each, with the machine loaded. Asking one `choice` question over all three looks gives the same winner in
4 of 6 orders for each occasion, and slot 1 wins 8 of the 12 orders. Each look scored alone picks the blazer
for a dinner date (1.43 / 2.73 / 1.88, margin 0.85, in 7.4 s) and the plain tank for a morning run
(2.33 / 0.90 / 0.89, margin 1.43, in 6.5 s).

## Register

| # | Unknown | Verdict | Evidence |
|---|---|---|---|
| M1 | Decider E2B v2 accepts images | VERIFIED | Ran 22 images through `images` field |
| M2 | Decider E2B v2 judges outfits although v2 is trained on text only (model card) | VERIFIED on both labelled sets and their webcam-quality versions, INCONCLUSIVE on real webcam frames | Tables above |
| M3 | Decider E2B v2 fits a 24 GB L4 | INCONCLUSIVE, likely | 10.3 GB bf16 weights, card says one 24 GB GPU. 5.0 GB peak RAM on CPU because Gemma 4 E2B's per-layer embeddings are mostly untouched. It holds 10.73 GB on Apple MPS (M8); the L4 still needs a run |
| M4 | Decider E2B v2 image latency on L4 | INCONCLUSIVE | No GPU or AWS account here. Card: 62 ms per text question on H100. Builder Center: 131 ms for the v1 2B on ml.g6.xlarge, text only |
| M5 | Scores use the full 0 to 4 range | NOT VERIFIED | Both decision models stay between about 0.2 and 3.3. The page needs a linear stretch |
| M6 | SigLIP2 in the browser can drive the meter alone | NOT VERIFIED | Ranks stock styled photos well, cannot separate no person from plain clothes, and reversed a real pair of phone photos |
| M7 | Decider on CPU is fast enough for a live meter | NOT VERIFIED | 4.30 s at 2 threads, 2.62 s at 4. Fit: 0.94 s serial plus 6.7 s parallel, so about 2.0 s at Lambda's 6 vCPU (x86 estimate). On the Mac, 4.1 to 4.5 s per `/score` on MPS (7.4 to 7.8 s with the machine loaded), so the meter moves about every 4 s |
| M8 | Decider E2B v2 runs on the presenter's Mac over Apple MPS | VERIFIED | MacBook Air M4, 16 GB: `decider ready: StrandsAgents/strands-decider-E2B-gemma4-v2-2611 on mps`, 10.73 GB resident against a 12.71 GB MPS limit, `REHEARSAL OK` with the CPU picks. Other apps must be closed: with Podman, Chrome and Cursor open, macOS ran out of memory at load and killed idle system daemons twice |
| M9 | A 3-look decision on the Mac is fast enough for the talk | VERIFIED with the fit and `person` | 6.3 s of model time for 3 looks and 4.2 s for 2, 7.8 s in the browser, against 12.6 to 19.2 s with five questions. `/choose` asks the fit and `person`; `/facts` answers the other three facts when the stylist is asked (8.1 to 8.3 s for 3 photos). The first decision after a load is M10 |
| M10 | The first decision after a load | VERIFIED, slow once | 17 s for the first call on a quiet Mac, 57 s with it loaded, so the first decision in the browser takes 18.4 s (49.6 s with five questions). New image shapes afterwards cost nothing visible. Run one decision before the talk |
| M11 | Asking only the fit would let a photo with nobody in it win | VERIFIED, so `/choose` also asks `person` | The eight stock photos with no outfit reach level 2.18 and fit 86 for a dinner date, and one ties with a real look for a morning run. With `person` six of them score 0. Two show a person and still rank by fit, as in the first design. Table above |
| C1 | SageMaker scale-to-zero holds requests while at zero | NOT VERIFIED | "any attempts to invoke the endpoint will produce an error" [docs](https://docs.aws.amazon.com/sagemaker/latest/dg/endpoint-auto-scaling-zero-instances.html) |
| C2 | Scale up from zero is automatic | NOT VERIFIED | Needs a StepScaling policy and a CloudWatch alarm on `NoCapacityInvocationFailures`, plus MinInstanceCount 0. Same docs |
| C3 | Time to scale up from zero | INCONCLUSIVE | Docs say "several minutes" |
| C4 | GPU quota for ml.g6.xlarge endpoints on the account | INCONCLUSIVE | Often 0 on new accounts. Check Service Quotas now |
| C5 | ml.g6.xlarge price and region | VERIFIED | Public AWS Price List, SageMaker Hosting per hour: us-east-1 and us-west-2 $1.1267, eu-west-1 $1.2578, eu-central-1 $1.409, sa-east-1 $1.9152. ml.g5.xlarge us-east-1 $1.408 |
| C6 | AWS credits cover SageMaker | VERIFIED unless the credit lists eligible services | [AWS credits terms](https://aws.amazon.com/awscredits/) |
| C7 | AWS credits cover Hugging Face endpoints via Marketplace | NOT VERIFIED | Marketplace excluded "unless authorized by us". Same page |
| C8 | Lambda function URL works with only `lambda:InvokeFunctionUrl` | NOT VERIFIED | Since Oct 2025 new URLs also need `lambda:InvokeFunction` [docs](https://docs.aws.amazon.com/lambda/latest/dg/urls-auth.html) |
| C9 | Lambda request and response fit | VERIFIED | 6 MB each, frames are about 50 KB [limits](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html) |
| C10 | SageMaker custom container contract | VERIFIED | Port 8080, `/ping` and `/invocations`, `/ping` must pass within 8 minutes, model answers within 60 s [docs](https://docs.aws.amazon.com/sagemaker/latest/dg/your-algorithms-inference-code.html) |
| C11 | AWS credentials in this cloud session work | NOT VERIFIED | In the first session `sts get-caller-identity` returned InvalidClientTokenId. On the presenter's Mac there is no default profile, `my-sso-profile` (us-east-1) has an expired SSO session, and `gcloud` is not installed. C3, C4 and M3/M4 still need a login |
| G1 | Gemini free tier keeps inputs private | NOT VERIFIED | Free tier inputs are "used to improve our products" [pricing](https://aistudio.google.com/docs/pricing). Send text only |
| G2 | Gemini free tier rate limits | INCONCLUSIVE | No longer published as a table; per project in AI Studio |
| G3 | Cloud Run runs without a billing account | NOT VERIFIED | Billing account required even inside the free tier |
| G4 | Firebase Hosting needs a billing account | NOT VERIFIED (no account needed) | Spark: 10 GB storage, 360 MB per day [pricing](https://firebase.google.com/pricing) |
| G5 | ADK deploys to Cloud Run with an API key and no Vertex AI | VERIFIED from source, not deployed | google-adk 2.15.1 `deployers/_cloud_run_deployer.py` sets `GOOGLE_GENAI_USE_ENTERPRISE=1` unless overridden. Deploy with `--env GOOGLE_GENAI_USE_ENTERPRISE=0 --env GOOGLE_API_KEY=...` |

## What changes in the design

1. Decider E2B v2 is the model. It passed and it is Apache-2.0 on Gemma 4. d1-2B is the fallback.
2. A pure Lambda path exists. 5 GB peak RAM fits Lambda's 10 GB, and about 2 s per verdict at 6 vCPU is too
   slow for the live needle but fine as a verdict every few seconds. At $0.0000166667 per GB-second, a 2 s
   verdict at 10 GB costs about $0.00033, so 1,000 verdicts cost about $0.33. The weights (10.3 GB) exceed the 10 GB container
   image and `/tmp` limits, so they load from EFS. SigLIP2 in the browser moves the needle between verdicts.
3. The GPU path (SageMaker scale-to-zero) needs a quota check first, a warm-up step, and a Lambda that turns
   the error at zero into a "warming up" reply.
4. The page needs a linear stretch of the 0 to 4 level onto 0 to 100.
5. The stylist must receive text only, and Cloud Run needs a billing account even at $0.
6. On the Mac, Plan B runs on MPS only, with other apps closed, and the first decision after a load is slow
   once (18 s), so run one before the talk. `/choose` asks the fit and `person`, and `/facts` answers the other
   three facts when the stylist is asked (M9, M11).
