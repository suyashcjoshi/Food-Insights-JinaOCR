# **Turn Images & PDFs into searchable text with Jina OCR: A/V Script**

**Author:** Suyash  
**Reviewers:** Carly, Arturo, Rob  
**Status:** v1: 4/11/2026, v2: 6/11/2026, v3 (draft revision): 10/11/2026

## **Overview**

A practical explainer built around a small demo app: photograph a food label on your phone, read it with jina-ocr-v1 running on the Elastic Inference Service (EIS), store the result in Elasticsearch Serverless, and search every label you have read, by words or by meaning, in any language.

The video shows the one API call behind it, explains why a small specialised model suits this job, and walks through storing and searching the result. It names the rough edges briefly and shows how the app is designed around them.

Timing: `document_extraction` is in preview on Elasticsearch Serverless. **[VERIFY with the PM: the release or version this ships in before saying anything about "9.6" or "GA".]** Until confirmed, say "preview" on screen and "at the time of recording".

**Demo App:** [https\://github.com/suyashcjoshi/Food-Insights-JinaOCR](https://github.com/suyashcjoshi/Food-Insights-JinaOCR)  
**Console and Discover code:** `docs/kibana-demo.md` in the repo (every request in it was run against a real project).

## **Target viewers**

**Primary**: Backend and search developers who already use or are evaluating Elasticsearch and have a backlog of images and PDFs that search can't read, and who are currently stitching together OCR libraries or vision LLM calls.

**Secondary**: Developers who are interested in OCR solutions but are not Elastic users.

## **Core viewer promise**

Read a label with one API call inside Elasticsearch, store it, and search it in any language, and see how the app handles the rough edges.

## **Suggested YouTube titles**

> 1. Small Model, Right Job: OCR Inside Elasticsearch with jina-ocr-v1 **[CHECK: v2 says "Right Row", a typo?]**  
> 2. Stop Sending Labels to an LLM: Jina OCR on EIS, Explained  
> 3. Read Any Food Label, in Any Language: Jina OCR + Elasticsearch

("Tested" is removed from title 2 and the "measured comparison" is removed from the overview: no head-to-head against general models was run, so the video shouldn't promise one.)

## **Search term suggestions**

Jina OCR; jina-ocr-v1; Elastic Inference Service; EIS; document_extraction; OCR Elasticsearch; nutrition label OCR; document parsing small model; semantic_text; Jina embeddings; Elasticsearch Serverless; inference endpoint

## **Recording & Editing checklist**

> * **Rig:** overhead camera on an arm for hands and packs, locked focus and exposure, taped marks on the counter; face camera at eye level; both roll continuously and are in sync.  
> * **Phone:** screen recorded natively over an HTTPS tunnel and composited; never filmed from above. **Warm the endpoint before every take** (the first call after idle takes minutes).  
> * **Screen:** Kibana Console at two or three zoom steps; filter the response to the Markdown in `content`. Light or dark mode for the app chosen once and never mixed.  
> * **Names:** use exact product names on screen and in audio: Elastic Inference Service (EIS), Elasticsearch Serverless, Kibana Console, Discover, ES|QL, the `.jina-reader` endpoint.  
> * **Props (all must appear in a scene):** the protein bar, the sugar packet, the **German chocolate** (foreign language) and the **crumpled bar** (odd shape). Open Food Facts images only where named, attributed.  
> * **Lower thirds:** "Preview" on the Extract call; "Open weights, non-commercial licence" on the model card.  
> * **Pacing:** jump cut loading; cut between phone and explanation every 20–30 seconds in the app section; record in segments.  
> * **Tone:** calm, candid, no hype. Never dismissive of general models. No health advice: the app reads labels, never advises.  
> * **Design:** Elastic brand guidelines; pencil-and-paper look for animations, consistent with previous videos. Architecture diagram: `docs/architecture.svg`.

## **Section 1: Hook, Teaser & Introduction ~00:00 - 00:40**

Goal: Grab attention with a real practical problem and set up what's coming with OCR.

| Scene & Notes | Visual | Verbal |
| :---- | :---- | :---- |
| **The Problem** | Talking to camera, holding up food items. Cut to a close-up of the protein bar and the sugar packet. | This protein bar looks healthy. But does it fit my carb limit for today? The answer is on the label. Somewhere. And this sugar packet? Apparently I need a magnifying glass for my coffee. Even when I can read the numbers, I still have to add them to everything else I've eaten. So I built an app to help. |
| **Solution teaser** | Split layout. Chapter heading top right. Screen recording of the demo app (Capture, then the Result with big net carbs). Presenter on the right. | All I do is take a photo. It reads the label, and my day's numbers add up. |
| **Intro** | Lower third (name, title). Animation of the core elements: the architecture diagram. | Hi, I'm Suyash. Let's use Jina OCR on the Elastic Inference Service to turn labels like these into text, bring that into Elasticsearch, and search it, in any language. |

## **Section 2: Why reading a label is tricky ~00:40 - 1:25**

Goal: make the problem concrete in under 45 seconds, and plant the "big model?" question without arguing it yet.

| Scene | Visual | Verbal |
| :---- | :---- | :---- |
| **What OCR is** | Animation: a photo turning into text. | The first step is OCR: optical character recognition. It turns text in an image into text our software can work with. |
| **Three challenges** | Three quick animations, one per line of the verbal: (1) glare on a shiny wrapper; (2) a crumpled bar with a fold hiding half a word; (3) a Japanese pack next to a German one. | But labels are hard. The print is tiny, and the wrapper reflects the light. A fold can hide half a word. And the layout is different on every pack, in whatever language the maker picked. So we need something accurate, quick, and cheap enough to call many times from an app. |

## **Section 3: Meet jina-ocr-v1 and the app ~1:25 - 3:00**

Goal: explain in plain terms what this model is and how the pieces fit, in three beats.

| Scene | Visual | Verbal |
| :---- | :---- | :---- |
| **The model** | Card: jina-ocr-v1 and "Open weights, non-commercial licence". Hugging Face page screenshot. | That's the job for Jina OCR. It's a small model built for reading documents: an image goes in, formatted text comes back, with tables and reading order intact. The weights are open, with a non-commercial licence. On Elastic you reach it through EIS, with an endpoint called `.jina-reader`. **[VERIFY: wording on licence vs. using it through EIS, with Elastic comms.]** |
| **Architecture, three beats** | Architecture diagram (`docs/architecture.svg`). Highlight each part as it's named: the Jina OCR box, then the app's INGEST, then SEARCH. | Here's the whole app, in three steps. Extract: the app sends the photo to Jina OCR on EIS, and Markdown comes back in a few seconds, with nothing for us to deploy. Ingest: the app saves what it read in Elasticsearch. Search: we query it. One thing to know: the reader only returns text. It never stores anything. Saving is a separate call, and we'll do it together. |
| **Preview note** | Lower third: "Preview". | This API is in preview at the time of recording, so details may change. |

## **Section 4: Demo, one clean run ~3:00 - 8:00**

Goal: show the end-to-end flow with the phone app, Kibana Console, and Discover, one arc, never repeating a step. All requests: `docs/kibana-demo.md`.

| Scene | Visual | Verbal |
| :---- | :---- | :---- |
| **4.1 Scan, foreign language** | Phone: photograph the German chocolate (front, then back), tap Read label. Result sheet appears. | Let's read a German chocolate bar. I take the front and the back, and tap Read label. A few seconds later, there are the numbers, from a language I don't read. |
| **4.2 The call** | Kibana Console. Type `GET _inference/_all`, point at `.jina-reader`. Then `POST _inference/document_extraction/.jina-reader` with one image (a URL here for readability). Lower third: Preview. | Here's what the app sent. It's one POST to the document_extraction endpoint. The image can be a URL or a base64 data URL, as in the app. There's no prompt to write. You can send PDFs too, and for scanned PDFs you add a preset for OCR. I'm using images today. |
| **4.3 The response** | Console response, filtered to `content`. Photo beside it. | And back comes Markdown, one result per input, in the same order. Let's check it against the photo. There's no token count in the response today, so I can't tell you what a label costs. |
| **4.4 Store** | Console: `PUT food_labels_demo` with the mapping (point at `semantic_text`), then `PUT .../_doc/...` with the Markdown. Then `GET food_labels_demo/_mapping` (point at the Jina embeddings model). Index diagram on screen. | The OCR call stored nothing. So we create an index. The field `meaning` is `semantic_text`, and that's all it takes: Elasticsearch embeds the text itself, using a Jina embeddings model, with nothing else to set up. Then we index the document. That create is one time only. |
| **4.5 Search by words** | Phone Library, or Console: search for a word that only the English label has. Then the German word. | Search by words finds labels that contain the word. A German label says Zucker, not sugar, so searching for sugar misses it. **[REHEARSE: pick words that give a clean miss and hit.]** |
| **4.6 Search by meaning** | Phone: tick "Search by meaning". Or Console: the `semantic` query. Results from different languages. | Now by meaning. The same question finds the German and French labels too, because it ranks by what the text means, not the exact word. And it's the same search API. Only the query changes. **[REHEARSE: the demo needs several labels indexed; `make seed` gives 50.]** |
| **4.7 One honest limit** | Result sheet: "Unverified text" and the edit field. Lower third: "64% of values matched across 50 photos in 7 languages". | The model isn't perfect. Where a photo is cut off, it can invent words. So the app keeps ingredients and allergens as unverified text, and I can fix any number by hand. It's a reader, not a safety check. |
| **4.8 Add to today** | Phone: stepper, "Add to today", then the Today tab: net carbs vs. my limit, calories. | Now I say how much I ate, and add it to today. The limit is mine, and the app only compares numbers. It never tells me what to eat. |
| **4.9 Discover** | Discover, ES\|QL: latest labels with parsed numbers and read time, then today's totals from `food_log`. | Back in Kibana, Discover shows everything the app saved: the labels, how long each read took, and what I ate today. |

## **Section 5: Why a small model for this job ~8:00 - 9:00**

Goal: answer the question the viewer has held since Section 2, without bashing anyone and without claims we haven't measured.

| Scene | Visual | Verbal |
| :---- | :---- | :---- |
| **Why not a general model** | Split view, presenter. | You may be wondering why not use a general-purpose model. A frontier model can read this label, and I'm not saying otherwise. But reading a label is one narrow job. Jina OCR is built for exactly that: no prompt to write, a few seconds per read, and it runs on Elastic's side, so there's nothing for us to deploy. For this step, a specialised tool fits. |
| **Elastic context** | Diagram: full integration. | And reading is only half the job. To put the label in the context of my day, the app stores it, searches it, and adds it up, all through Elastic APIs, in one project. |
| **Try PDFs** | Short Console shot: `"type": "pdf"` with the `preset: "ocr"` setting. | The same call works on PDFs, with an OCR preset for scans. **[REHEARSE or cut: not run on screen yet.]** |

## **Section 6: Recap and CTA ~9:00 - 10:00**

| Scene | Visual | Verbal |
| :---- | :---- | :---- |
| **Recap & CTA** | Split view. GitHub project screenshot. Presenter. | We started with a confusing label. With Jina OCR on EIS, we read it with one API call, stored it in Elasticsearch, and searched it by words and by meaning, in any language. The demo app is on GitHub, linked below, with the Console requests too. Try it on a label of your own, and tell me what it gets right or wrong. Next time, we'll look at asking questions across everything you've read. |
| **Outro** | Closing screen. Elastic logo. | Thanks for watching, and I hope to see you in a future Elastic community video. |

## **Description (links)**

Repo · `docs/kibana-demo.md` · Elastic Inference Service docs · Hugging Face model card · paper (arXiv 2609.03181) · "Preview as of <recording date>: the API may change" · "Open weights, non-commercial licence" · credits: Jina AI, the Inference team, Open Food Facts (ODbL data, CC BY-SA images) · "Not medical advice. The app compares numbers with limits you set."
