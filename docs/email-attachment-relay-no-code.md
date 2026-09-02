# Attachment relay without code (Zapier/Make)

[gmail-attachment-relay.gs](apps-script/gmail-attachment-relay.gs) is the
recommended way to close the PDF/image-attachment gap described in
[email-receipt-ingestion.md](email-receipt-ingestion.md#3-handle-attachment-only-receipts-optional) —
free forever, runs on your own Google account, and it's plain code so it
can't silently misconfigure itself. If you'd rather not touch a script at
all, a hosted no-code scenario does the same job. Two real caveats before
you build one:

- **Zapier's free plan can't run this.** The scenario needs a loop (one
  attachment can be multiple files) plus a filter, and Zapier gates
  multi-step Zaps behind a paid plan — you'd hit a 14-day trial wall, not a
  stable free tier.
- **Make.com's free plan can.** Make bills by operation volume, not by
  step count or feature — filters and iterators are available on the free
  plan (1,000 ops/month, 2 active scenarios), and at real personal-receipt
  volume (a handful of emails a month) that's nowhere close to the cap.

## Building it

Paste this into Make's AI scenario builder, or build it by hand — either
way, verify the result against the gotchas below before trusting it:

```
Build a Make scenario with these modules:

1. Trigger: Gmail — "Watch Emails"
   - Account: the Gmail account for your dedicated receipt-forwarding inbox
   - Folder: Inbox
   - Search/criteria: has:attachment

2. Iterator (Flow Control) — iterate over the array of attachments from the
   trigger's email.

3. Google Drive — "Upload a File"
   - Source: the current attachment from the Iterator (file content + name).
   - Destination folder: your receipt-attachments Drive folder.
   - File name: the Gmail message's unique Message ID (from the trigger —
     not the thread ID), an underscore, the current Iterator index number,
     then the original file extension. Example: 1a03f4eac1005a02_1.pdf
   - Do NOT convert the file to Google Docs format — it must upload as the
     original binary (application/pdf, image/jpeg, etc).

4. Google Drive — set sharing on the file just uploaded to "Anyone with the
   link" / Viewer, unless this is already inherited from the destination
   folder's own sharing settings.

Do not modify, forward, label, or reply to the original email. Do not
archive or delete it.
```

## Gotchas confirmed by hand, not just described

An AI-assisted scenario builder can report success while getting the
actual field mappings wrong. Check all three of these directly in the
module editor after it builds anything, don't trust the summary message:

1. **PDF-to-Google-Docs conversion.** The most dangerous one, because it
   fails silently — the file lands in Drive, looks like it worked, but
   it's now a native Google Doc with no way to serve the original PDF
   bytes back out. Symptom: the uploaded file shows a blue Google Docs
   icon instead of a red PDF icon, and its size reads suspiciously small
   (e.g. "1 KB") regardless of the real file's size. Find the "Convert to
   Google Docs editor format" toggle on the Upload module and make sure
   it's off.
2. **Filename.** Open the module and confirm the File Name field is
   actually bound to the dynamic Message ID token from the trigger step,
   not typed as literal text and not silently falling back to the
   attachment's own original filename.
3. **Destination folder.** Confirm the Folder field points at your actual
   receipt-attachments folder via its picker (bound to a real folder ID),
   not defaulting to Drive root ("My Drive").

## Tracking already-processed emails

You don't need to build this yourself — Make's own polling trigger tracks
which items it's already emitted internally and won't re-fire on an email
still sitting in the inbox. The one thing to know: Make's manual
"test"/"run once" action in the editor bypasses that tracking on purpose
(it grabs a batch of recent matching items to test field mappings against)
— if you see old emails' attachments reappear in Drive, that's most likely
a manual test run, not the live schedule misbehaving.

## Confirm the download link actually works

Before wiring this into the scheduled chat task at all, verify the
shareable link Drive produces actually serves raw bytes and not an
interstitial page:

```bash
curl -IL "https://drive.google.com/uc?export=download&id=<file_id>"
```

Large files can return Drive's "can't scan for viruses" confirmation page
instead of the file itself — unlikely for a typical receipt PDF, but worth
ruling out once rather than debugging it later from inside the automation.
