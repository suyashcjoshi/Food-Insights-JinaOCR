# **Turn Images & PDFs into searchable text with JINA OCR: A/V Script**

**Author:** Suyash  
**Reviewers:** Carly, Arturo, Rob  
**Status:** v1: 4/11/2026, v2: 6/11/2026 

## **Overview**

A practical explainer built around a small demo app: photograph a food label on your phone, read it with jina-ocr-v1 running on the Elastic Inference Service (EIS), store the result in Elasticsearch Serverless and search every label you have read, in any language. 

The video shows the one API call behind it, explains why a small specialised model reads labels well and cheaply, shows honestly where it fails and how the app is designed around that, and closes with a measured comparison against general-purpose models.

This video is also very timely as this new API is being released as part of 9.6 release and we can publish video soon after to promote the same.

**Demo App:** [https\://github.com/suyashcjoshi/Food-Insights-JinaOCR](https://github.com/suyashcjoshi/Food-Insights-JinaOCR)

## **Target viewers**

**Primary**: Backend and search developers who already use or are evaluating Elasticsearch and have a backlog of images, pdf’s that search can't read and are currently stitching together OCR libraries or vision LLM calls. 

**Secondary**: Developers who are interested in OCR solutions but are not Elastic users.

## **Core viewer promise**

Read any label with one API call inside Elasticsearch, see exactly where the model can and can't be trusted and how to design around it.

## **Suggested YouTube titles**

> 1. Small Model, Right Row: OCR Inside Elasticsearch with jina-ocr-v1  
> 2. Stop Sending Labels to an LLM: Jina OCR on EIS, Explained and Tested

## **Search term suggestions**

Jina OCR; jina-ocr-v1; Elastic Inference Service; EIS; OCR Elasticsearch; nutrition label OCR; document parsing small model; OCR vs LLM; Elasticsearch Serverless; inference endpoint

> 

## **Recording & Editing checklist**

> * **Rig:** overhead camera on an arm for hands and packs, locked focus and exposure, taped marks on the counter; face camera at eye level; both roll continuously and are in sync.  
> * **Phone:** screen recorded natively over an HTTPS tunnel and composited; never filmed from above. Endpoint warmed before every take (first call after idle takes minutes).  
> * **Screen:** Kibana Console at two or three zoom steps; filter the response to content and usage. Light or dark mode for the app chosen once and never mixed.  
> * **Names:** use exact product names on screen and in audio: Elastic Inference Service (EIS), Elasticsearch Serverless, Kibana Console, Discover, ES\|QL, the reader endpoint.  
> * **Props:** common food items from kitchen in packaging, the crumpled protein bar, German chocolate, the sugar cube. Open Food Facts images only in the accuracy chart, attributed.  
> * **Pacing:** jump cut loading; cut between phone and explanation every 20–30 seconds in the app section; record in segments.  
> * **Tone:** calm, candid, no hype. Show our own failures. Never dismissive of general models. No health advice: the app reads labels, never advises.  
> * **Design:** Elastic brand guidelines; pencil-and-paper look for animations, consistent with previous videos.

> 

## **Section 1: Hook, Teaser & Introduction \~00:00 \- 00:40**

Goal: Grab attention with a real practical problem and set up what's coming with OCR.

| Scene & Notes  | Visual | Verbal |
| :---- | :---- | :---- |
| **The Problem**  | Layout: Talking to Camera Talking to camera and showing food items Cutting to show a close-up of the protein bar and sugar packet. | This protein bar looks healthy. But does it fit my carb limit for today? The answer’s on the label. Somewhere. And this sugar packet? Apparently, I need a magnifying glass with my coffee. Even when I can read the numbers, I still have to add them to everything else I’ve eaten. So I built an app to help. |
| **Solution teaser** | Split Layout  Chapter Heading on top right Screen recording of Demo App (Main screen)  Myself (Right side) | All I have to do is take a photo, it extracts the text and makes the daily nutrition information easier to find. |
| **Intro** | Lower third (my name, title) Animation of the core elements of the demo app \- architecture diagram | Hi, I’m Suyash. Let’s use Jina OCR through Elastic Inference Service to turn these food labels into text then bring that information into Elasticsearch so we can search and analyse it. |

## 

## **Section 2: Why OCR is tricky \~00:40 \- 1:45**

Goal: make the problem concrete in under a minute, and plant the "big model" question without arguing it yet.

| Scene | Visual | Verbal |
| :---- | :---- | :---- |
| **Challenges** | Animations of an image being converted to OCR for: Image of food item with glare and shiny wrappers Bend and obscured items with text that is hard to read Food item in Japanese language | The first step is OCR optical character recognition. It turns text in an image into text our software can work with. But food labels can be challenging. The print can be tiny, the wrapper can reflect the light, a fold can hide half a word and layouts are not universally standard. Then there are language issues when you go to a foreign country and shop for food items. So we want a robust system that not only handles all these challenges at scale but is also very accurate but also fast and cost effective specially when an app needs to make several API calls. |

## 

## **Section 3: Meet jina-ocr-v1 \~1:45 \- 3:45**

Goal: explain in plain terms why this model reads well and cheaply. 

| Scene | Visual | Verbal |
| :---- | :---- | :---- |
| **App Deep Dive** | Card: jina-ocr-v1 and license Hugging face page screenshot | That’s the job we’re giving Jina OCR to solve. It’s a small model built for reading documents: an image goes in, formatted text comes back, tables and reading order intact. On Elastic you reach it through an endpoint called `.jina-reader`. It’s open weight for non-commercial use, for production you call it through Elastic Inference Service. |
| **Architecture walkthrough**  | Architecture Diagram highlighting EIS | Here’s the whole app. On the left is our web app where we take the photo. In the middle is a small FastAPI backend that does three things: extract, ingest and search. On the right are two Elastic services within one Elastic Serverless project. Btw, you can also run this within Elastic Cloud Hosted as well. All you need is an API key that you can easily create and configure in your application. Jina OCR on Elastic Inference Service is where the photo is sent and markdown comes back in a few seconds. Elastic runs the model on its GPUs so there’s nothing for us to deploy or manage. Then Elasticsearch also has two indexes: `food_labels` for every label it reads and `food_log` for what I’ve eaten. Neither of these were created during the OCR call.  It’s important to note that the reader only returns the markdown and stops, it never writes to an index. The app logic created both of these indexes so we can ingest the information about what we ate and keep track of calories. Search is a normal Elasticsearch query: full text, typo tolerant showing highlighted matches. |
| **Live Demo** | Mobile App Recording  | Let’s try it on this bar. (Walk through the demo app in brief).  |

## 

## 

## **Section 4: The detailed walkthrough \~3:45 \- 7:45**

Goal: show the end-to-end on how to use EIS with help of this demo app, Dev Console and screen whenever the viewer needs to know what just happened.

| Scene | Visual | Verbal |
| :---- | :---- | :---- |
| **POST Request** | Dev Console screen recording Show the Image | Let’s test this out in the Kibana Dev Console. Here’s the request the app sent. It has one extraction call for this image that I’ve base64-encoded. Btw you can also send a PDF as it’s supported but I’m working with images for this demo. |
| **HTTP Response** | Dev Console screen recording | Once we sent the POST request, here’s the extracted content. Let’s check it against the photo. \[Explain API response structure\] |
| **Storage** | Index architecture diagram | Now the OCR call doesn’t store the image or the data. To do that we rely on another request. \[Explain API to store data and that index is created and ready for search\] |
| **Library Page** | Phone: search "peanut" | This finds labels that mention peanuts. It helps us inspect those mentions as  it isn’t an allergy safety check. |
| **Discover View** | Discover: the ES\|QL query. | If I switch back to Discover inside Kibana, let me run this query and show you all the data for our food labels. |

## 

## **Section 5: Why not a general model? \~7:45 \- 9:00**

Goal: answer the question the viewer has been holding since Section 2 without bashing anyone.

| Scene | Visual | Verbal |
| :---- | :---- | :---- |
| **General Model vs Elastic** | Split View Screen recording Myself | Now you may be wondering why not just use a general purpose LLM model to do this? Any frontier model should be able to read this label but it’s like using a hammer for the job when a scalpel that is purpose built for one task only is a more effective tool both in terms of cost and also efficiency.  For the reading step, I’m using a JinaINA OCR model built specifically for document parsing. |
| **Elastic Context** | Diagram showing full integration | But reading this packet is only half the problem. To put it in the context of my day, the app retrieves my logged entries from Elasticsearch. So here we are calling several Elastic API’s all to help one single goal of understanding images, storing the data and searching to make sense of it. |

## 

## **Section 6: Recap and CTA \~9:00 \- 10:00**

| Scene | Visual | Verbal |
| :---- | :---- | :---- |
| **Recap & CTA** | Split View Main screen: GitHub Project Screenshot Myself talking head | We started with confusingwith a confusing food labels. Now with help of Elasticsearch and JINA we saw how easy it is to extract text from any image label, store the result and search quickly. The demo app is on Github and linked in the description below. I encourage you to try it out and look forward to hearing anyhearing your any questions or comments you have. |
| **Outro** | Closing screen / Elastic logo | Thanks for watching and hope to see you in a future Elastic community youtube video. |

