/**
 * Gmail attachment -> Drive relay for Holy Spend's email receipt ingestion.
 *
 * The scheduled chat automation (see ../email-receipt-ingestion.md) can read
 * a Gmail message's body but not its attachment bytes. This script fills
 * that one gap: it copies each new email's attachments into a Drive folder
 * the automation can search, named by the email's own Gmail message ID so
 * the automation can find the right file deterministically.
 *
 * Setup (one time):
 *   1. https://script.google.com/ -> New project, using the SAME Google
 *      account as your dedicated receipt-forwarding inbox.
 *   2. Paste this whole file in, replacing the default Code.gs contents.
 *   3. Create a Drive folder for the attachments, share it as "Anyone with
 *      the link - Viewer", copy its ID from the URL
 *      (drive.google.com/drive/folders/<THIS PART>), and paste it into
 *      DEST_FOLDER_ID below.
 *   4. Run the `setup` function once from the editor's function picker.
 *      Google will show an "unverified app" warning the first time you
 *      authorize it - click "Advanced" -> "Go to <project name> (unsafe)".
 *      This is expected for a personal script; it isn't actually unsafe,
 *      Google just hasn't reviewed it because it's not a published product.
 *   5. Done. `setup` creates the Gmail label and the recurring trigger;
 *      `processReceiptAttachments` runs on its own from then on.
 */

// Paste your destination Drive folder's share link or bare ID here (see
// step 3 above) - either form works.
var DEST_FOLDER_ID = 'PASTE_YOUR_FOLDER_ID_OR_LINK_HERE';

// Marks a thread as fully evaluated, whether or not anything useful was
// uploaded from it, so the search below never re-inspects it.
var PROCESSED_LABEL_NAME = 'HS-Drive-Uploaded';

var GMAIL_SEARCH_QUERY = 'in:inbox has:attachment -label:' + PROCESSED_LABEL_NAME;

// Bounds one run's Gmail API + Drive API usage; leftover threads are picked
// up on the next scheduled run, same batching the chat automation itself
// uses for its own 25-per-run limit.
var MAX_THREADS_PER_RUN = 25;

var FALLBACK_EXTENSIONS = {
  'application/pdf': 'pdf',
  'image/jpeg': 'jpg',
  'image/png': 'png',
  'image/webp': 'webp',
};

/** Run this once from the editor to install the label and the trigger. */
function setup() {
  getOrCreateLabel_();
  createTriggerIfMissing_();
  Logger.log('Setup complete. processReceiptAttachments will now run every 15 minutes.');
}

/** The recurring job. Also safe to run manually from the editor. */
function processReceiptAttachments() {
  var label = getOrCreateLabel_();
  var folder = DriveApp.getFolderById(resolveFolderId_(DEST_FOLDER_ID));
  var threads = GmailApp.search(GMAIL_SEARCH_QUERY, 0, MAX_THREADS_PER_RUN);

  for (var i = 0; i < threads.length; i++) {
    processThread_(threads[i], folder, label);
  }
}

/**
 * A thread only gets labeled once every attachment on every message in it
 * has actually been uploaded - one attachment failing (a transient Drive
 * write error, most often) no longer silently blocks a sibling attachment
 * from uploading, and the thread stays unlabeled so a real failure retries
 * next run instead of being lost.
 */
function processThread_(thread, folder, label) {
  var messages = thread.getMessages();
  var allSucceeded = true;

  for (var i = 0; i < messages.length; i++) {
    if (!processMessage_(messages[i], folder)) {
      allSucceeded = false;
    }
  }

  if (allSucceeded) {
    thread.addLabel(label);
  }
}

/**
 * getAttachments() excludes inline images (signature logos, tracking
 * pixels) by default - only real attachments reach this loop.
 */
function processMessage_(message, folder) {
  var attachments = message.getAttachments();
  var messageId = message.getId();
  var allSucceeded = true;

  for (var i = 0; i < attachments.length; i++) {
    try {
      uploadAttachmentIfNew_(attachments[i], i + 1, messageId, folder);
    } catch (error) {
      allSucceeded = false;
      Logger.log('Failed to upload attachment ' + (i + 1) + ' on message ' + messageId + ': ' + error);
    }
  }

  return allSucceeded;
}

function uploadAttachmentIfNew_(attachment, index, messageId, folder) {
  var filename = messageId + '_' + index + '.' + extensionFor_(attachment);

  if (folder.getFilesByName(filename).hasNext()) {
    return; // Already uploaded - a defensive check on top of the thread label.
  }

  // copyBlob() + setName() preserves the original bytes and content type;
  // nothing here ever converts a PDF into a Google Docs file.
  var blob = attachment.copyBlob().setName(filename);
  var file = folder.createFile(blob);
  file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);

  // Back-to-back Drive writes with zero delay can trip a transient rate
  // limit on this service - this is what most likely dropped a sibling
  // attachment silently before this function had per-attachment isolation.
  Utilities.sleep(300);
}

function extensionFor_(attachment) {
  var name = attachment.getName() || '';
  var dot = name.lastIndexOf('.');
  if (dot > -1 && dot < name.length - 1) {
    return name.substring(dot + 1).toLowerCase();
  }
  return FALLBACK_EXTENSIONS[attachment.getContentType()] || 'bin';
}

/** Accepts either a bare folder ID or a full Drive URL pasted as-is. */
function resolveFolderId_(raw) {
  var match = raw.match(/\/folders\/([a-zA-Z0-9_-]+)/);
  return match ? match[1] : raw.trim();
}

function getOrCreateLabel_() {
  return GmailApp.getUserLabelByName(PROCESSED_LABEL_NAME) || GmailApp.createLabel(PROCESSED_LABEL_NAME);
}

function createTriggerIfMissing_() {
  var alreadyExists = ScriptApp.getProjectTriggers().some(function (trigger) {
    return trigger.getHandlerFunction() === 'processReceiptAttachments';
  });
  if (!alreadyExists) {
    ScriptApp.newTrigger('processReceiptAttachments').timeBased().everyMinutes(15).create();
  }
}
