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
`recommended_max_memory()` of 12.71 GB. `dev/rehearse.js` against `DECIDER_MOCK=0 dev/run.sh`, stock trio:

| Occasion | Pick | Fits (tank / blazer / dress) | Margin | Model time | In the browser |
|---|---|---|---|---|---|
| Jantar romântico | blazer | 31 / 100 / 62 | 0.81 | 48.9 s | 49.6 s, the first decision after the load |
| Corrida no parque | plain tank | 58 / 0 / 0 | 0.94 | 12.6 s | 14.0 s |

`REHEARSAL OK`. Same picks as on CPU, fits within 3 points, margins within 0.03. Through the front door with
`curl` on the same load, 3 runs each: 3 looks 12.6 to 15.4 s for the dinner and 15.8 to 19.2 s for the run,
2 looks 10.1 to 13.4 s, one `/score` 7.4 to 7.8 s.

Cursor and one other agent session stayed open, and swap went from 3 GB to 11.8 GB while the model loaded,
so a quiet Mac should do a little better. No memory kill happened in this run.

What one look costs, timed in one process with the decider's own engine and questions, median of 3 runs after
a warm-up run:

| Questions | 512x512 photos | 512x288 frames, a webcam's shape |
|---|---|---|
| The 5 that `/choose` asks today | 4.15 s | 4.50 s |
| The fit question alone | 3.18 s | 2.55 s |
| Fit and person | 4.16 s | |

- The fit question alone gives the same level, to 2 decimals, as all 5 together.
- Time goes by pass through the model, not by size. One question is one pass and several are two, and the
  fit question alone still takes 2.41 s on 256 px photos (2.66 s at 384 px). Smaller photos also change the
  level (blazer 2.68 at 512 px, 2.36 at 384 px, 2.06 at 256 px), so the page keeps sending 512 px.
- The load takes about 88 s once the weights are cached. The first call after it takes 57 s and the next ones
  about 4 s. New image shapes later cost nothing visible (5.0 s and 4.5 s).
- With the model on MPS the process holds 10.73 GB. Loaded with the Podman VM (4.33 GB), Chrome and Cursor
  open, the Mac ran out of memory and macOS killed idle system daemons, twice
  (`JetsamEvent-2026-11-26-170105` and `-170126` in `/Library/Logs/DiagnosticReports`). No user process was
  killed. With Podman stopped and Chrome closed, the same load caused no kill. Close other apps before a
  Plan B run.
- CPU is no fallback on this Mac. In bf16 on 4 threads a 3-image request took 122.5 s and 149.4 s (machine
  under load), and float32 weights would be about 20 GB, more than the Mac has.

## Register

| # | Unknown | Verdict | Evidence |
|---|---|---|---|
| M1 | Decider E2B v2 accepts images | VERIFIED | Ran 22 images through `images` field |
| M2 | Decider E2B v2 judges outfits although v2 is trained on text only (model card) | VERIFIED on both labelled sets and their webcam-quality versions, INCONCLUSIVE on real webcam frames | Tables above |
| M3 | Decider E2B v2 fits a 24 GB L4 | INCONCLUSIVE, likely | 10.3 GB bf16 weights, card says one 24 GB GPU. 5.0 GB peak RAM on CPU because Gemma 4 E2B's per-layer embeddings are mostly untouched. It holds 10.73 GB on Apple MPS (M8); the L4 still needs a run |
| M4 | Decider E2B v2 image latency on L4 | INCONCLUSIVE | No GPU or AWS account here. Card: 62 ms per text question on H100. Builder Center: 131 ms for the v1 2B on ml.g6.xlarge, text only |
| M5 | Scores use the full 0 to 4 range | NOT VERIFIED | Both decision models stay between about 0.2 and 3.3. The page needs a linear stretch |
| M6 | SigLIP2 in the browser can drive the meter alone | NOT VERIFIED | Ranks stock styled photos well, cannot separate no person from plain clothes, and reversed a real pair of phone photos |
| M7 | Decider on CPU is fast enough for a live meter | NOT VERIFIED | 4.30 s at 2 threads, 2.62 s at 4. Fit: 0.94 s serial plus 6.7 s parallel, so about 2.0 s at Lambda's 6 vCPU (x86 estimate). On the Mac, 7.4 to 7.8 s per `/score` on MPS with the machine loaded, so the meter moves about every 8 s |
| M8 | Decider E2B v2 runs on the presenter's Mac over Apple MPS | VERIFIED | MacBook Air M4, 16 GB: `decider ready: StrandsAgents/strands-decider-E2B-gemma4-v2-2611 on mps`, 10.73 GB resident against a 12.71 GB MPS limit, `REHEARSAL OK` with the CPU picks. Other apps must be closed: with Podman, Chrome and Cursor open, macOS ran out of memory at load and killed idle system daemons twice |
| M9 | A 3-look decision on the Mac is fast enough for the talk | NOT MET with 5 questions | 12.6 to 15.4 s of model time for 3 looks once warm, 14.0 s in the browser. The fit question alone costs 2.55 s per look on webcam-shaped frames against 4.50 s for all 5, and gives the same level |
| M10 | The first decision after a load | VERIFIED, slow once | 57 s for the first call, about 4 s for the next. New image shapes afterwards cost nothing visible. Run one decision before the talk |
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
6. On the Mac, Plan B runs on MPS only, with other apps closed. The first decision after a load pays about 50 s
   once, so run one before the talk. Whether `/choose` should ask only the fit question is open (M9).
