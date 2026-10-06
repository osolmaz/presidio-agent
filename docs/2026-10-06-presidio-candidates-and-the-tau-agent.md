---
date: 2026-10-06
author: Onur Solmaz <2453968+osolmaz@users.noreply.github.com>
title: Presidio candidates and the Tau agent
tags: [presidio-agent, presidio, tau, agent, design]
---

# Presidio candidates and the Tau agent

This note records how the project became presidio-agent. It was called synthero and ran
one fixed flow: a vision model found the personal values, and code located and redrew
them before the model checked the result. Two gaps remained. Detection recall
depended on the vision model alone, and nothing could decide about a value the model was
unsure of. The project now takes candidates from Presidio and runs inside a Tau agent,
while the pixel edits stay the same fixed and tested code.

## Recall test

Before any code changed, Presidio's analyzer ran on the text of the 24 eval documents
(digital text layers, and Tesseract text for the scans) and its hits were compared with
the values the vision model had found. Presidio made 353 hits, and 227 of them matched
no found value. After a review by hand, two were real misses of customer data: the till
receipt's date on the real scan of `drucker.pdf`, and the customer's phone number on page
3 of the simulated `telekom_1` scan, which the model found on page 1 and on the digital
twin. Six more were the names of managing directors in footers ("Geschäftsführung: Julia
Kern und Daniel Vogt"), which the model never listed in any set. Everything else was the
business's own details, which stay unchanged on purpose, or noise from the German name
recognizer, such as "Bankname" read as a person.

So Presidio finds real misses, but most of its hits are not personal data. It became a
source of candidates for the model to check, and never a reason to edit on its own.

## Candidates

`recognizers.py` builds Presidio's analyzer for German. Presidio ships its generic
recognizers (IBAN, e-mail, phone, card, date) for English only, so they are registered
again for German next to Presidio's German ID recognizers and the `de_core_news_md` name
recognizer. `candidates.py` keeps the entities worth checking on invoices and drops
places, organisations, web sites, postal codes, and VAT IDs, because on these documents
those are almost always the business's own details.

The candidates go into the vision model's second pass, after the OCR text, with the
instruction to check each one against the image. The first pass still sees the image
alone, so a candidate cannot steer what the model reads first.

The managing-director gap is closed by the agent and not by the detection prompt. A
sentence in the first-pass prompt asking for the names of the business's managers made
Bonsai list the whole footer instead: the shop's phone numbers, addresses, VAT and
register numbers, and bank details. On invoice B (`drucker-3.jpg`) the count went from 9
values to 41, and a narrower wording either did the same (38) or dropped the director
(10). The 2-bit model cannot hold that one exception next to the rule that excludes the
business's details. The original prompt stays, Presidio flags the director's name as a
person, and the agent's policy accepts the names of staff and managers.

## Agent

Tau is Hugging Face's Python port of Pi's agent harness. presidio-agent is Tau's own CLI
with one extension (`extension.py`) and an appended policy (`agent.md`); it has no agent
loop of its own. The extension registers three tools over the fixed flow in
`pipeline.py`:

| Tool | What it does |
| --- | --- |
| `find_personal_values` | Analyses a document. It reports the values with whether each was located, and the candidates the model did not confirm, with the page images. |
| `accept_value` | Adds a value the agent decided is personal, then locates it and updates the page's cache. |
| `make_copies` | Makes the copies and reports how each did in the read-back and the leak check. |

The agent's job is the decision the fixed flow cannot make: for each candidate the model
did not confirm, it opens the page image with Tau's read tool and accepts the candidate
or skips it. A `tool_call` hook blocks every other Tau tool, so the agent cannot write
files or run commands such as an OCR engine.

The tools' reports contain original values, so the launcher sets `TAU_HOME` inside the
private folder and Tau's session logs land there with the other private data.

## Tau and llama.cpp vision

Tau's llama.cpp backend did not see that a llama.cpp model accepts images, so it never
sent the read tool's page images to the model. Current llama.cpp reports inputs as
`architecture.input_modalities`, older builds report them only in `/props`, and Tau read
neither. [huggingface/tau#757](https://github.com/huggingface/tau/pull/757) fixes this,
and presidio-agent pins Tau to that branch's commit until a release includes it.

## Testing

The new modules are tested against fakes of the model and OCR and of Presidio, so the
tests run without a server. One test runs the real Presidio analyzer when the `presidio` extra is
installed. `candidates.py` is under mutation testing with the other pure modules, and the
whole set kills 88.7% of mutants against the floor of 85%.
