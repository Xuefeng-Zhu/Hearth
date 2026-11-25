# Hearth QA for Hacksgiving

## Run 23 · Pages

November 25, 2026 · Private Hearth Sprite

### Demo script

1. In a demo workspace, choose **Mock** in **Settings → Brain**. In Chat, send **Make a page for our Thanksgiving dinner.** Open the **Thanksgiving dinner** page card. The page uses the demo guest list and menu.
2. Switch between **Phone** and **Desktop** to show the 390 px and 1440 px previews. Close the preview and send **Make the header green.** Open the new card and compare v2 with v1 in **Version history**.
3. Open **Pages** from the sidebar or mobile menu, immediately after **Artifacts**. Open the page, use **Open in new tab**, then **Download .html**. **Save HTML to Box** saves the selected version to the **Pages** folder when Box is connected.
4. With v1 selected, click **Share link**. Show the approval card, then approve. Open the share URL in a signed-out window. Revoke it from the page and reload the public URL to show the 404.
5. Select v1 and click **Restore v1**. Hearth adds v3 with the original contents. Open **Timeline** and undo the restore to return to v2.

### Verification

- Chromium checked all four viewport and theme combinations, including navigation order, dialog focus, page cards, frame isolation, preview widths, sharing, HTML download, restore, and Timeline Undo. There were no browser errors. The Thanksgiving page had no horizontal overflow and its lowest sampled text contrast was **7.25:1** in light mode and **9.50:1** in dark mode. The Browser plugin was unavailable, so the captures use Playwright Chromium.
- The deployed Hugging Face brain used **Kimi-K3.1-Pro** to build **Seattle trip itinerary** in **51.39 s** and **周日家庭野餐** in **47.39 s**. A follow-up in the Seattle thread changed the header to green and saved v2 in **20.63 s**. Both builds kept the supplied details. The **DeepSeek-V4-Pro-0813** code fallback passed the simulated provider failure. [Seattle v2](https://your-sprite.sprites.app/pages/6886c729b37f487ea925fa82a44169ca/v/2) · [周日家庭野餐](https://your-sprite.sprites.app/pages/b51dcf93d714485e82a37804702a8603)
- Chromium rendered the three HTML documents pulled from the Sprite at both widths and in both themes. All sampled text passed WCAG AA contrast, with a minimum of **6.14:1** across the live examples and no horizontal overflow. The Seattle header changed from dark teal to green in both themes.
- The authenticated private Sprite returned `{"ok": true, "checkpoints": "sprite"}`. Anonymous access to its page returned **302** to Sprite sign-in. An approved Seattle v1 snapshot opened without auth on the separate Pages origin and matched the private v1 byte for byte. The public origin returned **404** for the workspace, API, private page paths, and the revoked link. Sharing pins one version per approval.
- **138 Python tests**, **7 Node tests**, JavaScript syntax checks, and shell syntax checks passed. The new tests cover sanitized HTML and CSS, the CSP, attachment-only images, a single clarification, mock builds, version conflicts and Undo, and create/revoke behavior. The Box upload was verified with a connector fixture. Pages use styled thumbnails. Generated documents use inline CSS and native HTML controls. The sanitizer removes JavaScript.

| Capture | 390 px light | 390 px dark | 1440 px light | 1440 px dark |
| --- | --- | --- | --- | --- |
| Pages list | [Light](/workspace/tmp/hearth-qa/run23-pages-list-390-light.png) | [Dark](/workspace/tmp/hearth-qa/run23-pages-list-390-dark.png) | [Light](/workspace/tmp/hearth-qa/run23-pages-list-1440-light.png) | [Dark](/workspace/tmp/hearth-qa/run23-pages-list-1440-dark.png) |
| Phone preview | [Light](/workspace/tmp/hearth-qa/run23-preview-phone-390-light.png) | [Dark](/workspace/tmp/hearth-qa/run23-preview-phone-390-dark.png) | [Light](/workspace/tmp/hearth-qa/run23-preview-phone-1440-light.png) | [Dark](/workspace/tmp/hearth-qa/run23-preview-phone-1440-dark.png) |
| Desktop preview | [Light](/workspace/tmp/hearth-qa/run23-preview-desktop-390-light.png) | [Dark](/workspace/tmp/hearth-qa/run23-preview-desktop-390-dark.png) | [Light](/workspace/tmp/hearth-qa/run23-preview-desktop-1440-light.png) | [Dark](/workspace/tmp/hearth-qa/run23-preview-desktop-1440-dark.png) |
| Chat card | [Light](/workspace/tmp/hearth-qa/run23-chat-card-390-light.png) | [Dark](/workspace/tmp/hearth-qa/run23-chat-card-390-dark.png) | [Light](/workspace/tmp/hearth-qa/run23-chat-card-1440-light.png) | [Dark](/workspace/tmp/hearth-qa/run23-chat-card-1440-dark.png) |

At the Run 23 revision, run the browser regression from the repository root with Playwright Chromium installed.

```sh
PYTHONPATH=. python tests/run23-browser.py --output /tmp/hearth-shots
```

`scripts/deploy-pages-share.sh` installs the share-only service and its dedicated publishing key. `scripts/deploy.sh` installs Hearth on the private Sprite. Public snapshots live on the share origin, outside Hearth workspace checkpoints.

## Run 22 · Glanceable Home

November 25, 2026 · Private Hearth Sprite

### Demo script

1. In a demo workspace, choose **Mock** in **Settings → Brain**. To populate **Today** and **Recent files**, send **Plan Thanksgiving dinner** in Chat. Wait for the PDF, workbook, and in-app reminder. Leave the sample invitation awaiting approval.
2. Open **Home**, the first item in the desktop sidebar and mobile menu. Select **Try sample panels in Chat**, then send the prepared prompt, **Create the Thanksgiving countdown and shopping list Home panels**. The reply’s **Open Home** action returns to the seven built-ins and the two new panels. Send the same prompt again if you need to resume this demo.
3. Open **Thanksgiving plan** in **Recent files** to show its PDF preview. Return to Home, check off **Cranberries** in **Shopping list**, and use **Refresh Shopping list**. Reload to show that the checkmark persists. Select **Ask about this** to open a side chat with the panel snapshot and a prepared question.
4. Drag **Today** by its handle on desktop. On mobile, select **Edit layout** and use **Move Today down**. Remove a panel and restore it from **Removed panels**, then select **Done**. Reload to verify the saved order.
5. Open **Weather settings** from the weather panel and enter another city, such as **Seattle, WA**. Return to Home and refresh the panel. The location and conditions change while the clock stays on Pacific time. [Open-Meteo forecast documentation](https://open-meteo.com/en/docs) · [Location search documentation](https://open-meteo.com/en/docs/geocoding-api)

### Verification and captures

- Chromium passed at **390 × 844** and **1440 × 1080** in both themes. It verified the landing page, navigation order, grid, drag and button reordering, removal and restoration, checklist and layout persistence, preview focus, weather settings, the side-chat snapshot, approval for four panels, and refresh recovery with the last good value visible. No page or console errors were reported. The Browser plugin was unavailable, so the checks used Playwright Chromium.
- The Home text contrast sweep measured a minimum of **5.50:1** in light mode and **6.20:1** in dark mode. Visual review compared the navigation, date hierarchy, panel order, heading icons, footer actions, and grid density with the desktop and mobile concepts. The deployed shell keeps Hearth’s existing sidebar and mobile status indicator.
- **127 Python tests** and **7 Node tests** passed. All top-level frontend JavaScript passed `node --check`. The Home tests cover validation, atomic approval and replay, scheduler intervals, refresh and edit races, saved errors, persistence, connector GET, public URLs, and weather retries. The Run 21 browser regression also passed in all four viewport and theme combinations.
- The deployment returned `{"ok": true, "checkpoints": "sprite"}` from authenticated `/health`. The live Home endpoint returned all seven built-ins, and Open-Meteo populated the stored Redmond forecast. In an isolated Sprite workspace, Kimi K3.1 Pro created a stat panel through Chat, and a public URL panel saved a summary from a connected brain. The screenshots use a Mock workspace with fixture weather and connector states.

| Capture | 390 px light | 390 px dark | 1440 px light | 1440 px dark |
| --- | --- | --- | --- | --- |
| Home viewport | [Light](/workspace/tmp/hearth-qa/run22-home-390-light.png) | [Dark](/workspace/tmp/hearth-qa/run22-home-390-dark.png) | [Light](/workspace/tmp/hearth-qa/run22-home-1440-light.png) | [Dark](/workspace/tmp/hearth-qa/run22-home-1440-dark.png) |
| All nine panels | [Light](/workspace/tmp/hearth-qa/run22-all-panels-390-light.png) | [Dark](/workspace/tmp/hearth-qa/run22-all-panels-390-dark.png) | | |
| Mobile reorder mode | [Light](/workspace/tmp/hearth-qa/run22-reorder-390-light.png) | [Dark](/workspace/tmp/hearth-qa/run22-reorder-390-dark.png) | | |

With Playwright Chromium installed, run the Home browser regression from the repository root.

```sh
PYTHONPATH=. python tests/run22-browser.py --shots /tmp/hearth-shots
```

## Run 21 · Chat attachments and mobile polish

November 25, 2026 · Private Hearth Sprite

### Demo script

1. In **Settings → Brain**, choose **Mock** for the deterministic demo. Open a side chat and ask **Can you create a slide for Seattle trip?** The assistant says “Here's your Seattle trip deck.” above the PowerPoint card. Open the card with its preview icon.
2. Choose the paperclip and add a photo and a PDF in one selection. Include a document with selectable text. On desktop, try dropping the workbook into Chat and pasting a clipboard image. On iPhone, the paperclip opens the native file picker. Watch the chips, remove any extra file, then send **Summarize the attached files**. An empty composer also sends ready attachments.
3. Mock gives a fixed demo description for the photo and a short extractive summary for the PDF. Open the image, PDF, and XLSX cards or the reply’s **Sources**. Swipe the wide spreadsheet horizontally. Reload and check that the original message and previews return.
4. Select **Copy** under the reply and look for **Copied**. Tap or long-press a side-chat message to reveal **Share to Main**. On desktop, right-click the message or focus it and press Enter. Call is in the top-right corner of the chat header, and Settings stays at the bottom of both navigation layouts.
5. The box icon on the attachment card explicitly saves the original bytes to Box if connected. Once saved, the icon becomes **Open in Box**. Return to Smart routing to demonstrate live image, document, and audio understanding.

### Live Sprite attachment checks

The deployed release ran three independent uploads and chat turns in a temporary workspace on the private Sprite. Each returned a clickable attachment citation, an available preview, and a byte-identical download. All replies were in Chinese.

| Attachment | Hearth’s answer | Upload through verified reply and preview |
| --- | --- | --- |
| Apollo 11 JPEG | Identified a white-suited astronaut standing on dusty lunar ground with boot prints and a reflection of the photographer and equipment in the visor. | 10.31 s |
| 图书馆活动.pdf | The book club meets at 松林图书馆 on Saturday, December 12 at 2 p.m. It has 24 spots, requires advance registration, and attendees should bring a favorite book. | 4.79 s |
| Seattle budget.xlsx | The budget is **US$155**. The second sheet identifies **林晓** as the approver and **SEA-274** as the reference. | 3.94 s |

Qwen3-VL 235B A22B Instruct interpreted the JPEG through Hugging Face. Kimi K3.1 Pro wrote the three chat replies. [Apollo 11 photo from NASA](https://nssdc.gsfc.nasa.gov/imgcat/html/object_page/a11_h_40_5903.html)

### Regression checks and captures

- 117 Python tests and seven Node tests passed, and all frontend JavaScript passed `node --check`. The upload suite covers the exact 20 MiB boundary, unsupported and misleading MIME types, malformed multipart boundaries, same-origin requests, traversal and thread scope, Office and Chinese text extraction, truncation, vision fallback, Whisper dispatch, Mock, and the explicitly triggered Box binary upload. Box saving was checked with a test double.
- Chromium passed all four theme and width combinations using a UTC browser profile. A version timestamp of `2026-11-25T01:16:00Z` read **Nov 24, 5:16 PM** in the artifact sheet. The mobile XLSX test checks that a long header stays on one line and that the sheet scrolls horizontally. The existing contrast sweep passed 11,201 measurements. Browser automation verified the native-picker input activation; physical iPhone interaction remains unverified.
- The final deployment returned `{"ok": true, "checkpoints": "sprite"}`. The deployed composer, icon, time, chat, and stylesheet assets matched the local release.

| Capture | 390 px light | 390 px dark | 1440 px light | 1440 px dark |
| --- | --- | --- | --- | --- |
| Attachments in chat | [Light](/workspace/tmp/hearth-qa/run21-attachments-390-light.png) | [Dark](/workspace/tmp/hearth-qa/run21-attachments-390-dark.png) | [Light](/workspace/tmp/hearth-qa/run21-attachments-1440-light.png) | [Dark](/workspace/tmp/hearth-qa/run21-attachments-1440-dark.png) |
| Attachment chips | [Light](/workspace/tmp/hearth-qa/run21-attachments-composer-390-light.png) | [Dark](/workspace/tmp/hearth-qa/run21-attachments-composer-390-dark.png) | [Light](/workspace/tmp/hearth-qa/run21-attachments-composer-1440-light.png) | [Dark](/workspace/tmp/hearth-qa/run21-attachments-composer-1440-dark.png) |
| Navigation | [Light](/workspace/tmp/hearth-qa/run21-nav-390-light.png) | [Dark](/workspace/tmp/hearth-qa/run21-nav-390-dark.png) | [Light](/workspace/tmp/hearth-qa/run21-nav-1440-light.png) | [Dark](/workspace/tmp/hearth-qa/run21-nav-1440-dark.png) |
| Reply actions | [Light](/workspace/tmp/hearth-qa/run21-chat-actions-390-light.png) | [Dark](/workspace/tmp/hearth-qa/run21-chat-actions-390-dark.png) | [Light](/workspace/tmp/hearth-qa/run21-chat-actions-1440-light.png) | [Dark](/workspace/tmp/hearth-qa/run21-chat-actions-1440-dark.png) |
| XLSX preview and version history | [Light](/workspace/tmp/hearth-qa/run21-xlsx-preview-390-light.png) | [Dark](/workspace/tmp/hearth-qa/run21-xlsx-preview-390-dark.png) | | |

The attachment screenshots use a photograph of Seattle from Puget Sound. [Pexels photograph](https://www.pexels.com/photo/seattle-skyline-and-puget-sound-from-ferry-28895463/)

With Chromium installed, run the standalone browser regression from the repository root.

```sh
PYTHONPATH=. python tests/run21-browser.py --shots /tmp/hearth-shots
```

## Run 19 · Contrast, navigation, and Chat

November 25, 2026 UTC · Private Hearth Sprite

- On a phone, tap the menu in the header and choose **Timeline**. Expand an activity, then open **Undo** and cancel. The drawer highlights the current page and closes on selection, Escape, scrim tap, or a left swipe. **New chat** and the thread list are in the drawer. The desktop sidebar stays in place.
- In a new chat, enter **Can you create a slide for Seattle trip**. Mock makes a local PPTX. Smart routing on the Sprite made a real PPTX, synced it to Box, and returned a file card. Use **Open** to preview or **Save to Box** to sync a local file. The message’s **⋯** button or a long press opens its timestamp, model details, and actions.
- Playwright Chromium exercised the drawer, focus trap, Markdown tables, expanding long replies, all Timeline entry kinds and raw details, each Office preview, Reminders, Inbox, both Connections tabs, all seven Settings sections, and demo call captions. The Browser plugin was unavailable. The additional drawer sizes were 375×812, 430×932, and 844×390 in both themes.
- The contrast sweep found zero failures. The lowest measurements were **5.224:1** for dark body text (**Undo**), **4.054:1** for a dark control border in Reminders, and **4.543:1** for light body text (the composer placeholder). The PDF viewer’s embedded page contents and decorative mascot artwork are outside the app DOM measurement. Physical iPhone Safari was not tested.
- All 105 Python tests, five Node tests, and JavaScript syntax checks passed. `scripts/deploy.sh` deployed the release, and the authenticated `/health` returned `{"ok": true, "checkpoints": "sprite"}`.

| Hugging Face model on the Sprite | Structured tool call | Chinese reply |
| --- | ---: | ---: |
| Kimi K3.1 Pro | 2.699 s | 9.149 s |
| DeepSeek V4.1 Flash | 0.987 s | 2.531 s |
| DeepSeek V4 Pro | 0.649 s | 0.999 s |

These are connector wall-clock times for one request per task and model. The full Seattle turn took 13.834 s and the downloaded PPTX passed ZIP validation. [Seattle Trip.pptx in Box](https://app.box.com/file/2614819364671)

### Browser evidence

| Flow | Captures |
| --- | --- |
| Timeline at 390 px | [Before](/workspace/tmp/hearth-qa/run19-timeline-before.png), [after](/workspace/tmp/hearth-qa/run19-timeline-after.png), [Undo](/workspace/tmp/hearth-qa/run19-dark-timeline-undo.png) |
| Drawer in light mode | [Closed](/workspace/tmp/hearth-qa/run19-menu-closed-light.png), [open](/workspace/tmp/hearth-qa/run19-menu-open-light.png) |
| Drawer in dark mode | [Closed](/workspace/tmp/hearth-qa/run19-menu-closed-dark.png), [open](/workspace/tmp/hearth-qa/run19-menu-open-dark.png) |
| Seattle in Mock, light | [Before](/workspace/tmp/hearth-qa/run19-chat-mock-before-light.png), [after](/workspace/tmp/hearth-qa/run19-chat-mock-after-light.png) |
| Seattle in Mock, dark | [Before](/workspace/tmp/hearth-qa/run19-chat-mock-before-dark.png), [after](/workspace/tmp/hearth-qa/run19-chat-mock-after-dark.png) |
| Seattle through Hugging Face, light | [Reconstructed before](/workspace/tmp/hearth-qa/run19-chat-live-before-light.png), [after](/workspace/tmp/hearth-qa/run19-chat-live-after-light.png) |
| Seattle through Hugging Face, dark | [Reconstructed before](/workspace/tmp/hearth-qa/run19-chat-live-before-dark.png), [after](/workspace/tmp/hearth-qa/run19-chat-live-after-dark.png) |
| Dark mobile screens | [Chat](/workspace/tmp/hearth-qa/run19-dark-chat.png), [side chat](/workspace/tmp/hearth-qa/run19-dark-side-chat.png), [Artifacts](/workspace/tmp/hearth-qa/run19-dark-artifacts.png), [Reminders](/workspace/tmp/hearth-qa/run19-dark-reminders.png), [Inbox](/workspace/tmp/hearth-qa/run19-dark-inbox.png), [Connections](/workspace/tmp/hearth-qa/run19-dark-connections-configured.png), [Settings](/workspace/tmp/hearth-qa/run19-dark-settings.png), [call](/workspace/tmp/hearth-qa/run19-dark-call.png) |

The old live capture recreates the reported leak in the old UI from the prompt description and a fresh response from the retired model. That response used a structured tool call, so the previously reported raw markup had to be reconstructed. The after capture renders the actual Sprite reply and artifact metadata in Chromium.

### Rerun the contrast check

With Playwright and its Chromium browser installed, run the fixture and audit from the repository root in two shells. The fixture creates a temporary Hearth workspace.

```sh
PYTHONPATH=. python tests/contrast-fixture.py
HEARTH_QA_SCREENSHOTS=/workspace/tmp/hearth-qa node tests/contrast.mjs
```

Set `PLAYWRIGHT_PATH` or `CHROMIUM_PATH` to use an existing external installation. Set `HEARTH_QA_BEFORE_URL` to capture the baseline Timeline from a Run 18 fixture.

## Run 18 · Office files

November 25, 2026 UTC · Private Hearth Sprite

Hugging Face Qwen3-Coder-Next created all four files from chat prompts. Each download returned the expected MIME type and extension, and the SHA-1 of its bytes matched the Box file metadata.

| Format | File | Box file ID | Latest Box version |
| --- | --- | --- | --- |
| PDF | Thanksgiving plan | [2614758587725](https://app.box.com/file/2614758587725) | 1 |
| DOCX | Kitchen prep guide | [2614755342889](https://app.box.com/file/2614755342889) | 1 |
| XLSX | Shopping budget | [2614757771595](https://app.box.com/file/2614757771595) | 3 |
| PPTX | 感恩节晚餐 | [2614755266074](https://app.box.com/file/2614755266074) | 3 |

A follow-up added a Chinese dessert slide to the existing deck. Preview QA found a repeated title slide, so the generator now combines duplicate title slides and preserves their notes. The live deck was corrected in version 3. The workbook gained a Category column and a follow-up corrected the Total formulas to reference the Quantity and Unit cost columns. Both files kept their original Box IDs. The Box gateway returned HTTP 403 from its version-history endpoint, and the drawer showed the receipts saved by Hearth. Unit tests reopened the Office files, checked the Chinese text and the embedded PDF font, and verified the one-page PDF. The Sprite installs the pinned 1.5 MiB WenQuanYi Micro Hei package and embeds the needed glyphs in each Chinese PDF. [Debian package](https://packages.debian.org/bookworm/fonts-wqy-microhei), [Font license](https://metadata.ftp-master.debian.org/changelogs/main/f/fonts-wqy-microhei/fonts-wqy-microhei_0.2.0-beta-3.1_copyright)


Chromium and Playwright passed at 1440×900 and 390×844 using a local relay to the private Sprite. The Browser plugin was unavailable. The sweep opened all four previews, verified browser downloads and Box links, checked drawer focus return and horizontal scrolling bounds, and found the file chip on the originating reply. Python passed 103 tests and Node passed five. All web JavaScript passed syntax checks.

| Browser evidence | Capture |
| --- | --- |
| Artifacts list · 1440 px | [Desktop](/workspace/tmp/hearth-qa/run18-artifacts-desktop.png) |
| Artifacts list · 390 px | [Mobile](/workspace/tmp/hearth-qa/run18-artifacts-mobile.png) |
| PDF inline preview | [PDF](/workspace/tmp/hearth-qa/run18-preview-pdf.png) |
| Word headings and paragraphs | [DOCX](/workspace/tmp/hearth-qa/run18-preview-docx.png) |
| Excel first-sheet table | [XLSX desktop](/workspace/tmp/hearth-qa/run18-preview-xlsx.png), [XLSX mobile](/workspace/tmp/hearth-qa/run18-preview-xlsx-mobile.png) |
| Chinese slide outline | [PPTX](/workspace/tmp/hearth-qa/run18-preview-pptx.png) |

## Mobile

November 25, 2026 UTC · `main` · Sprite runtime commit `2acb786`

Touch-enabled Chromium with Playwright passed at **375×667**, **390×844**, and **430×932** portrait, **844×390** and **932×430** landscape, and an extra **320×640** check. The **1440×900** desktop sweep covered the sidebar, Chat, calls, and the workspace views. All sweeps completed without JavaScript or console errors. The harness used an isolated workspace with Mock, fixture Inbox mail, and synthetic microphone input. The Browser plugin was unavailable.

| Area | Verification |
| --- | --- |
| Navigation and Chat | Tested bottom tabs and the More sheet, one-tap access to the thread sheet, side-chat creation and switching, Ember full-screen and return, and the mic, call, and send controls on one row. Checked Markdown and artifact chips. An 800-character URL and code token wrapped within the transcript. |
| Viewport and PWA | Checked the standalone manifest, Apple Home Screen metadata and icon, and `viewport-fit=cover`. Chromium simulated a shrinking and panning visual viewport. The composer stayed within it and the tab bar returned on dismissal. A separate Safe Area test supplied 47/34/12/10 px for top, bottom, left, and right. |
| Workspace views | Opened Timeline details, checked Artifacts as a list, edited a preview in the full-screen drawer, and scrolled a ten-column CSV inside its table viewport. Checked the reminder form and its Settings shortcut, forwarded Inbox, Memory, Connections tabs, and all seven Settings disclosures. Sampled interactive controls met 44 px and sampled entry fields used at least 16 px type. |
| Voice and appearance | Exercised full-screen demo calls, mute, minimize, resume, and hang-up. Started and canceled dictation with the mobile overlay. Swept dark mode at 390 px and used reduced motion throughout. |

Physical iPhone Safari, the operating system keyboard animation, and installation from the iOS share sheet remain unverified. The keyboard check exercised the visual viewport response in Chromium. [WebKit visual viewport timing](https://bugs.webkit.org/show_bug.cgi?id=265578), [Apple status-bar metadata](https://developer.apple.com/library/archive/documentation/AppleApplications/Reference/SafariHTMLRef/Articles/MetaTags.html)

### 390×844 captures

[Mobile overview](/workspace/tmp/hearth-qa/mobile-overview.png)

| Screen | Before | After |
| --- | --- | --- |
| Chat | [Before](/workspace/tmp/hearth-qa/mobile-chat-before.png) | [After](/workspace/tmp/hearth-qa/mobile-chat-after.png), [Markdown and chips](/workspace/tmp/hearth-qa/mobile-chat-markdown-after.png) |
| Chat threads | [Before](/workspace/tmp/hearth-qa/mobile-threads-before.png) | [After](/workspace/tmp/hearth-qa/mobile-threads-after.png) |
| Timeline | [Before](/workspace/tmp/hearth-qa/mobile-timeline-before.png) | [After](/workspace/tmp/hearth-qa/mobile-timeline-after.png) |
| Artifacts | [Before](/workspace/tmp/hearth-qa/mobile-artifacts-before.png) | [After](/workspace/tmp/hearth-qa/mobile-artifacts-after.png) |
| Artifact detail | [Before](/workspace/tmp/hearth-qa/mobile-artifact-detail-before.png) | [After](/workspace/tmp/hearth-qa/mobile-artifact-detail-after.png) |
| Reminders | [Before](/workspace/tmp/hearth-qa/mobile-reminders-before.png) | [After](/workspace/tmp/hearth-qa/mobile-reminders-after.png) |
| More | [Workspace links before](/workspace/tmp/hearth-qa/mobile-more-before.png) | [After](/workspace/tmp/hearth-qa/mobile-more-after.png) |
| Inbox | [Before](/workspace/tmp/hearth-qa/mobile-inbox-before.png) | [After](/workspace/tmp/hearth-qa/mobile-inbox-after.png) |
| Memory | [Before](/workspace/tmp/hearth-qa/mobile-memory-before.png) | [After](/workspace/tmp/hearth-qa/mobile-memory-after.png) |
| Connections | [Before](/workspace/tmp/hearth-qa/mobile-connections-before.png) | [After](/workspace/tmp/hearth-qa/mobile-connections-after.png) |
| Settings | [Before](/workspace/tmp/hearth-qa/mobile-settings-before.png) | [After](/workspace/tmp/hearth-qa/mobile-settings-after.png), [Open Brain section](/workspace/tmp/hearth-qa/mobile-settings-brain-after.png) |
| Call | [Before](/workspace/tmp/hearth-qa/mobile-call-before.png) | [After](/workspace/tmp/hearth-qa/mobile-call-after.png) |
| Voice input | [Before](/workspace/tmp/hearth-qa/mobile-voice-before.png) | [After](/workspace/tmp/hearth-qa/mobile-voice-after.png) |

[Simulated keyboard](/workspace/tmp/hearth-qa/mobile-keyboard-after.png), [Safe areas](/workspace/tmp/hearth-qa/mobile-safe-area.png), [Landscape Chat](/workspace/tmp/hearth-qa/mobile-chat-landscape.png), [Landscape Call](/workspace/tmp/hearth-qa/mobile-call-landscape.png), [Dark Settings](/workspace/tmp/hearth-qa/mobile-dark-settings-brain.png), [Desktop Chat](/workspace/tmp/hearth-qa/mobile-desktop-chat.png)

### Live Box upload

The deployed `POST /api/artifacts/create` returned **201** and synchronized to Box. The deployed `POST /api/artifacts/update` returned **200** for the same file. A detail request after the final deployment returned version 2 and both receipts. The direct gateway request to `GET 2.0/files/2614704783851/versions` returned **403** with “request is not supported by this connector.” Hearth used its saved history. The live verification file remains in Box. [Box verification file](https://app.box.com/file/2614704783851)

| Receipt | ID |
| --- | --- |
| Hearth artifact | `4a2a28b60023449ebe6abaf5f1a156b5` |
| Box file | `2614704783851` |
| Box version 1 | `2902976041451` |
| Box version 2 | `2902968544059` |

The Box fixture checked both gateway upload paths, multipart ordering, the 50 MiB file limit, fallback and retry, and workspace-only Trash and restore. `python3 -m unittest discover -s tests` passed **91 tests**. `node --test tests/*.test.mjs` passed **5 tests**. Every `web/*.js` file passed `node --check`. `scripts/deploy.sh` succeeded. The authenticated Sprite `/health` responded with `{"ok": true, "checkpoints": "sprite"}`, and the hashes for seven served assets matched the local files.

## Round 2

November 25, 2026 UTC · `main` · Sprite runtime commit `37caf1e`

The Mock demo flow passed. Round 2 reproduced defects in Inbox polling, chat rendering, keyboard focus, connection testing and idle Chat transfer. The runtime fixes were deployed to the private Hearth Sprite.

| Area | Result | Round 2 evidence |
| --- | --- | --- |
| 0. Artifacts and Box | Open | Chromium exercised chat creation, preview, CSV, grid/list, filters, download, edits, deletion during reload and return focus after editing. The Box fixture covered sync, the file link, version history, Trash and Undo. Sprite listing and preview responded. Live Box upload and version writes remain blocked by the known gateway 403. |
| 1. Chat | Fixed | Both widths covered streaming, completion, Markdown, long and unusual text, model chips, interrupted SSE and retry. Tests exercised fallback after a tool action, split/self-closing tool tags and incomplete credentials. The Sprite exposed two older replies with tool tags before deployment and zero after sanitization. Live greeting and action requests returned replies in an isolated Sprite workspace. |
| 2. Side chats | Pass | At both widths, Main and side turns overlapped, switching preserved isolation, and reload during another turn kept the selected thread and recovered its saved reply. A local process restart preserved the started prompt, cleared volatile queued work, and accepted a new retry. |
| 3. Memory | Open | Chromium exercised note save, local recall, Remembered disclosure, settings and the Pinecone fixture. The suite covered English and Chinese matching and vector deletion/reindex after Forget, Undo and Redo. Live Pinecone remains blocked by the known 403 on index creation. |
| 4. Timeline | Pass | Both widths rendered and opened all 17 supported kinds using an exhaustive fixture, with search, filter, empty results and live arrival of an artifact event. Separate flows exercised real tool, connector, reminder, Inbox, Voice and Undo entries. Live Sprite Timeline snapshots loaded in Chromium. |
| 5. Undo | Pass | Verified reversible note changes, reminder cancellation, Inbox imports, artifact create/update/Trash, simulated email and local checkpoint restore against server state. Native checkpoint restore on the shared Sprite remains outside the verified scope because a restore would roll back the shared workspace. |
| 6. Reminders and wake | Open | Both widths exercised channel selection, list, in-app and email test controls, disconnected Outbox, and the action page. The suite verified natural-language channels, quiet hours, urgent bypass, retries and signed-link replay. The Sprite was cold before the 15:24:28 UTC due time and immediately before authenticated wake. One in-app delivery appeared at 15:24:37 UTC, a second tick produced zero duplicate deliveries, and an unsigned tick returned 401. The recipient stayed empty and no real reminder email was sent. The external periodic wake workflow remains inactive. |
| 6b. Forward-to-Hearth Inbox | Fixed | Browser polling, manual polling over a pending check, simultaneous drafts, flight/booking/receipt/school/Chinese/plain messages, instruction-like text and ICS attachments were exercised against the fixture. Tests covered the cursor, allowlist/DMARC, opt-in acknowledgment, and Accept/Edit/Undo effects. After deployment, two forced polls returned HTTP 200 with zero new imports, and the single existing flight still appeared at both widths. |
| 7. Connections | Fixed | Both widths covered configured/catalog tabs, keyboard switches, search and filtering. The live sweep reproduced a Test 409 during discovery. The regression suite exercises discovery contention for Rescan, Test and Memory search. Configured checks were verified for Hugging Face, Exa, Pinecone, Box and Vocal Bridge. |
| 8. Settings | Pass | Chromium visited Brain, Memory, Search, Reminders, Artifacts, Appearance, Voice and Calls at both widths. Routing preview classified greeting and action prompts separately. The suite covered model-pool tags and routing/fallback. Chinese call language and transcript preferences persisted in the demo. |
| 9. Ember | Pass | A complete Mock turn exercised all nine poses, captions, placement and full-screen mode, presets, color, reduced motion and side-thread activity. Keyboard controls and pose announcements were checked. |
| 10. Voice input | Pass | Chromium exercised microphone, level meter, hold-Space, Escape, edit, auto-send, permission denial and unsupported feedback with synthetic audio or browser fixtures. The Sprite Whisper endpoint returned HTTP 200 with a nine-word transcription in 1.242 s. Synthetic speech accuracy beyond that sample remains unmeasured. |
| 11. Vocal Bridge | Open | Chromium exercised demo call controls and saved Main and side-chat transcript cards. The suite verified redaction. The configured Sprite minted one real token with HTTP 200 and `Cache-Control: no-store`. The token stayed out of output. Chromium could not negotiate the LiveKit connection through the harness proxy, so a real conversation and its language hint remain unverified. |
| 12. Shell and assets | Pass | Shell title, icons, manifest, 404, responsive width, network and page errors were checked. The authenticated Sprite CLI proxy reset TCP connections. The browser used a loopback relay for real Sprite APIs and static files checked against remote hashes. The relay did not forward Timeline's long-lived event stream, which was tested locally and checked directly on the Sprite. |
| 13. Security | Fixed | Tests checked the shared origin gate, oversized or malformed bodies, lone surrogates, non-finite numbers, signed actions, and transcript/stream redaction. HTML-shaped text in chat, a side-chat title and memory stayed literal in Chromium. A targeted `git grep` found no tracked key-pattern matches. |
| 14. Accessibility | Fixed | Keyboard navigation, focus visibility, disclosure, reduced motion, and artifact return focus passed at 1440 and 390 px. The chat regression keeps an expanded Remembered item and its keyboard focus through other-tab updates. Sampled CSS contrast was 4.89:1 for unselected navigation, 8.11:1 for selected navigation, and 5.38:1 for the focus outline on the page background. Full screen-reader and WCAG audits remain unverified. |
| 15. Performance | Fixed | A 320-message thread transferred 211–215 KB every three seconds before the fix. Two idle checks at each width returned 304 with zero response body after it. The final Sprite loaded 273 KB of static resources with the call SDK deferred. Mock reply paint was 0.41–0.50 s. Live Sprite first token was 1.205 s for the greeting and 2.724 s for the action turn. A 14-cycle Chat/Timeline navigation sample retained about 0.29 MB more JavaScript heap after garbage collection at each width. Multi-hour behavior and server-side work on large state remain unmeasured. |

### Round 2 defects

| Severity | Defect | Fix and verification | Commit |
| --- | --- | --- | --- |
| High | AgentMail rejected the persisted `after` cursor once Hearth had imported a message. Subsequent browser and wake polls could stop importing new mail. | Convert stored UTC offsets to `Z` at the AgentMail boundary. The live gateway returned 400 for the saved offset and 200 for the same instant in the fixed format. | `37caf1e` |
| Medium | Chat streamed Mock note excerpts with raw tool markup, self-closing tags could swallow following text, and old saved replies still displayed tool tags. | Apply the same filter before Mock emission, preserve following text, and sanitize archived replies when read. | `cc2ec03` |
| Medium | Check mail silently dropped requests during a browser poll, could return completion when the connector failed, and a different card's action destroyed open Inbox drafts. | Queue an explicit manual check after browser polling, wait for the Inbox lock, surface connector errors, and preserve active editor nodes. | `cc2ec03` |
| Medium | Unchanged chat messages were replaced after another-tab update, closing disclosures and clearing keyboard focus. | Keep unchanged message nodes in place while reconciling the transcript. Verified at both widths. | `cc2ec03` |
| Medium | Idle Chat repeatedly transferred complete long conversations. | Send entity tags with state responses and reuse the current snapshot on a 304. | `aa9e277` |
| Medium | Connection tests could return 409 during normal background discovery. | Reuse the bounded operation-lock wait for Test. | `37caf1e` |
| Medium | Incomplete private key blocks and non-finite or truncated JSON were not handled consistently. | Redact unfinished key blocks and reject non-finite JSON and early EOF up front. | `aa9e277`, `cc2ec03` |
| Low | Closing an artifact after saving an edit moved keyboard focus to Search. | Restore focus to the artifact's replacement opener and keep it through list refresh. | `37caf1e` |

### Round 2 verification and captures

- `python3 -m unittest discover -s tests` passed **89 tests**. `node --test tests/*.test.mjs` passed **5 tests**. `node --check` passed for every `web/*.js` file. `scripts/deploy.sh` and the requested authenticated `sprite exec --http-post --no-stdin --no-port-forward -o xuefeng-zhu -s hearth` health check passed.
- Six adversarial Chromium scenarios and three focused regression checks passed at each width. The deployed desktop and mobile sweeps reported no JavaScript or console errors. Twenty-one deployed web files matched the local runtime by SHA-256.
- Overview at [1440 px](/workspace/tmp/hearth-qa/qa-overview-desktop.png) and [390 px](/workspace/tmp/hearth-qa/qa-overview-mobile.png). The single deployed Inbox flight import at [1440 px](/workspace/tmp/hearth-qa/qa-inbox-desktop.png) and [390 px](/workspace/tmp/hearth-qa/qa-inbox-mobile.png).
- Chat disclosure and focus on [desktop before](/workspace/tmp/hearth-qa/qa-r2-chat-disclosure-before-1440.png), [desktop after](/workspace/tmp/hearth-qa/qa-r2-chat-disclosure-after-1440.png), [mobile before](/workspace/tmp/hearth-qa/qa-r2-chat-disclosure-before-390.png) and [mobile after](/workspace/tmp/hearth-qa/qa-r2-chat-disclosure-after-390.png).
- Archived tool markup on [desktop before](/workspace/tmp/hearth-qa/qa-r2-sanitizer-before-1440.png), [desktop after](/workspace/tmp/hearth-qa/qa-r2-sanitizer-after-1440.png), [mobile before](/workspace/tmp/hearth-qa/qa-r2-sanitizer-before-390.png) and [mobile after](/workspace/tmp/hearth-qa/qa-r2-sanitizer-after-390.png).
- Manual Inbox poll on [desktop before](/workspace/tmp/hearth-qa/qa-r2-inbox-poll-before-1440.png), [desktop after](/workspace/tmp/hearth-qa/qa-r2-inbox-poll-after-1440.png), [mobile before](/workspace/tmp/hearth-qa/qa-r2-inbox-poll-before-390.png) and [mobile after](/workspace/tmp/hearth-qa/qa-r2-inbox-poll-after-390.png). Parallel edit drafts at [1440 px](/workspace/tmp/hearth-qa/qa-r2-inbox-drafts-1440.png) and [390 px](/workspace/tmp/hearth-qa/qa-r2-inbox-drafts-390.png).
- Artifact return focus on [desktop before](/workspace/tmp/hearth-qa/qa-r2-artifact-focus-before-1440.png), [desktop after](/workspace/tmp/hearth-qa/qa-r2-artifact-focus-after-1440.png), [mobile before](/workspace/tmp/hearth-qa/qa-r2-artifact-focus-before-390.png) and [mobile after](/workspace/tmp/hearth-qa/qa-r2-artifact-focus-after-390.png).
- Timeline kinds at [1440 px](/workspace/tmp/hearth-qa/qa-r2-timeline-kinds-1440.png) and [390 px](/workspace/tmp/hearth-qa/qa-r2-timeline-kinds-390.png). [Box fixture](/workspace/tmp/hearth-qa/qa-r2-artifact-detail.png), [Pinecone fixture](/workspace/tmp/hearth-qa/qa-r2-pinecone-recall.png), [Outbox](/workspace/tmp/hearth-qa/qa-r2-reminder-email.png) and [Vocal Bridge demo](/workspace/tmp/hearth-qa/qa-r2-call-live.png).

## 90-second demo

Use a demo workspace with **Mock** selected and **Auto-save to Box** off. Leave the sample email draft awaiting approval.

| Time | Action |
| --- | --- |
| 0–15 s | Open Chat and select **Plan Thanksgiving dinner**. Show Ember changing poses while Hearth recalls the sample notes and creates the two files. |
| 15–30 s | Open **Remembered** to show the source notes. Point out the invitation awaiting approval and the in-app reminder. |
| 30–48 s | Open **Saved “Thanksgiving plan” locally**. Scroll the inline PDF preview from the menu to the kitchen timeline, then select **Download**. |
| 48–65 s | Open **Saved “Shopping list” locally**. Show the **Groceries** sheet preview with quantities in their own column and download the XLSX. |
| 65–78 s | Open **Artifacts** and show the PDF and XLSX cards with their types, sizes, version 1, and local status. |
| 78–90 s | Show the file’s **Hearth version history**. Explain that a connected brain can edit the file when asked, for example “add a column for cost.” |

## Round 1

November 25, 2026 UTC · `main` · runtime release `9e35978`

### Coverage

**Pass** means the stated checks succeeded. **Fixed** means a QA defect was corrected and rechecked. **Open** means an integration or verification gap remains, even where the rest of the area passed.

| Area | Result | Evidence and limits |
| --- | --- | --- |
| 0. Artifacts and Box | Open | Chromium verified chat-created artifacts, list/grid, search, preview, edits, copy, download, status, deletion and Undo with the Box fixture. The fixture covered upload, versioning, Trash restore and the original Box link. The deployed connector can list files. Live upload and version writes remain unavailable through the configured gateway. The local-only and failed-sync copies remain usable. |
| 1. Chat | Fixed | Chromium checked Mock replies, chip, rendered Markdown, a 3,900-character prompt, escaped text and interruption/retry. Tests cover split tool markup, provider fallback and suppression of replay after a state-changing tool. The deployed release routed a greeting to Llama and a reminder to Qwen, with one in-app job created in an isolated Sprite workspace. No live outage was induced. |
| 2. Side chats | Pass | Chromium checked creation, thread switching and reload persistence. The thread suite covers isolated context, simultaneous turns, queued ordering and deleted sources. A real local process restart confirmed that pending turns are cleared, the started prompt remains in history, and retry works after startup. |
| 3. Memory | Open | Chromium exercised save/recall, Settings, local fallback, and fixture Pinecone sync/rebuild/status. The gateway fixture and suite cover English and Chinese queries, deletion and reindexing after Undo/Redo. The real connector has no usable `hearth-memory` index, so live vector reads, writes and deletion remain unverified. |
| 4. Timeline | Open | Chromium checked search, empty results, filtering, expansion, Raw details, and live chat/voice/reminder updates across the local sweep and targeted checks. Coverage across feature suites includes chat, routing, recall, memory, email, reminders, voice, search, artifacts, Inbox, connector activity and checkpoints. An exhaustive rendered assertion for every event subtype remains open. |
| 5. Undo | Pass | Verified item-level server reversions for notes, artifacts, reminders and Inbox acceptance, plus local workspace restore and simulated email state. The suite covers artifact conflicts and guarded approvals. Real email delivery and other provider-side operations remain external. No native rollback of the shared Sprite was run during this QA pass. |
| 6. Reminders and wake | Open | Desktop and mobile Chromium covered channels, creation, listing, Undo, late delivery, test controls and the disconnected Outbox. Automated checks cover quiet hours, urgent bypass, retry keys, dedupe, signed Done/Snooze, expiry, and replay. Authenticated wake caught up the deployed in-app reminder due at 11:59:10 UTC at 12:05:51 UTC. The saved recipient was empty and stayed empty. AgentMail reminder delivery was not sent live. The external periodic wake workflow is still inactive. |
| 6b. Forward-to-Hearth Inbox | Fixed | Manual **Check mail** now bypasses the background poll interval. The deployed Inbox contains exactly one flight import and a subsequent poll reported no duplicate. Fixtures cover flight, receipt, school, Chinese, plain mail, attachments, ICS, cursor, sender authentication, opt-in acknowledgments, and injection-like text. Chromium exercised Accept, Edit, Dismiss and Undo against six local mail fixtures. The existing live flight was already Undone. No second live flight or acknowledgment was sent. |
| 7. Connections | Pass | Chromium covered both tabs, keyboard switching, search and the configured/catalog distinction. Concurrent discovery and Memory searches now wait briefly for ordinary lock contention. The deployed checks exercised Hugging Face, Exa, Pinecone, Box and Vocal Bridge. A gateway authorization check alone does not establish support for specific write endpoints. |
| 8. Settings | Pass | Chromium exercised Brain, Memory, Search, Appearance, Voice, Calls, Reminders and Artifacts at the requested widths. Model pool tags, routing/fallback and disconnected search adapters are covered by fixture or Python tests. |
| 9. Ember | Pass | Chromium observed idle, listening, thinking, working, concerned, speaking, remembering, happy and sleeping. Checked placement, full screen/captions, pose announcements, presets, color, reduced motion and activity across threads. |
| 10. Voice input | Pass | Chromium exercised the mic, fake-microphone recording/level, hold-Space, Escape, interim speech, edit/auto-send, permission denied and unsupported feedback. The deployed Whisper endpoint transcribed the synthetic WebM correctly in 0.756 s. |
| 11. Vocal Bridge | Open | Chromium completed demo calls, live-sheet controls and transcript persistence on Main and a side chat. Tests cover transcript redaction and token isolation. The configured release minted one real credential with HTTP 200 and `Cache-Control: no-store`. The token was never printed. A fresh real WebRTC conversation and the agent’s use of the non-Auto language hint remain unverified in this pass. |
| 12. Shell and assets | Pass | Chromium checked the Hearth title, manifest, icons, broken-image state and responsive layout. The app returns a JSON 404 for unknown routes. The final local browser sweep recorded no console errors at either width. Sprite release asset hashes were compared with the files loaded in the QA browser. The CLI relay occasionally could not carry large JSON responses, so coverage of the full live browser flow is incomplete. |
| 13. Security | Fixed | Every POST handler shares the origin gate, including endpoints that accept raw audio. The scheduler also requires its separate token. Regression tests cover malformed, oversized and deeply nested JSON, escaped user text and credential redaction. `git grep` found no matches for the checked API key, GitHub, Hugging Face, Pinecone, Slack or private-key patterns in tracked files. This was a targeted review of user-facing data paths. |
| 14. Accessibility | Pass | A Chromium keyboard walkthrough checked navigation, visible composer focus, Escape, Timeline disclosure and reduced motion. Labels were checked on chat, voice, search and settings controls. The sampled color pairs had contrast ratios from 5.30:1 to 7.10:1. Full screen-reader and WCAG conformance audits were outside this pass. |
| 15. Performance | Open | Chromium measured 269,980 bytes of initial static resources with the call SDK deferred. Idle Chat made two state requests in 6.5 seconds at each width. Local Mock reply paint was approximately 0.41–0.48 s in the instrumented browser. On the Sprite, greeting first token was 0.554 s and tool-turn first token 2.806 s. Completed background turns are released from client memory. Long-session heap behavior and large workspace performance remain unmeasured. |

### Defects and fixes

| Severity | Defect | Fix and verification | Commit |
| --- | --- | --- | --- |
| High | Some POST handlers checked only `Sec-Fetch-Site: cross-site`, while newer routes also enforced exact Origin. | Put the exact-origin gate in front of all POST dispatch. Regression checks cover route families and scheduler authentication. | `8223375` |
| Medium | Several JSON body readers could wait indefinitely on a stalled request. Lone Unicode surrogates and extreme JSON nesting could also interrupt a request instead of returning a handled error. | Bound body reads and reject invalid inputs. Tests cover size, surrogate and nesting cases. The same change redacts recognized credentials when reading legacy Markdown through the Memory API. | `8223375` |
| Medium | Provider replies could display or store model-control markup such as `</function>`. Stream deltas and model-generated draft email could also expose recognized credential strings before redaction. | Filter split model markup and redact before publishing streamed deltas, saving replies, or staging email content. Tests split tool tags and credentials across deltas and check the transcript and events. | `160a425` |
| Medium | Completed assistant answers showed Markdown control characters as plain paragraphs. | Reuse the existing text-node Markdown renderer for completed replies. Desktop and mobile Chromium verified headings and literal handling of unfamiliar tags. | `e05c738` |
| Medium | **Check mail** used the same throttle as background polling and could report completion without contacting AgentMail. | Send an explicit manual flag through the same-origin endpoint. Regression checks verify that manual polling fetches immediately and deduplicates subsequent mail. | `d409cf5` |
| Medium | An interrupted chat could keep partial text while losing the explanation and leaving the prompt difficult to retry. | Keep the error on the turn and add **Edit and retry**. The action restores the prompt to an empty composer and preserves an existing draft. Chromium exercised this with an interrupted SSE fixture. | `4724048` |
| Medium | Multiple tabs could trigger 409s on Connections discovery and Memory search during ordinary lock contention. | Allow a bounded wait. A regression test holds the operation lock during each request and verifies both complete successfully. | `9e35978` |
| Low | Completed turns in background threads could remain in the client’s pending set until the user reopened the thread. | Release completed turns after the server saves them. Clean up local thread state when the server reports that a selected thread no longer exists. | `4724048` |

### Verification and remaining risks

- `python3 -m unittest discover -s tests` passed **84 tests**. `node --test tests/*.test.mjs` passed **5 tests**. `node --check` passed for each file under `web/*.js`. `scripts/deploy.sh` and the subsequent authenticated `sprite exec --http-post --no-stdin --no-port-forward -o xuefeng-zhu -s hearth` health check passed.
- Used Chromium at **1440 px** and **390 px** with Playwright because the Browser plugin was unavailable. Local checks used isolated workspaces and deterministic provider fixtures. Deployed checks used the private Sprite through authenticated CLI access. The public entry URL required Sprite sign-in. Browser checks against the deployed API used a loopback relay with byte-matched static assets. Live SSE timings were measured inside the Sprite.
- The live Pinecone connector still needs a usable index. The live Box connector’s write restrictions make the upload path a poor demo dependency. External wake cadence determines the worst-case delivery delay when the Sprite sleeps. Real-time delivery below that cadence requires another wake source.
- Pending chat turns are intentionally volatile under the current design. An automatic replay after restart could repeat tools that changed workspace state. Retry is an explicit user action. Larger histories also increase idle Chat transfer and render cost.
- The configured private Sprite received no outbound reminder test email. Testing used an in-app cold-wake job and a separate local fixture for reminder emails.

### Captures

- Overview at [1440 px](/workspace/tmp/hearth-qa/qa-overview-desktop.png) and [390 px](/workspace/tmp/hearth-qa/qa-overview-mobile.png).
- Markdown before and after on [desktop before](/workspace/tmp/hearth-qa/qa-markdown-before-1440.png), [desktop after](/workspace/tmp/hearth-qa/qa-markdown-after-1440.png), [mobile before](/workspace/tmp/hearth-qa/qa-markdown-before-390.png) and [mobile after](/workspace/tmp/hearth-qa/qa-markdown-after-390.png).
- Interrupted reply and retry on [desktop](/workspace/tmp/hearth-qa/qa-retry-after-1440.png) and [mobile](/workspace/tmp/hearth-qa/qa-retry-after-390.png).
- The single live flight import in Inbox at [1440 px](/workspace/tmp/hearth-qa/qa-inbox-desktop.png) and [390 px](/workspace/tmp/hearth-qa/qa-inbox-mobile.png).
- Timeline at [1440 px](/workspace/tmp/hearth-qa/qa-timeline.png) and [390 px](/workspace/tmp/hearth-qa/qa-timeline-mobile.png).
- [Box fixture](/workspace/tmp/hearth-qa/qa-artifact-detail.png), [Pinecone fixture](/workspace/tmp/hearth-qa/qa-pinecone-recall.png), [reminder Outbox](/workspace/tmp/hearth-qa/qa-reminder-email.png), and [demo call](/workspace/tmp/hearth-qa/qa-call-live.png).
